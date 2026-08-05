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
from app.services.prompt_scenarios import build_scenario_block


class InterruptService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

        # 인터럽트 판단은 짧은 JSON 분류 작업이므로 가벼운 모델 권장
        # .env 예시:
        # OPENAI_INTERRUPT_MODEL=gpt-5-nano
        self.model = getattr(
            settings,
            "openai_interrupt_model",
            "gpt-5-nano",
        )

        # LLM이 질문 타이밍이라고 해도 신뢰도가 너무 낮으면 차단
        self.min_confidence = 0.55

    async def decide(
        self,
        data: InterruptDecisionInput,
    ) -> InterruptDecisionResult:
        """
        LLM 기반 인터럽트 판단

        - 여기서의 rule은 LLM 판단으로 넘어가기 전에
          한 번 더 안전적으로 판단하는 역할을 한다.
        - 실제 질문 타이밍은 LLM이 발화 흐름을 보고 판단한다.
        """

        # 1. 인터럽트 비활성화면 무조건 차단
        if not data.interrupt_enabled:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason=(
                    "interrupt_enabled가 false이므로 "
                    "인터럽트를 수행하지 않습니다."
                ),
                interrupt_type=None,
                triggered_by=["disabled"],
                confidence=1.0,
            )

        # 2. 쿨다운 중이면 무조건 차단
        if data.cooldown_remaining_ms > 0:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason=(
                    "쿨다운이 아직 남아 있어 "
                    "인터럽트를 수행하지 않습니다."
                ),
                interrupt_type=None,
                triggered_by=["cooldown"],
                confidence=1.0,
            )

        latest_utterance = (
            data.context_state.latest_utterance.strip()
        )
        recent_transcript = (
            data.context_state.recent_transcript.strip()
        )

        # 3. 발표 내용이 너무 짧으면 LLM 호출하지 않음
        if (
            len(recent_transcript) < 30
            and len(latest_utterance) < 10
        ):
            return InterruptDecisionResult(
                should_interrupt=False,
                reason=(
                    "아직 발표 내용이 충분히 쌓이지 않아 "
                    "질문 타이밍을 판단하지 않습니다."
                ),
                interrupt_type=None,
                triggered_by=["too_short_context"],
                confidence=1.0,
            )

        try:
            prompt = self._build_prompt(data)

            # 중요:
            # gpt-5 계열 일부 모델은 temperature=0.2 같은 값을
            # 지원하지 않을 수 있다.
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
                response_format={
                    "type": "json_object",
                },
            )

            content = (
                response.choices[0].message.content or "{}"
            )
            parsed = json.loads(content)

            should_interrupt = bool(
                parsed.get("should_interrupt", False)
            )
            reason = str(
                parsed.get(
                    "reason",
                    "LLM 판단 결과입니다.",
                )
            )
            interrupt_type = parsed.get("interrupt_type")

            triggered_by = self._normalize_triggered_by(
                parsed.get("triggered_by", [])
            )
            confidence = self._normalize_confidence(
                parsed.get("confidence", 0.0)
            )

            # should_interrupt가 false면
            # interrupt_type은 없어도 됨
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
                    reason=(
                        "질문 타이밍일 가능성은 있지만 "
                        "확신도가 낮아 개입하지 않습니다. "
                        f"이유: {reason}"
                    ),
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
                reason=(
                    "LLM 판단 실패로 인터럽트를 "
                    f"수행하지 않습니다: {e}"
                ),
                interrupt_type=None,
                triggered_by=["llm_error"],
                confidence=0.0,
            )

    def _system_prompt(self) -> str:
        return """
너는 발표 연습 서비스에서 실시간으로 청중의 개입 시점을 판단하는 인터럽트 판단기다.

목표:
지금 질문하는 것이 조금 더 기다리는 것보다 발표자의 흐름과 청중의 이해에
더 도움이 되는지 판단한다.

질문을 많이 만드는 것이 목적이 아니다.
질문할 가치가 있는 내용과 자연스러운 타이밍이 모두 있을 때만 개입한다.

판단 원칙:
- 발화가 하나의 의미 단위를 어느 정도 마쳤는지 먼저 살펴본다.
- 문장이나 설명이 이어지는 중이라면 대체로 기다린다.
- 최근 발표 내용에서 실제 청중이 바로 궁금해할 만한 구체적인 지점이 있는지 본다.
- 그 궁금증이 발표의 이해, 검증, 적용 또는 흐름 회복에 실질적으로 도움이 되는지 판단한다.
- 슬라이드나 대본 맥락상 곧 설명될 가능성이 높다면 성급하게 개입하지 않는다.
- 최근 질문과 핵심 요구가 겹치면 표현이 달라도 반복 질문으로 본다.
- 상황별 지침은 청중의 관점과 적극성을 조정하는 참고 기준이다.
- 상황별 지침의 모든 항목을 기계적으로 적용하려 하지 않는다.
- 압박 수준이 높더라도 미완성 발화를 끊거나, 내용 없는 트집을 잡거나,
  같은 요구를 반복하지 않는다.
- WPM, 필러, 침묵, 망설임, 스트레스 지표는 타이밍을 보조하는 신호일 뿐이다.
- 음성 지표만으로 질문 여부를 결정하지 않는다.

개입을 고려할 수 있는 경우:
- 중요한 주장이나 개념이 제시됐지만 이해에 필요한 핵심 설명이 비어 있는 경우
- 결과나 선택이 제시됐고, 그 이유·근거·조건이 자연스럽게 궁금해지는 경우
- 구체적인 예시나 연결 설명이 있으면 현재 흐름을 훨씬 쉽게 이해할 수 있는 경우
- 발표자가 막힌 상태이며 짧은 질문이 다음 설명을 자연스럽게 이끌 수 있는 경우
- 방금 발표한 내용과 앞선 내용의 관계가 불분명해 청중이 흐름을 놓칠 수 있는 경우

기다리는 편이 좋은 경우:
- 인사, 자기소개, 주제 소개 등 아직 판단할 맥락이 충분하지 않은 경우
- 발표자가 방금 제시한 내용을 바로 이어서 설명하고 있는 경우
- 질문의 근거가 되는 구체적인 내용 없이 막연한 궁금증만 있는 경우
- 단순한 말하기 습관이나 일시적인 음성 변화만 감지된 경우
- 현재 질문하더라도 발표의 이해에 큰 도움이 되지 않는 경우
- 발표자가 잠시 멈췄지만 생각을 정리해 계속 말할 가능성이 높은 경우

결정 방식:
- 타이밍은 자연스럽지만 물을 만한 내용이 없다면 should_interrupt=false다.
- 물을 만한 내용은 있지만 발화가 이어지는 중이라면 should_interrupt=false다.
- 조금 더 기다리는 편이 자연스럽다면 should_interrupt=false다.
- 질문의 가치와 자연스러운 타이밍이 모두 충족될 때 should_interrupt=true다.
- false는 발표 내용이 좋거나 나쁘다는 평가가 아니라,
  현재는 조금 더 듣는 편이 낫다는 의미다.

interrupt_type 선택 기준:
- natural_question: 일반적인 청중 궁금증
- concept_question: 핵심 개념이나 용어 설명이 필요한 경우
- reason_question: 선택이나 주장에 대한 이유가 필요한 경우
- evidence_question: 주장이나 결과를 뒷받침하는 근거가 필요한 경우
- example_question: 구체적인 예시가 이해에 도움이 되는 경우
- connection_question: 앞뒤 내용의 연결 관계가 불분명한 경우
- recovery_question: 발표자가 막힌 상황에서 흐름 회복을 도울 수 있는 경우

출력 규칙:
- 반드시 JSON object만 반환한다.
- 모든 필드를 항상 포함한다.
- reason은 판단의 핵심 근거가 드러나는 짧은 한국어 한 문장으로 작성한다.
- should_interrupt=false라면 interrupt_type은 null로 작성한다.
- triggered_by에는 실제 판단에 사용한 항목만 넣는다.
- confidence는 현재 판단에 대한 확신 정도를 나타낸다.
- 빈 JSON object를 반환하지 않는다.
- JSON 외의 설명이나 마크다운을 출력하지 않는다.

출력 형식:
{
  "should_interrupt": true 또는 false,
  "reason": "지금 개입하거나 기다리는 핵심 이유",
  "interrupt_type": "natural_question | concept_question | reason_question | evidence_question | example_question | connection_question | recovery_question | null",
  "triggered_by": [
    "curiosity",
    "concept_needs_detail",
    "reason_unclear",
    "evidence_needed",
    "example_needed",
    "connection_unclear",
    "hesitation"
  ],
  "confidence": 0.0부터 1.0 사이 숫자
}
"""

    def _build_prompt(
        self,
        data: InterruptDecisionInput,
    ) -> str:
        speech = data.speech_metrics
        context = data.context_state

        previous_questions_text = "\n".join(
            [
                f"- {question}"
                for question in data.previous_questions[-3:]
            ]
        ) or "없음"

        return f"""
[판단 목표]
아래 정보를 종합해 지금 질문하는 편이 조금 더 기다리는 것보다
자연스럽고 유익한지 판단해라.

질문을 실제로 작성하지 말고, 개입 여부와 판단 근거만 반환한다.

[정보 적용 방식]
- 최근 발표 흐름과 방금 들은 발화를 가장 중요하게 본다.
- 상황별 지침은 청중의 관점과 압박 정도를 조정하는 가이드다.
- 상황별 지침의 모든 내용을 한 번의 판단에 반영하려 하지 않는다.
- 현재 발표 내용에서 실제로 드러난 정보만 근거로 사용한다.
- 구체적으로 물을 만한 지점이 떠오르지 않으면 개입하지 않는다.
- 음성 지표는 발표 내용에 기반한 판단을 보조할 때만 사용한다.

[세션 설정]
- 발표 유형: {data.presentation_type}
- 청중 유형: {data.audience_type}
- 청중 인원: {f"{data.audience_count}명" if data.audience_count else "알 수 없음"}
- 압박 수준: {data.pressure_level}

[상황별 지침]
{build_scenario_block(
    data.presentation_type,
    data.audience_type,
    data.pressure_level,
    data.audience_count,
)}

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

[최종 판단 전 확인]
1. 방금 발화가 하나의 의미 단위를 어느 정도 마쳤는가?
2. 지금 발표 내용에서 실제 청중이 물을 만한 구체적인 지점이 있는가?
3. 질문이 발표의 이해, 검증, 적용 또는 흐름 회복에 도움이 되는가?
4. 질문이 현재 발표 흐름을 불필요하게 끊지는 않는가?
5. 최근 질문과 핵심 요구가 겹치지 않는가?
6. 조금 더 기다리면 발표자가 바로 설명할 가능성이 높지는 않은가?
7. 단순한 음성 지표 변화만으로 개입하려는 것은 아닌가?

질문의 가치와 자연스러운 타이밍이 모두 확인되는 경우에만
should_interrupt=true로 판단해라.

반드시 JSON object만 반환해라.
"""

    def _normalize_triggered_by(
        self,
        value: Any,
    ) -> list[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [
                str(item)
                for item in value
            ]

        return [str(value)]

    def _normalize_confidence(
        self,
        value: Any,
    ) -> float:
        try:
            confidence = float(value)
        except Exception:
            confidence = 0.0

        return max(
            0.0,
            min(confidence, 1.0),
        )