# app/services/question_service.py

# 발표 상황에 맞는 질문 생성, 추가 질문 생성, 사용자 답변 평가를 담당하는 Question Engine 서비스
#
# 최소 프롬프팅 버전:
# - 지금까지 들은 발표 내용만 기반으로 질문 생성
# - 발표 중간에 실제 청중이 끼어드는 듯한 자연스러운 질문 생성
# - 질문은 짧게 1문장, 1개의 궁금증만 생성
# - 발표자가 뒤에서 설명할 수도 있는 내용은 단정적으로 비판하지 않음
# - 답변 평가는 JSON으로만 받음
# - OpenAI 실패 시 룰 기반 로직으로 폴백

import asyncio
import json
import re
from typing import List

from openai import OpenAI

from app.core.config import settings
from app.schemas.question import (
    QuestionGenerationInput,
    QuestionGenerationResult,
    AnswerEvaluationInput,
    AnswerEvaluationResult,
)


try:
    _openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
except Exception as _e:
    print(f"[QuestionService OpenAI 초기화 실패] {_e}")
    _openai_client = None


class QuestionService:
    """
    Question Engine 서비스

    주요 기능
    - 발표 맥락 기반 질문 생성
    - 사용자 답변 평가
    - 필요 시 후속 질문 생성

    OpenAI API 연결 실패 또는 API Key 미설정 시 룰 기반 로직으로 폴백한다.
    """

    async def analyze_presentation_style(self, context: str) -> str:
        """
        현재 버전에서는 발표 스타일 분석을 복잡하게 하지 않는다.
        기존 호출부와의 호환성을 위해 함수는 유지하되 항상 general을 반환한다.
        """
        return "general"

    async def generate_question_ai(
        self,
        data: QuestionGenerationInput,
        presentation_style: str = "general"
    ) -> QuestionGenerationResult:
        """
        OpenAI로 최근 발표 맥락 기반 질문 생성.

        방향:
        - 실제 청중처럼 자연스럽게 질문
        - 발표 중간에 끼어들 수 있는 짧은 질문
        - 질문은 1개만 생성
        - 너무 길거나 복합적인 질문은 피함
        - 발표자가 뒤에서 설명할 수 있는 내용은 단정적으로 공격하지 않음
        - 첫 질문 후 사용자 답변 평가 후, 답변이 부족하다 판단되면
        - 사용자 답변 평가 후, 답변이 부족하다 판단되면 꼬리질문 생성
        - 꼬리질문은 최대 2번까지만 생성 가능
        - 꼬리질문은 사용자의 답변을 바탕으로 자연스럽게 이어지도록 생성
        - 모든 질문은 존댓말로 할것
        """
        if _openai_client is None:
            return self.generate_question(data)

        context = " ".join(data.recent_context[-4:]) if data.recent_context else "발표 내용 없음"
        previous_questions = "\n".join(f"- {q}" for q in data.previous_questions[-3:]) or "없음"

        prompt = f"""
너는 발표를 듣고 있는 실제 청중이다.

지금까지 들은 발표 내용을 바탕으로, 발표 중간에 자연스럽게 끼어들 수 있는 질문을 1개만 만들어라.

조건:
- 질문은 한국어로 작성한다.
- 한 문장으로만 질문한다.
- 하나의 궁금증만 묻는다.
- 지금까지 나온 내용과 직접 관련된 질문이어야 한다.
- 너무 길거나 복잡하게 만들지 않는다.
- 발표자가 뒤에서 설명할 수 있는 내용은 단정하지 말고 조심스럽게 묻는다.
- 질문은 너무 완성된 논문 심사 질문처럼 만들지 말고, 발표를 들으며 바로 떠오른 궁금증처럼 작성한다.
- 실제 사람이 말하듯 자연스러운 말투로 작성한다.
- 이전 질문과 비슷한 질문은 피한다.
- 말머리, 번호, 설명 없이 질문 문장만 출력한다.

참고 정보:
- 현재 발표 주제: {data.current_topic or "알 수 없음"}
- 발표 유형: {data.presentation_type}
- 청중 유형: {data.audience_type}
- 압박 강도: {data.pressure_level}

이전 질문:
{previous_questions}

지금까지 들은 발표 내용:
{context}
""".strip()

        try:
            result = await asyncio.to_thread(
                _openai_client.responses.create,
                model=settings.openai_question_model,
                input=prompt,
            )

            question_text = result.output_text.strip().splitlines()[0]
            question_text = self._clean_generated_question(question_text)
            question_text = self._simplify_question_if_compound(question_text)

            if not question_text:
                return self.generate_question(data)

            return QuestionGenerationResult(
                question_text=question_text,
                question_difficulty=self._select_question_difficulty(data.pressure_level),
                question_type="ai_generated",
            )

        except Exception as e:
            print(f"[OpenAI 질문 생성 실패] {e} — 룰 기반 폴백")
            return self.generate_question(data)

    async def evaluate_answer_ai(self, data: AnswerEvaluationInput) -> AnswerEvaluationResult:
        """
        OpenAI로 사용자 답변 평가 및 필요 시 꼬리질문 생성.
        """
        if _openai_client is None:
            return self.evaluate_answer(data)

        recent_context = " ".join(data.recent_context[-2:]) if data.recent_context else "없음"

        follow_up_count = getattr(data, "follow_up_count", 0)
        max_follow_ups = getattr(data, "max_follow_ups", 2)

        try:
            follow_up_count = int(follow_up_count)
        except Exception:
            follow_up_count = 0

        try:
            max_follow_ups = int(max_follow_ups)
        except Exception:
            max_follow_ups = 2

        can_generate_follow_up = follow_up_count < max_follow_ups

        prompt = f"""
너는 발표 Q&A 상황에서 발표자의 답변을 평가하는 평가자다.
질문에 대해 사용자의 답변이 충분한지 판단해라.

[질문]
{data.question_text}

[사용자 답변]
{data.user_answer}

[현재 발표 주제]
{data.current_topic or "알 수 없음"}

[최근 발표 맥락]
{recent_context}

[꼬리질문 상태]
- 현재 꼬리질문 횟수: {follow_up_count}
- 최대 꼬리질문 횟수: {max_follow_ups}
- 꼬리질문 생성 가능 여부: {can_generate_follow_up}

평가 기준:
- 질문에 직접 답했는가?
- 답변이 구체적인가?
- 발표 맥락과 연결되는가?
- 이유나 예시가 있는가?

반드시 JSON만 출력해라.
형식은 아래와 같다.

{{
  "score": 70,
  "sufficient": true,
  "follow_up": null
}}

답변이 부족하면 아래처럼 출력해라.

{{
  "score": 40,
  "sufficient": false,
  "follow_up": "조금 더 구체적인 예시를 들어 주실 수 있나요?"
}}

규칙:
- score가 70 이상이면 sufficient는 true다.
- score가 70 미만이면 sufficient는 false다.
- 꼬리질문 생성 가능 여부가 false이면 follow_up은 반드시 null이다.
- sufficient가 false이고 꼬리질문 생성 가능 여부가 true이면 follow_up에 짧은 꼬리질문을 작성한다.
- sufficient가 true이면 follow_up은 null이다.
- follow_up은 사용자의 답변에서 부족한 부분을 자연스럽게 되묻는 질문이어야 한다.
- follow_up은 새로운 주제를 꺼내지 않는다.
- follow_up은 한 문장으로만 작성한다.
""".strip()

        try:
            result = await asyncio.to_thread(
                _openai_client.responses.create,
                model=settings.openai_question_model,
                input=prompt,
            )

            text = result.output_text.strip()

            if text.startswith("```"):
                text = text.replace("```json", "").replace("```", "").strip()

            parsed = json.loads(text)

            score = float(parsed.get("score", 50))
            score = max(0.0, min(score, 100.0))

            sufficient = bool(parsed.get("sufficient", score >= 70))
            follow_up = parsed.get("follow_up")

            follow_up_needed = (
                not sufficient
                and score < 70
                and follow_up_count < max_follow_ups
            )

            if not follow_up_needed:
                follow_up = None

            if follow_up:
                follow_up = self._clean_generated_question(str(follow_up))
                follow_up = self._simplify_question_if_compound(follow_up)

            return AnswerEvaluationResult(
                answer_score=round(score, 2),
                follow_up_needed=follow_up_needed,
                audience_reaction=self._select_audience_reaction(score),
                evaluation_reason="AI 평가 완료",
                follow_up_question=follow_up,
            )

        except Exception as e:
            print(f"[OpenAI 답변 평가 실패] {e} — 룰 기반 폴백")
            return self.evaluate_answer(data)

    def generate_question(
        self,
        data: QuestionGenerationInput
    ) -> QuestionGenerationResult:
        """
        OpenAI 호출 실패 시 사용하는 룰 기반 질문 생성.
        """
        question_type = self._select_question_type(
            audience_type=data.audience_type,
            presentation_type=data.presentation_type,
            pressure_level=data.pressure_level
        )

        question_difficulty = self._select_question_difficulty(
            pressure_level=data.pressure_level
        )

        question_text = self._build_question_text(
            current_topic=data.current_topic,
            recent_context=data.recent_context,
            audience_type=data.audience_type,
            presentation_type=data.presentation_type,
            pressure_level=data.pressure_level,
            previous_questions=data.previous_questions,
            question_type=question_type
        )

        question_text = self._clean_generated_question(question_text)
        question_text = self._simplify_question_if_compound(question_text)

        return QuestionGenerationResult(
            question_text=question_text,
            question_difficulty=question_difficulty,
            question_type=question_type
        )

    def evaluate_answer(
        self,
        data: AnswerEvaluationInput
    ) -> AnswerEvaluationResult:
        """
        OpenAI 호출 실패 시 사용하는 룰 기반 답변 평가.
        """
        answer_score = self._calculate_answer_score(
            question_text=data.question_text,
            user_answer=data.user_answer,
            current_topic=data.current_topic,
            recent_context=data.recent_context
        )

        follow_up_needed = answer_score < 60
        audience_reaction = self._select_audience_reaction(answer_score)

        evaluation_reason = self._build_evaluation_reason(
            answer_score=answer_score,
            user_answer=data.user_answer
        )

        follow_up_question = None

        if follow_up_needed:
            follow_up_question = self._build_follow_up_question(
                question_text=data.question_text,
                current_topic=data.current_topic,
                user_answer=data.user_answer,
                pressure_level=data.pressure_level
            )
            follow_up_question = self._clean_generated_question(follow_up_question)
            follow_up_question = self._simplify_question_if_compound(follow_up_question)

        return AnswerEvaluationResult(
            answer_score=round(answer_score, 2),
            follow_up_needed=follow_up_needed,
            audience_reaction=audience_reaction,
            evaluation_reason=evaluation_reason,
            follow_up_question=follow_up_question
        )

    def _clean_generated_question(self, question: str) -> str:
        """
        생성된 질문 문장 정리.
        - 따옴표 제거
        - 번호 제거
        - 말머리 제거
        - 물음표 보정
        """
        if not question:
            return ""

        question = question.strip()
        question = question.strip('"').strip("'").strip()
        question = question.lstrip("- ").strip()

        question = re.sub(r"^\d+[\.\)]\s*", "", question).strip()

        prefixes = [
            "질문:",
            "청중:",
            "교수:",
            "면접관:",
            "투자자:",
            "발표자에게 질문:",
            "궁금한 점:",
            "제가 궁금한 점은",
        ]

        for prefix in prefixes:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()

        question = question.splitlines()[0].strip()

        if question and not question.endswith("?") and not question.endswith("？"):
            if question.endswith("."):
                question = question[:-1].strip()
            question += "?"

        return question

    def _simplify_question_if_compound(self, question: str) -> str:
        """
        질문이 너무 복합적으로 생성된 경우 첫 번째 질문만 남긴다.
        너무 강하게 자르면 어색해질 수 있으므로 기본적인 연결 표현만 처리한다.
        """
        if not question:
            return ""

        original = re.sub(r"\s+", " ", question.strip())

        compound_markers = [
            " 그리고 ",
            " 또한 ",
            " 또는 ",
            " 동시에 ",
            "뿐만 아니라",
            "뿐 아니라",
            "장점과 단점",
            "장단점",
            "가능성과 한계",
            "기대효과와 한계",
            "차이점과 장점",
            "이유와 과정",
            "방법과 기준",
        ]

        simplified = original

        for marker in compound_markers:
            if marker in simplified:
                simplified = simplified.split(marker)[0].strip()
                break

        cut_markers = [
            "이고,",
            "이며,",
            "하며,",
            "하고,",
            "인지,",
            "이며 동시에",
        ]

        for marker in cut_markers:
            if marker in simplified:
                simplified = simplified.split(marker)[0].strip()
                break

        comma_patterns = [
            ", 왜",
            ", 어떻게",
            ", 무엇",
            ", 어떤",
            ", 어느",
            ", 실제로",
        ]

        for pattern in comma_patterns:
            if pattern in simplified:
                simplified = simplified.split(pattern)[0].strip()
                break

        if len(simplified) < 10:
            simplified = original

        if simplified.endswith(("은", "는", "이", "가", "을", "를", "의", "와", "과", "로", "으로")):
            simplified = original

        if simplified and not simplified.endswith("?"):
            if simplified.endswith("."):
                simplified = simplified[:-1].strip()
            simplified += "?"

        return simplified

    def _select_question_type(
        self,
        audience_type: str,
        presentation_type: str,
        pressure_level: str
    ) -> str:
        """
        질문 유형 결정.
        기본 버전에서는 너무 세분화하지 않고 간단하게만 분기한다.
        """
        if pressure_level == "high":
            return "natural_challenge"

        if audience_type == "investor":
            return "use_case"

        if audience_type == "professor":
            return "reason_probe"

        if presentation_type == "job_interview":
            return "experience_probe"

        return "clarification"

    def _select_question_difficulty(self, pressure_level: str) -> str:
        """
        압박 강도에 따른 질문 난이도 결정.
        """
        if pressure_level == "low":
            return "easy"

        if pressure_level == "high":
            return "hard"

        return "medium"

    def _build_question_text(
        self,
        current_topic: str | None,
        recent_context: List[str],
        audience_type: str,
        presentation_type: str,
        pressure_level: str,
        previous_questions: List[str],
        question_type: str
    ) -> str:
        """
        룰 기반 질문 문장 생성.
        OpenAI가 실패했을 때 최소한 자연스러운 질문을 반환한다.
        """
        topic = current_topic or "방금 설명한 내용"

        latest_context = recent_context[-1] if recent_context else topic
        latest_context = latest_context.strip()

        short_context = self._make_short_context(latest_context, topic)

        if question_type == "experience_probe":
            candidate = f"그러면 이 부분은 실제 경험에서는 어떻게 적용해 보셨나요?"

        elif question_type == "reason_probe":
            candidate = f"이 부분에서 그렇게 판단한 이유를 조금 더 설명해 주실 수 있나요?"

        elif question_type == "use_case":
            candidate = f"그러면 이 내용이 실제 사용자에게 가장 도움이 되는 상황은 언제인가요?"

        elif question_type == "natural_challenge":
            candidate = f"혹시 그 부분을 뒷받침할 만한 근거가 하나 더 있을까요?"

        else:
            candidate = f"방금 말씀하신 {short_context} 부분을 조금 더 설명해 주실 수 있나요?"

        if candidate in previous_questions:
            candidate = f"그 부분이 실제로는 어떻게 이어지는지 조금 더 설명해 주실 수 있나요?"

        return candidate

    def _make_short_context(self, latest_context: str, fallback: str) -> str:
        """
        최근 발표 문맥을 질문에 넣기 좋게 짧게 자른다.
        너무 긴 문장을 그대로 질문에 넣으면 부자연스러워지므로 20자 내외로 줄인다.
        """
        if not latest_context:
            return fallback

        cleaned = re.sub(r"\s+", " ", latest_context).strip()
        cleaned = cleaned.replace("\n", " ")

        if len(cleaned) > 24:
            cleaned = cleaned[:24].strip() + "..."

        return f"'{cleaned}'"

    def _calculate_answer_score(
        self,
        question_text: str,
        user_answer: str,
        current_topic: str | None,
        recent_context: List[str]
    ) -> float:
        """
        단순 룰 기반 답변 점수 계산.

        기준:
        - 답변 길이
        - 현재 주제 포함 여부
        - 최근 맥락과 관련 단어 포함 여부
        - 이유나 예시 표현 포함 여부
        """
        score = 0.0
        answer = user_answer.strip()

        if len(answer) >= 10:
            score += 20

        if len(answer) >= 30:
            score += 20

        if len(answer) >= 60:
            score += 15

        if current_topic and current_topic in answer:
            score += 20

        matched_context_terms = 0

        for ctx in recent_context[-2:]:
            for token in ctx.split():
                token = token.strip(".,!?()[]\"'")
                if len(token) >= 2 and token in answer:
                    matched_context_terms += 1

        score += min(matched_context_terms * 3, 20)

        if any(word in answer for word in ["왜냐하면", "따라서", "즉", "예를 들어", "근거", "이유"]):
            score += 10

        return min(score, 100.0)

    def _select_audience_reaction(self, answer_score: float) -> str:
        """
        답변 점수 기반 청중 반응 결정.
        """
        if answer_score >= 85:
            return "impressed"

        if answer_score >= 65:
            return "satisfied"

        if answer_score >= 40:
            return "neutral"

        return "confused"

    def _build_evaluation_reason(self, answer_score: float, user_answer: str) -> str:
        """
        답변 평가 이유 생성.
        """
        if answer_score >= 85:
            return "답변이 구체적이고 논리적이며 질문의 핵심에 잘 답하고 있습니다."

        if answer_score >= 65:
            return "답변이 대체로 적절하지만 조금 더 구체적인 근거나 예시가 있으면 좋습니다."

        if answer_score >= 40:
            return "답변은 일부 관련성이 있지만 질문에 대한 핵심 설명이 충분하지 않습니다."

        return "답변이 짧거나 질문과의 연결이 부족하여 추가 설명이 필요합니다."

    def _build_follow_up_question(
        self,
        question_text: str,
        current_topic: str | None,
        user_answer: str,
        pressure_level: str
    ) -> str:
        """
        답변이 부족할 경우 후속 질문 생성.
        """
        topic = current_topic or "해당 내용"

        if pressure_level == "high":
            return f"그 부분에 대한 가장 중요한 근거를 하나만 더 말씀해 주실 수 있나요?"

        if len(user_answer.strip()) < 20:
            return f"조금 더 구체적인 예시를 하나 들어 주실 수 있나요?"

        return f"그 내용이 왜 중요한지 한 가지로 정리해 주실 수 있나요?"