# Interrupt Decision Engine에서 사용하는 입력 및 출력 데이터 구조를 정의하는 스키마 파일
# 이 파일은 실시간 발화 지표, 맥락 상태, NLP/LLM 분석 결과를 받아
# 인터럽트 여부와 이유, 인터럽트 타입을 반환하기 위한 데이터 형식을 정의한다.

from typing import Optional, List
from pydantic import BaseModel


class SpeechMetricsInput(BaseModel):
    """
    Speech Analyzer에서 넘어오는 발화 지표
    """
    recent_wpm: float
    average_wpm: float
    filler_count: int
    silence_duration: int
    hesitation_score: float
    stress_score: float


class ContextStateInput(BaseModel):
    """
    Context Tracker / NLP / LLM 쪽에서 넘어오는 문맥 상태
    """
    drift_score: float = 0.0
    current_topic: Optional[str] = None
    topic_shift_detected: bool = False


class InterruptDecisionInput(BaseModel):
    """
    Interrupt Decision Engine 전체 입력

    - speech_metrics: Speech Analyzer 결과
    - context_state: Context Tracker / LLM 기반 주제 상태
    - cooldown_remaining_ms: 아직 쿨다운이 남아 있으면 남은 시간
    - pressure_level: low / medium / high
    - interrupt_enabled: false면 어떤 경우에도 인터럽트 금지
    """
    speech_metrics: SpeechMetricsInput
    context_state: ContextStateInput
    cooldown_remaining_ms: int = 0
    pressure_level: str = "medium"
    interrupt_enabled: bool = True


class InterruptDecisionResult(BaseModel):
    """
    Interrupt Decision Engine 판단 결과

    - should_interrupt: 지금 개입할지 여부
    - reason: 개입 이유
    - interrupt_type: 어떤 유형의 질문을 할지
    - triggered_by: 어떤 조건이 발동했는지
    """
    should_interrupt: bool
    reason: str
    interrupt_type: Optional[str] = None
    triggered_by: List[str] = []