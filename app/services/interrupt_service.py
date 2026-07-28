# app/services/interrupt_service.py

"""
LLM 기반 Interrupt Decision Engine

역할
1. 시스템 조건은 rule로 먼저 차단
   - interrupt_enabled=False
   - cooldown_remaining_ms > 0
   - 최근 발화가 너무 짧음
2. 발화 내용, 최근 발표 흐름, 음성 지표를 LLM에 전달
3. LLM이 자연스러운 질문 타이밍인지 JSON으로 판단
"""

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.interrupt import (
    InterruptDecisionInput,
    InterruptDecisionResult,
)


class InterruptService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

        # 인터럽트 판단은 짧은 JSON 분류 작업이므로 가벼운 모델 권장
        # .env 예시:
        # OPENAI_INTERRUPT_MODEL=gpt-5-nano
        self.model = getattr(settings, "openai_interrupt_model", "gpt-5-nano")

        # LLM이 질문 타이밍이라고 해도 신뢰도가 너무 낮으면 차단
        self.min_confidence = 0.55

    async def decide(self, data: InterruptDecisionInput) -> InterruptDecisionResult:
        """
        LLM 기반 인터럽트 판단

        - 여기서의 rule은 LLM 판단으로 넘어가기 전에 한 번 더 안전적으로 판단하는 역할을 한다.
        - 실제 질문 타이밍은 LLM이 발화 흐름을 보고 판단한다.
        """

        # 1. 인터럽트 비활성화면 무조건 차단
        if not data.interrupt_enabled:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="interrupt_enabled가 false이므로 인터럽트를 수행하지 않습니다.",
                interrupt_type=None,
                triggered_by=["disabled"],
                confidence=1.0,
            )

        # 2. 쿨다운 중이면 무조건 차단
        if data.cooldown_remaining_ms > 0:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="쿨다운이 아직 남아 있어 인터럽트를 수행하지 않습니다.",
                interrupt_type=None,
                triggered_by=["cooldown"],
                confidence=1.0,
            )

        latest_utterance = data.context_state.latest_utterance.strip()
        recent_transcript = data.context_state.recent_transcript.strip()

        # 3. 발표 내용이 너무 짧으면 LLM 호출하지 않음
        if len(recent_transcript) < 30 and len(latest_utterance) < 10:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="아직 발표 내용이 충분히 쌓이지 않아 질문 타이밍을 판단하지 않습니다.",
                interrupt_type=None,
                triggered_by=["too_short_context"],
                confidence=1.0,
            )

        try:
            prompt = self._build_prompt(data)

            # 중요:
            # gpt-5 계열 일부 모델은 temperature=0.2 같은 값을 지원하지 않을 수 있다.
            # 따라서 temperature를 보내지 않고 기본값을 사용한다.
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)

            should_interrupt = bool(parsed.get("should_interrupt", False))
            reason = str(parsed.get("reason", "LLM 판단 결과입니다."))
            interrupt_type = parsed.get("interrupt_type")
            triggered_by = self._normalize_triggered_by(parsed.get("triggered_by", []))
            confidence = self._normalize_confidence(parsed.get("confidence", 0.0))

            # should_interrupt가 false면 interrupt_type은 없어도 됨
            if not should_interrupt:
                return InterruptDecisionResult(
                    should_interrupt=False,
                    reason=reason,
                    interrupt_type=None,
                    triggered_by=triggered_by,
                    confidence=confidence,
                )

            # LLM이 true라고 해도 confidence가 낮으면 차단
            if confidence < self.min_confidence:
                return InterruptDecisionResult(
                    should_interrupt=False,
                    reason=f"질문 타이밍일 가능성은 있지만 확신도가 낮아 개입하지 않습니다. 이유: {reason}",
                    interrupt_type=None,
                    triggered_by=["low_confidence"],
                    confidence=confidence,
                )

            # interrupt_type이 비어 있으면 일반 질문으로 보정
            if not interrupt_type:
                interrupt_type = "natural_question"

            return InterruptDecisionResult(
                should_interrupt=True,
                reason=reason,
                interrupt_type=interrupt_type,
                triggered_by=triggered_by,
                confidence=confidence,
            )

        except Exception as e:
            print(f"[LLM 인터럽트 판단 에러] {e}")

            # LLM 실패 시에는 안전하게 인터럽트하지 않음
            return InterruptDecisionResult(
                should_interrupt=False,
                reason=f"LLM 판단 실패로 인터럽트를 수행하지 않습니다: {e}",
                interrupt_type=None,
                triggered_by=["llm_error"],
                confidence=0.0,
            )

    def _system_prompt(self) -> str:
        return """
너는 발표 연습 서비스에서 청중 역할을 하는 인터럽트 판단기다.

역할:
발표자를 공격적으로 평가하는 것이 아니라,
발표를 듣는 청중 입장에서 자연스럽게 질문할 만한 순간인지 판단한다.

판단 방향:
- 발표 흐름을 우선 존중하되, 청중의 이해를 돕는 질문이라면 개입할 수 있다.
- 발표자가 아직 설명을 이어가는 중이라면 대체로 기다린다.
- 핵심 개념, 방법, 이유, 근거, 예시, 차이점, 연결 관계 등을 종합적으로 고려해 설명이 부족하다고 판단되면 질문할 수 있다.
- 이미 나온 질문과 비슷한 내용은 반복하지 않는다.
- WPM, 필러, 침묵 같은 음성 지표는 참고만 하고, 최종 판단은 발표 내용과 흐름을 기준으로 한다.

질문을 고려하기 좋은 경우:
- 방금 나온 내용이 중요하지만 설명이 부족한 경우
- 주장이나 결과에 대한 이유나 근거가 궁금한 경우
- 예시가 있으면 청중이 더 쉽게 이해할 수 있는 경우
- 앞 내용과 방금 내용의 연결이 약한 경우
- 발표자가 잠시 막혀서 자연스럽게 흐름을 이어줄 필요가 있는 경우

질문을 피하는 것이 좋은 경우:
- 인사말, 자기소개, 발표 초반처럼 맥락이 아직 부족한 경우
- 발표자가 한 문장이나 설명을 이어가는 중인 경우
- 단순히 말이 빠르거나 필러가 있다는 것만 문제인 경우
- 최근 질문과 거의 같은 질문이 될 가능성이 큰 경우

출력 규칙:
- 반드시 JSON object만 반환한다.
- 모든 필드는 항상 포함한다.
- reason은 한국어 한 문장으로 짧게 작성한다.
- 빈 JSON object({})를 반환하지 않는다.

형식:
{
  "should_interrupt": true 또는 false,
  "reason": "지금 질문하거나 질문하지 않는 이유 20자 이내로 간단히",
  "interrupt_type": "natural_question | concept_question | reason_question | evidence_question | example_question | connection_question | recovery_question | null",
  "triggered_by": ["curiosity", "concept_needs_detail", "reason_unclear", "evidence_needed", "example_needed", "connection_unclear", "hesitation"],
  "confidence": 0.0부터 1.0 사이 숫자
}
"""

    def _build_prompt(self, data: InterruptDecisionInput) -> str:
        speech = data.speech_metrics
        context = data.context_state

        previous_questions_text = "\n".join(
            [f"- {q}" for q in data.previous_questions[-3:]]
        ) or "없음"

        return f"""
[상황]
발표자가 실시간으로 발표 중이다.
너는 청중처럼 발표를 듣고 있다가, 궁금한 내용을 자연스러운 타이밍에 질문을 하려고 한다.

[발표 유형]
{data.presentation_type}

[청중 유형]
{data.audience_type}

[청중 인원]
{f"{data.audience_count}명" if data.audience_count else "알 수 없음"}

[압박 수준]
{data.pressure_level}

[방금 들은 발화]
{context.latest_utterance}

[최근 발표 흐름]
{context.recent_transcript}

[현재 주제]
{context.current_topic or "알 수 없음"}

[슬라이드 맥락]
{context.slide_context or "없음"}

[대본 맥락]
{context.script_context or "없음"}

[최근 이미 나온 질문]
{previous_questions_text}

[보조 음성 지표]
- recent_wpm: {speech.recent_wpm}
- average_wpm: {speech.average_wpm}
- filler_count: {speech.filler_count}
- silence_duration_ms: {speech.silence_duration}
- hesitation_score: {speech.hesitation_score}
- stress_score: {speech.stress_score}

[판단]
위 정보를 바탕으로 지금 청중 질문이 자연스러운 타이밍인지 판단해라.

판단할 때 고려할 것:
- 발표 흐름을 끊는 질문인지, 이해를 돕는 질문인지
- 방금 나온 내용에서 청중이 궁금해할 만한 구체적인 지점이 있는지
- 아직 조금 더 설명을 기다리는 편이 자연스러운지
- 최근 질문과 중복되지 않는지

JSON object만 반환해라.
"""

    def _normalize_triggered_by(self, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [str(item) for item in value]

        return [str(value)]

    def _normalize_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except Exception:
            confidence = 0.0

        return max(0.0, min(confidence, 1.0))