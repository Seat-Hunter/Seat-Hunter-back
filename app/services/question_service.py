# app/services/question_service.py

# 발표 상황에 맞는 질문 생성, 추가 질문 생성,
# 사용자 답변 평가를 담당하는 Question Engine 서비스
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
from app.services.prompt_scenarios import (
    build_scenario_block,
    PRESSURE_LEVEL_EVAL_SCENARIOS,
)


try:
    _openai_client = (
        OpenAI(api_key=settings.openai_api_key)
        if settings.openai_api_key
        else None
    )
except Exception as _e:
    print(
        f"[QuestionService OpenAI 초기화 실패] {_e}"
    )
    _openai_client = None


class QuestionService:
    """
    Question Engine 서비스

    주요 기능
    - 발표 맥락 기반 질문 생성
    - 사용자 답변 평가
    - 필요 시 후속 질문 생성

    OpenAI API 연결 실패 또는 API Key 미설정 시
    룰 기반 로직으로 폴백한다.
    """

    async def analyze_presentation_style(
        self,
        context: str,
    ) -> str:
        """
        현재 버전에서는 발표 스타일 분석을 복잡하게 하지 않는다.
        기존 호출부와의 호환성을 위해 함수는 유지하되
        항상 general을 반환한다.
        """
        return "general"

    async def generate_question_ai(
        self,
        data: QuestionGenerationInput,
        presentation_style: str = "general",
    ) -> QuestionGenerationResult:
        """
        OpenAI로 최근 발표 맥락 기반 질문 생성.

        방향:
        - 실제 청중처럼 자연스럽게 질문
        - 발표 중간에 끼어들 수 있는 짧은 질문
        - 질문은 1개만 생성
        - 너무 길거나 복합적인 질문은 피함
        - 발표자가 뒤에서 설명할 수 있는 내용은
          단정적으로 공격하지 않음
        - 사용자 답변 평가 후 답변이 부족하면
          꼬리질문 생성
        - 꼬리질문은 최대 2번까지 생성 가능
        - 꼬리질문은 사용자의 답변을 바탕으로
          자연스럽게 이어지도록 생성
        - 모든 질문은 존댓말로 작성
        """
        if _openai_client is None:
            return self.generate_question(data)

        context = (
            " ".join(data.recent_context[-4:])
            if data.recent_context
            else "발표 내용 없음"
        )

        previous_questions = "\n".join(
            f"- {question}"
            for question in data.previous_questions[-3:]
        ) or "없음"

        prompt = f"""
너는 발표를 실시간으로 듣고 있는 실제 청중이다.

목표:
지금까지 실제로 들은 발표 내용에서 가장 자연스럽고 유익한 궁금증 하나를 골라,
발표 중간에 말로 건넬 수 있는 질문 한 문장으로 만든다.

좋은 질문은 단순히 어려운 질문이 아니라,
현재 발표 내용을 더 잘 이해하거나 중요한 지점을 확인하는 데 도움이 되는 질문이다.

질문을 만드는 과정:
1. 최근 발표 흐름에서 질문의 근거가 되는 구체적인 표현, 주장, 결과,
   방법, 사례 또는 연결 지점을 찾는다.
2. 그중 현재 청중의 이해에 가장 도움이 되는 궁금증 하나를 선택한다.
3. 발표자가 실제로 말하지 않은 내용을 임의로 가정하지 않는다.
4. 발표자가 바로 뒤에서 설명할 가능성이 높은 내용은
   이미 빠진 정보라고 단정하지 않는다.
5. 이전 질문과 핵심 요구가 겹치는지 확인한다.
6. 선택한 궁금증을 실제 사람이 말할 만한 자연스러운 질문으로 표현한다.

상황별 지침 적용 방법:
- 상황별 지침은 질문의 관점, 깊이, 어조를 조정하는 가이드다.
- 상황별 지침의 모든 요소를 하나의 질문에 억지로 포함하지 않는다.
- 교수 청중이라고 항상 한계점을 묻거나,
  투자자 청중이라고 항상 시장 규모를 묻지는 않는다.
- 현재 발표 내용과 가장 자연스럽게 연결되는 관점 하나만 선택한다.
- 압박 강도는 질문의 깊이와 직접성에 반영한다.
- 압박 강도가 높더라도 공격적인 표현, 억지 반박,
  근거 없는 의심이나 트집 잡는 질문은 만들지 않는다.

질문 선택 기준:
- 이미 충분히 설명된 내용은 다시 묻지 않는다.
- 너무 넓어서 어떤 답을 해야 할지 모호한 질문은 피한다.
- 발표 내용의 핵심 이해와 관계없는 사소한 질문은 피한다.
- 구체적으로 물을 수 있다면
  "조금 더 설명해 주세요" 같은 포괄적인 질문보다
  무엇이 궁금한지를 직접 묻는다.
- 단순히 질문을 생성하기 위해 의미 없는 빈틈을 만들지 않는다.
- 여러 궁금증이 있더라도 가장 가치 있는 질문 하나만 선택한다.
- 이전 질문을 단어만 바꿔 반복하지 않는다.

말투:
- 실제 발표 현장의 청중처럼 자연스럽게 작성한다.
- 한국어 존댓말을 사용한다.
- 정중하지만 지나치게 격식적이거나 기계적으로 표현하지 않는다.
- 발표자를 공격하거나 잘못을 단정하는 표현은 피한다.
- 발표자가 뒤에서 설명할 수도 있는 내용은
  "혹시", "이 부분은", "말씀하신 내용에서"처럼 자연스럽게 묻는다.
- 지나치게 완성된 논문 심사 문장처럼 만들지 않는다.

출력 규칙:
- 질문 한 문장만 출력한다.
- 하나의 핵심 궁금증만 묻는다.
- 여러 질문을 쉼표나 접속사로 결합하지 않는다.
- 질문과 근거 요구를 한꺼번에 여러 개 묻지 않는다.
- 발표 내용에 없는 사실을 전제로 삼지 않는다.
- 말머리, 번호, 역할명, 해설을 출력하지 않는다.
- 따옴표로 감싸지 않는다.
- 질문 이외의 설명을 출력하지 않는다.

[현재 발표 주제]
{data.current_topic or "알 수 없음"}

[세션 설정]
- 발표 유형: {data.presentation_type}
- 청중 유형: {data.audience_type}
- 청중 인원: {f"{data.audience_count}명" if data.audience_count else "알 수 없음"}
- 압박 강도: {data.pressure_level}

[상황별 지침]
{build_scenario_block(
    data.presentation_type,
    data.audience_type,
    data.pressure_level,
    data.audience_count,
)}

[이전 질문]
{previous_questions}

[지금까지 들은 발표 내용]
{context}

위 발표 내용에서 실제로 근거를 찾을 수 있는,
가장 자연스럽고 유익한 질문 한 문장만 출력해라.
""".strip()

        try:
            result = await asyncio.to_thread(
                _openai_client.responses.create,
                model=settings.openai_question_model,
                input=prompt,
            )

            question_text = (
                result.output_text
                .strip()
                .splitlines()[0]
            )
            question_text = self._clean_generated_question(
                question_text
            )

            if not question_text:
                return self.generate_question(data)

            return QuestionGenerationResult(
                question_text=question_text,
                question_difficulty=(
                    self._select_question_difficulty(
                        data.pressure_level
                    )
                ),
                question_type="ai_generated",
            )

        except Exception as e:
            print(
                f"[OpenAI 질문 생성 실패] {e} "
                "— 룰 기반 폴백"
            )
            return self.generate_question(data)

    async def evaluate_answer_ai(
        self,
        data: AnswerEvaluationInput,
    ) -> AnswerEvaluationResult:
        """
        OpenAI로 사용자 답변 평가 및
        필요 시 꼬리질문 생성.
        """
        if _openai_client is None:
            return self.evaluate_answer(data)

        recent_context = (
            " ".join(data.recent_context[-2:])
            if data.recent_context
            else "없음"
        )

        follow_up_count = getattr(
            data,
            "follow_up_count",
            0,
        )
        max_follow_ups = getattr(
            data,
            "max_follow_ups",
            2,
        )

        try:
            follow_up_count = int(follow_up_count)
        except Exception:
            follow_up_count = 0

        try:
            max_follow_ups = int(max_follow_ups)
        except Exception:
            max_follow_ups = 2

        can_generate_follow_up = (
            follow_up_count < max_follow_ups
        )

        qa_history = (
            getattr(data, "qa_history", None)
            or []
        )

        if qa_history:
            history_text = "\n".join(
                (
                    f"{index + 1}) "
                    f"Q: {item.get('question', '')}\n"
                    f"   A: {item.get('answer', '')}"
                )
                for index, item in enumerate(qa_history)
            )
        else:
            history_text = (
                "없음 "
                "(이번이 이 질문 흐름의 첫 평가)"
            )

        pressure_eval_scenario = (
            PRESSURE_LEVEL_EVAL_SCENARIOS.get(
                data.pressure_level,
                PRESSURE_LEVEL_EVAL_SCENARIOS[
                    "medium"
                ],
            )
        )

        prompt = f"""
너는 실시간 발표 Q&A에서 발표자의 답변을 평가하는 청중 평가자다.

목표:
완벽한 모범답안을 요구하는 것이 아니라,
이번 질문의 핵심에 대해 현재 Q&A를 자연스럽게 마쳐도 될 만큼
답변했는지를 판단한다.

꼬리질문은 단순히 더 자세한 답변을 얻기 위해 만드는 것이 아니다.
답변에서 확인 가능한 중요한 빈틈이 하나 남아 있고,
그 빈틈을 묻는 것이 실제로 발표 이해에 도움이 될 때만 만든다.

[이 질문 흐름에서 지금까지 나온 질문/답변]
{history_text}

[이번 질문]
{data.question_text}

[이번 사용자 답변]
{data.user_answer}

[현재 발표 주제]
{data.current_topic or "알 수 없음"}

[최근 발표 맥락]
{recent_context}

[꼬리질문 상태]
- 현재 꼬리질문 횟수: {follow_up_count}
- 최대 꼬리질문 횟수: {max_follow_ups}
- 꼬리질문 생성 가능 여부: {can_generate_follow_up}

[압박 강도에 따른 판단 가이드]
- {pressure_eval_scenario}

[평가 방법]
아래 순서대로 판단한다.

1. 이번 질문이 실제로 요구한 핵심이 무엇인지 파악한다.
2. 이번 답변과 이전 Q&A를 함께 살펴본다.
3. 질문의 핵심에 직접 응답했는지 판단한다.
4. 답변의 의미가 청중에게 이해될 만큼 전달됐는지 판단한다.
5. 질문을 이해하는 데 꼭 필요한 이유, 근거, 예시 또는 조건이
   실질적으로 빠져 있는지 살펴본다.
6. 부족한 부분이 있더라도 이미 비슷한 내용을 물었다면
   같은 요구를 반복하지 않는다.
7. 꼬리질문이 필요하다면 가장 중요한 빈틈 하나만 선택한다.

[가장 먼저 적용할 종료 조건]
다음 조건 중 하나에 해당하면 sufficient=true, follow_up=null로 처리한다.

- 사용자가 "모르겠다", "잘 모르겠습니다", "모름",
  "생각해 본 적이 없습니다", "필요 없습니다", "됐습니다",
  "없습니다" 등으로 더 답할 의사가 없음을 분명히 나타낸 경우
- 꼬리질문 생성 가능 여부가 false인 경우
- 질문의 핵심에 이미 답했고 전체적인 의미가 충분히 전달된 경우
- 부족한 세부 정보가 있더라도 Q&A를 더 이어갈 정도로 중요하지 않은 경우
- 이전 질문이나 답변에서 해당 요구가 이미 충분히 다뤄진 경우
- 자연스럽고 유익한 꼬리질문을 만들 수 없는 경우

사용자가 답변을 회피하거나 더 답할 의사가 없다고 표현한 경우:
- 왜 모르는지 다시 묻지 않는다.
- 어떤 정보가 있어야 답할 수 있는지 묻지 않는다.
- 답변을 강제로 유도하지 않는다.
- Q&A를 종료한다.

[명확화 요청 처리]
사용자의 답변이 이번 질문에 대한 실제 답변이 아니라,
다음과 같이 질문의 의미를 다시 확인하는 경우가 있다.

예:
- "어떤 부분을 말씀하시는 건가요?"
- "구체적으로 어떤 의미인가요?"
- "그게 어떤 상황을 말하는 건가요?"

이 경우:
- sufficient=false로 판단할 수 있다.
- 새로운 주제로 넘어가지 않는다.
- 선택지를 여러 개 나열하지 않는다.
- 최근 발표 맥락에 실제로 나온 표현이나 사례 하나를 짚는다.
- 원래 질문의 핵심을 유지한 채 더 쉬운 말로 다시 묻는다.
- 사용자를 평가하거나 명확화 요청 자체를 문제 삼지 않는다.

[sufficient 판단 기준]
- sufficient는 score와 독립적으로 판단한다.
- 점수가 낮다는 이유만으로 sufficient=false로 판단하지 않는다.
- 질문의 핵심 요구에 직접 응답했고 의미가 전달됐다면 true다.
- 답변이 짧더라도 핵심이 분명하다면 true로 판단할 수 있다.
- 답변이 길더라도 핵심을 비켜 갔다면 false로 판단할 수 있다.
- 질문과 일부 관련은 있지만 핵심 요구에 응답하지 않았다면 false를 고려한다.
- 답변을 이해하기 위해 꼭 필요한 정보가 실질적으로 빠진 경우 false를 고려한다.
- 압박 강도가 높다는 이유만으로 자동으로 false 처리하지 않는다.
- 단순히 더 좋은 답변을 받을 수 있다는 이유로 false 처리하지 않는다.
- 이전 Q&A에서 이미 충족된 요구를 표현만 바꿔 다시 요구하지 않는다.

[score 판단 기준]
score는 0부터 100까지의 참고 점수다.

다음을 종합해 판단한다.
- 질문에 얼마나 직접적으로 답했는가
- 답변의 의미가 얼마나 명확한가
- 발표 맥락과 자연스럽게 연결되는가
- 필요한 경우 이유, 근거, 예시 또는 조건이 제시됐는가
- 청중이 답변을 듣고 질문의 핵심을 이해할 수 있는가

주의:
- 답변이 짧다는 이유만으로 낮은 점수를 주지 않는다.
- 답변이 길다는 이유만으로 높은 점수를 주지 않는다.
- 전문 용어를 많이 사용했다는 이유만으로 높은 점수를 주지 않는다.
- 완벽한 답변이 아니더라도 핵심에 답했다면 적절한 점수를 줄 수 있다.

[꼬리질문 생성 조건]
다음 조건을 모두 만족할 때만 sufficient=false로 판단하고
follow_up을 생성한다.

- 원래 질문의 핵심과 직접 관련된 중요한 정보가 빠져 있다.
- 그 부족함을 사용자의 실제 답변에서 확인할 수 있다.
- 이전 질문과 같은 요구를 반복하지 않는다.
- 추가 질문이 발표 내용을 이해하는 데 실질적으로 도움이 된다.
- 한 문장으로 자연스럽게 물을 수 있다.
- 꼬리질문 생성 가능 여부가 true다.

[follow_up 작성 규칙]
- sufficient=false일 때만 작성한다.
- 한 문장으로 작성한다.
- 한국어 존댓말을 사용한다.
- 새로운 주제를 꺼내지 않는다.
- 답변에서 실제로 부족한 핵심 한 가지만 묻는다.
- 가능하면 사용자의 답변에 나온 구체적인 표현과 연결한다.
- 발표 맥락에 없는 내용을 임의로 전제하지 않는다.
- 이미 했던 질문을 표현만 바꿔 반복하지 않는다.
- 여러 개의 질문을 한 문장에 결합하지 않는다.
- 양자택일과 근거 요구를 동시에 묻지 않는다.
- 과도하게 세부적인 심문형 질문은 피한다.
- 단순히 "조금 더 자세히 설명해 주세요"라고만 묻기보다,
  어떤 부분이 필요한지를 자연스럽게 드러낸다.
- 답변이 충분하다면 억지로 꼬리질문을 만들지 않는다.

[출력 형식]
반드시 아래 필드를 모두 포함한 JSON object만 출력한다.

{{
  "score": 0부터 100 사이 숫자,
  "sufficient": true 또는 false,
  "follow_up": "꼬리질문 한 문장" 또는 null
}}

[출력 규칙]
- JSON object만 출력한다.
- 코드 블록을 사용하지 않는다.
- JSON 앞뒤에 설명을 붙이지 않는다.
- 모든 필드를 반드시 포함한다.
- sufficient=true이면 follow_up은 반드시 null이다.
- sufficient=false이면 follow_up은 자연스러운 질문 한 문장이어야 한다.
""".strip()

        try:
            result = await asyncio.to_thread(
                _openai_client.responses.create,
                model=settings.openai_question_model,
                input=prompt,
            )

            text = result.output_text.strip()

            if text.startswith("```"):
                text = (
                    text
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )

            parsed = json.loads(text)

            score = float(
                parsed.get("score", 50)
            )
            score = max(
                0.0,
                min(score, 100.0),
            )

            sufficient = bool(
                parsed.get(
                    "sufficient",
                    score >= 70,
                )
            )
            follow_up = parsed.get("follow_up")

            follow_up_needed = (
                not sufficient
                and follow_up_count < max_follow_ups
            )

            if not follow_up_needed:
                follow_up = None

            if follow_up:
                follow_up = self._clean_generated_question(
                    str(follow_up)
                )

            return AnswerEvaluationResult(
                answer_score=round(score, 2),
                follow_up_needed=follow_up_needed,
                audience_reaction=(
                    self._select_audience_reaction(
                        score
                    )
                ),
                evaluation_reason="AI 평가 완료",
                follow_up_question=follow_up,
            )

        except Exception as e:
            print(
                f"[OpenAI 답변 평가 실패] {e} "
                "— 룰 기반 폴백"
            )
            return self.evaluate_answer(data)

    def generate_question(
        self,
        data: QuestionGenerationInput,
    ) -> QuestionGenerationResult:
        """
        OpenAI 호출 실패 시 사용하는 룰 기반 질문 생성.
        """
        question_type = self._select_question_type(
            audience_type=data.audience_type,
            presentation_type=data.presentation_type,
            pressure_level=data.pressure_level,
        )

        question_difficulty = (
            self._select_question_difficulty(
                pressure_level=data.pressure_level,
            )
        )

        question_text = self._build_question_text(
            current_topic=data.current_topic,
            recent_context=data.recent_context,
            audience_type=data.audience_type,
            presentation_type=data.presentation_type,
            pressure_level=data.pressure_level,
            previous_questions=data.previous_questions,
            question_type=question_type,
        )

        question_text = self._clean_generated_question(
            question_text
        )

        return QuestionGenerationResult(
            question_text=question_text,
            question_difficulty=question_difficulty,
            question_type=question_type,
        )

    def evaluate_answer(
        self,
        data: AnswerEvaluationInput,
    ) -> AnswerEvaluationResult:
        """
        OpenAI 호출 실패 시 사용하는 룰 기반 답변 평가.
        """
        answer_score = self._calculate_answer_score(
            question_text=data.question_text,
            user_answer=data.user_answer,
            current_topic=data.current_topic,
            recent_context=data.recent_context,
        )

        follow_up_needed = answer_score < 60
        audience_reaction = (
            self._select_audience_reaction(
                answer_score
            )
        )

        evaluation_reason = (
            self._build_evaluation_reason(
                answer_score=answer_score,
                user_answer=data.user_answer,
            )
        )

        follow_up_question = None

        if follow_up_needed:
            follow_up_question = (
                self._build_follow_up_question(
                    question_text=data.question_text,
                    current_topic=data.current_topic,
                    user_answer=data.user_answer,
                    pressure_level=data.pressure_level,
                )
            )
            follow_up_question = (
                self._clean_generated_question(
                    follow_up_question
                )
            )

        return AnswerEvaluationResult(
            answer_score=round(answer_score, 2),
            follow_up_needed=follow_up_needed,
            audience_reaction=audience_reaction,
            evaluation_reason=evaluation_reason,
            follow_up_question=follow_up_question,
        )

    def _clean_generated_question(
        self,
        question: str,
    ) -> str:
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
        question = (
            question
            .strip('"')
            .strip("'")
            .strip()
        )
        question = question.lstrip("- ").strip()

        question = re.sub(
            r"^\d+[\.\)]\s*",
            "",
            question,
        ).strip()

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
                question = question[
                    len(prefix):
                ].strip()

        question = (
            question
            .splitlines()[0]
            .strip()
        )

        if (
            question
            and not question.endswith("?")
            and not question.endswith("？")
        ):
            if question.endswith("."):
                question = question[:-1].strip()

            question += "?"

        return question

    def _select_question_type(
        self,
        audience_type: str,
        presentation_type: str,
        pressure_level: str,
    ) -> str:
        """
        질문 유형 결정.

        기본 버전에서는 너무 세분화하지 않고
        간단하게만 분기한다.
        """
        if pressure_level == "high":
            return "natural_challenge"

        if audience_type == "investor":
            return "use_case"

        if audience_type == "professor":
            return "reason_probe"

        return "clarification"

    def _select_question_difficulty(
        self,
        pressure_level: str,
    ) -> str:
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
        question_type: str,
    ) -> str:
        """
        룰 기반 질문 문장 생성.

        OpenAI가 실패했을 때 최소한
        자연스러운 질문을 반환한다.
        """
        topic = (
            current_topic
            or "방금 설명한 내용"
        )

        latest_context = (
            recent_context[-1]
            if recent_context
            else topic
        )
        latest_context = latest_context.strip()

        short_context = self._make_short_context(
            latest_context,
            topic,
        )

        if question_type == "experience_probe":
            candidate = (
                "그러면 이 부분은 실제 경험에서는 "
                "어떻게 적용해 보셨나요?"
            )

        elif question_type == "reason_probe":
            candidate = (
                "이 부분에서 그렇게 판단한 이유를 "
                "조금 더 설명해 주실 수 있나요?"
            )

        elif question_type == "use_case":
            candidate = (
                "그러면 이 내용이 실제 사용자에게 "
                "가장 도움이 되는 상황은 언제인가요?"
            )

        elif question_type == "natural_challenge":
            candidate = (
                "혹시 그 부분을 뒷받침할 만한 "
                "근거가 하나 더 있을까요?"
            )

        else:
            candidate = (
                f"방금 말씀하신 {short_context} 부분을 "
                "조금 더 설명해 주실 수 있나요?"
            )

        if candidate in previous_questions:
            candidate = (
                "그 부분이 실제로는 어떻게 이어지는지 "
                "조금 더 설명해 주실 수 있나요?"
            )

        return candidate

    def _make_short_context(
        self,
        latest_context: str,
        fallback: str,
    ) -> str:
        """
        최근 발표 문맥을 질문에 넣기 좋게 짧게 자른다.

        너무 긴 문장을 그대로 질문에 넣으면
        부자연스러워지므로 20자 내외로 줄인다.
        """
        if not latest_context:
            return fallback

        cleaned = re.sub(
            r"\s+",
            " ",
            latest_context,
        ).strip()
        cleaned = cleaned.replace("\n", " ")

        if len(cleaned) > 24:
            cleaned = (
                cleaned[:24].strip()
                + "..."
            )

        return f"'{cleaned}'"

    def _calculate_answer_score(
        self,
        question_text: str,
        user_answer: str,
        current_topic: str | None,
        recent_context: List[str],
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

        if (
            current_topic
            and current_topic in answer
        ):
            score += 20

        matched_context_terms = 0

        for context in recent_context[-2:]:
            for token in context.split():
                token = token.strip(
                    ".,!?()[]\"'"
                )

                if (
                    len(token) >= 2
                    and token in answer
                ):
                    matched_context_terms += 1

        score += min(
            matched_context_terms * 3,
            20,
        )

        reason_words = [
            "왜냐하면",
            "따라서",
            "즉",
            "예를 들어",
            "근거",
            "이유",
        ]

        if any(
            word in answer
            for word in reason_words
        ):
            score += 10

        return min(score, 100.0)

    def _select_audience_reaction(
        self,
        answer_score: float,
    ) -> str:
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

    def _build_evaluation_reason(
        self,
        answer_score: float,
        user_answer: str,
    ) -> str:
        """
        답변 평가 이유 생성.
        """
        if answer_score >= 85:
            return (
                "답변이 구체적이고 논리적이며 "
                "질문의 핵심에 잘 답하고 있습니다."
            )

        if answer_score >= 65:
            return (
                "답변이 대체로 적절하지만 조금 더 "
                "구체적인 근거나 예시가 있으면 좋습니다."
            )

        if answer_score >= 40:
            return (
                "답변은 일부 관련성이 있지만 질문에 대한 "
                "핵심 설명이 충분하지 않습니다."
            )

        return (
            "답변이 짧거나 질문과의 연결이 부족하여 "
            "추가 설명이 필요합니다."
        )

    def _build_follow_up_question(
        self,
        question_text: str,
        current_topic: str | None,
        user_answer: str,
        pressure_level: str,
    ) -> str:
        """
        답변이 부족할 경우 후속 질문 생성.
        """
        topic = current_topic or "해당 내용"

        if pressure_level == "high":
            return (
                "그 부분에 대한 가장 중요한 근거를 "
                "하나만 더 말씀해 주실 수 있나요?"
            )

        if len(user_answer.strip()) < 20:
            return (
                "조금 더 구체적인 예시를 "
                "하나 들어 주실 수 있나요?"
            )

        return (
            "그 내용이 왜 중요한지 "
            "한 가지로 정리해 주실 수 있나요?"
        )