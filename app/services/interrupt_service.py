# 발표 중 실시간 개입 여부를 판단하는 Interrupt Decision Engine 서비스
# 이 서비스는 Speech Analyzer, Context Tracker, NLP/LLM 분석 결과를 종합하여
# 지금 질문으로 개입해야 하는지 여부와 그 이유, 인터럽트 타입을 결정한다.

from app.schemas.interrupt import (
    InterruptDecisionInput,
    InterruptDecisionResult,
)


class InterruptService:
    """
    Interrupt Decision Engine 서비스

    주요 역할
    - 침묵, 주제 이탈, 필러 급증, WPM 급감 등을 기반으로 인터럽트 여부 판단
    - cooldown 상태를 고려하여 너무 자주 질문하지 않도록 제어
    - pressure_level에 따라 개입 민감도 조정
    """

    def __init__(self):
        # 이전 턴과 비교하기 위한 내부 상태
        self.previous_filler_count = 0
        self.previous_recent_wpm = None

    def decide(self, data: InterruptDecisionInput) -> InterruptDecisionResult:
        """
        현재 상태를 바탕으로 인터럽트 여부를 판단한다.
        """
        # 1. 인터럽트 비활성화면 무조건 중단
        if not data.interrupt_enabled:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="interrupt_enabled가 false이므로 인터럽트를 수행하지 않습니다.",
                interrupt_type=None,
                triggered_by=[]
            )

        # 2. cooldown이 남아 있으면 인터럽트 금지
        if data.cooldown_remaining_ms > 0:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="쿨다운이 아직 남아 있어 인터럽트를 수행하지 않습니다.",
                interrupt_type=None,
                triggered_by=[]
            )

        triggered_by = []

        speech = data.speech_metrics
        context = data.context_state

        # 3. silence_ms >= 3000
        if speech.silence_duration >= 3000:
            triggered_by.append("long_silence")

        # 4. drift_score > 0.65
        if context.drift_score > 0.65:
            triggered_by.append("topic_drift")

        # 5. filler 연속 급증
        if self._is_filler_spike(speech.filler_count):
            triggered_by.append("filler_spike")

        # 6. WPM 급격히 감소
        if self._is_wpm_drop(speech.recent_wpm):
            triggered_by.append("wpm_drop")

        # 7. pressure=high & topic_shift_detected
        if (
            data.pressure_level == "high"
            and context.topic_shift_detected
        ):
            triggered_by.append("high_pressure_topic_shift")

        # 다음 판단을 위해 이전 상태 업데이트
        self.previous_filler_count = speech.filler_count
        self.previous_recent_wpm = speech.recent_wpm

        # 트리거가 하나도 없으면 인터럽트 안 함
        if not triggered_by:
            return InterruptDecisionResult(
                should_interrupt=False,
                reason="현재 인터럽트 트리거 조건을 만족하지 않았습니다.",
                interrupt_type=None,
                triggered_by=[]
            )

        # 트리거가 있으면 인터럽트 타입 결정
        interrupt_type = self._select_interrupt_type(triggered_by, context.drift_score)

        reason = self._build_reason(triggered_by, data.pressure_level)

        return InterruptDecisionResult(
            should_interrupt=True,
            reason=reason,
            interrupt_type=interrupt_type,
            triggered_by=triggered_by
        )

    def _is_filler_spike(self, current_filler_count: int) -> bool:
        """
        필러가 갑자기 많이 증가했는지 판단
        현재는 단순하게 이전 값 대비 2개 이상 증가하면 급증으로 본다.
        """
        filler_delta = current_filler_count - self.previous_filler_count
        return filler_delta >= 2

    def _is_wpm_drop(self, current_recent_wpm: float) -> bool:
        """
        최근 WPM이 이전보다 급격히 감소했는지 판단
        현재는 이전 recent_wpm 대비 25% 이상 감소하면 급격한 감소로 본다.
        """
        if self.previous_recent_wpm is None:
            return False

        if self.previous_recent_wpm <= 0:
            return False

        drop_ratio = (self.previous_recent_wpm - current_recent_wpm) / self.previous_recent_wpm
        return drop_ratio >= 0.25

    def _select_interrupt_type(self, triggered_by: list[str], drift_score: float) -> str:
        """
        어떤 유형의 인터럽트를 할지 결정

        예시
        - topic_drift가 강하면 topic_clarification
        - silence나 wpm_drop이면 encouragement_probe
        - filler_spike면 logic_probe
        """
        if "topic_drift" in triggered_by or drift_score > 0.8:
            return "topic_clarification"

        if "high_pressure_topic_shift" in triggered_by:
            return "pressure_probe"

        if "long_silence" in triggered_by:
            return "encouragement_probe"

        if "wpm_drop" in triggered_by:
            return "recovery_probe"

        if "filler_spike" in triggered_by:
            return "logic_probe"

        return "general_probe"

    def _build_reason(self, triggered_by: list[str], pressure_level: str) -> str:
        """
        사용자에게 남기거나 로그에 저장할 개입 이유 문자열 생성
        """
        reason_map = {
            "long_silence": "3초 이상 침묵이 감지되었습니다.",
            "topic_drift": "주제 이탈 점수가 기준치를 초과했습니다.",
            "filler_spike": "필러 사용이 급격히 증가했습니다.",
            "wpm_drop": "최근 말속도가 급격히 감소했습니다.",
            "high_pressure_topic_shift": "고압박 모드에서 주제 전환이 감지되었습니다.",
        }

        parts = [reason_map[key] for key in triggered_by if key in reason_map]

        if not parts:
            return "인터럽트 조건이 감지되었습니다."

        return f"[pressure={pressure_level}] " + " ".join(parts)