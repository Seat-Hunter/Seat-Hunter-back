# 발표 상황에 맞는 질문 생성, 추가 질문 생성, 사용자 답변 평가를 담당하는 Question Engine 서비스
# 이 서비스는 발표 유형, 청중 유형, 압박 강도, 최근 발표 맥락을 반영하여
# 면접관형 질문을 만들고, 답변 품질을 평가하며, 후속 질문 필요 여부를 판단한다.

import asyncio
import json
from typing import List

from google import genai

from app.core.config import settings
from app.schemas.question import (
    QuestionGenerationInput,
    QuestionGenerationResult,
    AnswerEvaluationInput,
    AnswerEvaluationResult,
)

try:
    _gemini_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
except Exception as _e:
    print(f"[QuestionService Gemini 초기화 실패] {_e}")
    _gemini_client = None


class QuestionService:
    """
    Question Engine 서비스

    주요 기능
    - 발표 유형 / 청중 유형 / 압박 강도 기반 질문 생성
    - 이전 질문과의 중복 회피
    - 사용자 답변 평가
    - 후속 질문 생성
    """

    async def analyze_presentation_style(self, context: str) -> str:
        """발표 맥락을 분석해 어투·수준 라벨을 반환. 실패 시 'general'."""
        if _gemini_client is None:
            return "general"

        prompt = (
            f"발표: \"{context[:300]}\"\n"
            "발표 어투·수준을 academic / professional / casual 중 하나로만 답해."
        )
        try:
            result = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
            )
            style = result.text.strip().lower().split()[0]
            return style if style in ("academic", "professional", "casual") else "general"
        except Exception as e:
            print(f"[Gemini 스타일 분석 실패] {e}")
            return "general"

    async def generate_question_ai(
        self, data: QuestionGenerationInput, presentation_style: str = "general"
    ) -> QuestionGenerationResult:
        """Gemini로 맥락 기반 질문 생성. 실패 시 룰 기반 폴백."""
        if _gemini_client is None:
            return self.generate_question(data)

        context = " ".join(data.recent_context[-5:]) if data.recent_context else "발표 시작"
        prev_qs = "\n".join(f"- {q}" for q in data.previous_questions[-3:]) or "없음"

        pressure_guide = {
            "low":    "자연스러운 청중 호기심 질문",
            "medium": "발표에서 빠진 근거나 구체적 수치를 요구하는 질문",
            "high":   "논리 빈틈이나 근거 없는 가정을 직접 지적하는 압박 질문",
        }.get(data.pressure_level, "발표 내용을 파고드는 질문")

        prompt = (
            f"발표 맥락: \"{context}\" [스타일: {presentation_style}]\n"
            f"청중: {data.audience_type}, 압박: {data.pressure_level}\n"
            f"이전 질문: {prev_qs}\n\n"
            f"{pressure_guide}을 1개 만들어.\n"
            "조건: 50자 내외 구어체 한 문장. "
            "마크다운·별표·따옴표 사용 금지. "
            "'설명해주세요' 단순 요청 금지. "
            "이전 질문과 겹치지 않게. 질문 문장만 출력."
        )

        try:
            result = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
            )
            question_text = result.text.strip().splitlines()[0]
            return QuestionGenerationResult(
                question_text=question_text,
                question_difficulty=self._select_question_difficulty(data.pressure_level),
                question_type="ai_generated",
            )
        except Exception as e:
            print(f"[Gemini 질문 생성 실패] {e} — 룰 기반 폴백")
            return self.generate_question(data)

    async def evaluate_answer_ai(self, data: AnswerEvaluationInput) -> AnswerEvaluationResult:
        """Gemini로 답변 평가 및 꼬리질문 생성. 실패 시 룰 기반 폴백."""
        if _gemini_client is None:
            return self.evaluate_answer(data)

        prompt = (
            f"질문: {data.question_text}\n"
            f"사용자 답변: {data.user_answer}\n\n"
            "답변 품질을 평가하세요. JSON만 응답 (설명 없이):\n"
            "{\"score\": 70, \"sufficient\": true, \"follow_up\": null}\n"
            "또는 답변이 부족하면:\n"
            "{\"score\": 35, \"sufficient\": false, \"follow_up\": \"꼬리질문 한 문장\"}\n\n"
            "기준: score 60 이상이면 sufficient=true, 미만이면 false"
        )

        try:
            result = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = result.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].lstrip("json").strip()
            parsed = json.loads(text)
            score = float(parsed.get("score", 50))
            return AnswerEvaluationResult(
                answer_score=round(score, 2),
                follow_up_needed=not parsed.get("sufficient", True),
                audience_reaction=self._select_audience_reaction(score),
                evaluation_reason="AI 평가 완료",
                follow_up_question=parsed.get("follow_up"),
            )
        except Exception as e:
            print(f"[Gemini 답변 평가 실패] {e} — 룰 기반 폴백")
            return self.evaluate_answer(data)

    def generate_question(
        self,
        data: QuestionGenerationInput
    ) -> QuestionGenerationResult:
        """
        현재 맥락에 맞는 질문을 생성한다.
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
        사용자 답변을 평가하고, 필요하면 후속 질문을 만든다.
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

        return AnswerEvaluationResult(
            answer_score=round(answer_score, 2),
            follow_up_needed=follow_up_needed,
            audience_reaction=audience_reaction,
            evaluation_reason=evaluation_reason,
            follow_up_question=follow_up_question
        )

    def _select_question_type(
        self,
        audience_type: str,
        presentation_type: str,
        pressure_level: str
    ) -> str:
        """
        질문 유형 결정
        """
        if pressure_level == "high":
            return "challenge"

        if audience_type == "investor":
            return "business_probe"

        if audience_type == "professor":
            return "logic_probe"

        if presentation_type == "job_interview":
            return "clarification"

        return "detail_probe"

    def _select_question_difficulty(self, pressure_level: str) -> str:
        """
        압박 강도에 따른 질문 난이도 결정
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
        질문 문장 생성
        """
        topic = current_topic or "방금 설명한 내용"

        # 최근 문맥에서 마지막 발화를 우선 참고
        latest_context = recent_context[-1] if recent_context else topic

        # 청중별 말투
        tone_prefix = self._get_audience_tone_prefix(audience_type, pressure_level)

        # 질문 유형별 기본 템플릿
        if question_type == "clarification":
            candidate = f"{tone_prefix}방금 말씀하신 '{topic}' 부분을 조금 더 구체적으로 설명해 주시겠어요?"
        elif question_type == "logic_probe":
            candidate = f"{tone_prefix}'{topic}'에 대한 설명이 어떤 논리로 이어지는지 한 단계씩 설명해 주세요."
        elif question_type == "business_probe":
            candidate = f"{tone_prefix}'{topic}'이 실제 사용자나 시장에 어떤 가치를 주는지 설명해 주세요."
        elif question_type == "challenge":
            candidate = f"{tone_prefix}지금 설명에는 근거가 부족해 보입니다. '{topic}' 주장이 왜 타당한지 명확히 답변해 주세요."
        else:
            candidate = f"{tone_prefix}방금 말씀하신 내용 중 핵심 포인트를 다시 한 번 정리해 주시겠어요?"

        # 이전 질문과 동일하면 살짝 변형
        if candidate in previous_questions:
            candidate = f"{tone_prefix}방금 설명하신 '{latest_context}'와 '{topic}'의 연결을 조금 더 명확히 말씀해 주세요."

        return candidate

    def _get_audience_tone_prefix(self, audience_type: str, pressure_level: str) -> str:
        """
        청중 유형과 압박 강도에 맞는 질문 톤 결정
        """
        if audience_type == "interviewer":
            if pressure_level == "high":
                return "면접관: "
            return "면접관: "

        if audience_type == "professor":
            if pressure_level == "high":
                return "교수: "
            return "교수: "

        if audience_type == "investor":
            if pressure_level == "high":
                return "투자자: "
            return "투자자: "

        return "청중: "

    def _calculate_answer_score(
        self,
        question_text: str,
        user_answer: str,
        current_topic: str | None,
        recent_context: List[str]
    ) -> float:
        """
        단순 룰 기반 답변 점수 계산

        기준 예시
        - 답변 길이
        - 현재 주제 포함 여부
        - 최근 맥락과 관련 단어 포함 여부
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
        답변 점수 기반 청중 반응 결정
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
        답변 평가 이유 생성
        """
        if answer_score >= 85:
            return "답변이 구체적이고 논리적이며 핵심 포인트를 잘 포함하고 있습니다."

        if answer_score >= 65:
            return "답변이 대체로 적절하지만 조금 더 구체적인 근거나 예시가 있으면 좋습니다."

        if answer_score >= 40:
            return "답변은 일부 관련성이 있지만 핵심 설명이 충분하지 않습니다."

        return "답변이 짧거나 주제와의 연결이 부족하여 추가 설명이 필요합니다."

    def _build_follow_up_question(
        self,
        question_text: str,
        current_topic: str | None,
        user_answer: str,
        pressure_level: str
    ) -> str:
        """
        답변이 부족할 경우 후속 질문 생성
        """
        topic = current_topic or "해당 내용"

        if pressure_level == "high":
            return f"'{topic}'의 핵심 근거를 한 문장으로 명확히 말씀해 주세요."

        if len(user_answer.strip()) < 20:
            return f"'{topic}'에 대해 예시를 들어 조금 더 자세히 설명해 주세요."

        return f"좋습니다. 그렇다면 '{topic}'이 실제로 왜 중요한지 조금 더 구체적으로 설명해 주세요."