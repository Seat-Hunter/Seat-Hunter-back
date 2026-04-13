# LLM 분석 엔진을 언제 호출할지 결정하는 스케줄러 서비스
# 10초 주기, 주제 전환 감지, 인터럽트 직전 여부 등을 기준으로 LLM 호출 여부를 판단한다.

from app.schemas.analysis import NLPAnalysisResult


class AnalysisSchedulerService:
    """
    LLM 호출 스케줄 판단 서비스

    호출 조건 예시
    - 마지막 LLM 호출 후 10초 이상 경과
    - NLP 분석에서 주제 전환 감지
    - 인터럽트 직전
    """

    def __init__(self, llm_interval_ms: int = 10000):
        # 마지막 LLM 호출 시점 저장
        self.last_llm_call_time_ms: int | None = None
        self.llm_interval_ms = llm_interval_ms

    def should_call_llm(
        self,
        current_time_ms: int,
        nlp_result: NLPAnalysisResult,
        is_interrupt_imminent: bool
    ) -> bool:
        """
        이번 턴에 LLM을 호출할지 판단한다.
        """
        # 인터럽트 직전이면 우선 호출
        if is_interrupt_imminent:
            return True

        # 주제 이탈이 감지되면 호출
        if nlp_result.topic_shift_detected:
            return True

        # 한 번도 호출 안 했으면 초기 1회 호출 허용
        if self.last_llm_call_time_ms is None:
            return True

        elapsed = current_time_ms - self.last_llm_call_time_ms
        return elapsed >= self.llm_interval_ms

    def mark_llm_called(self, current_time_ms: int) -> None:
        """
        실제로 LLM을 호출한 뒤 호출 시점을 기록한다.
        """
        self.last_llm_call_time_ms = current_time_ms