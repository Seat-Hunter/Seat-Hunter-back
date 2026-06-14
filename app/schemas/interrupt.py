# app/schemas/interrupt.py

"""
Interrupt Decision Engine에서 사용하는 입력 및 출력 데이터 구조

LLM 기반 인터럽트 판단용 스키마
- 음성 지표는 참고 신호로 사용
- 실제 인터럽트 여부는 최근 발표 내용과 흐름을 보고 LLM이 판단
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class SpeechMetricsInput(BaseModel):
    """
    Speech Analyzer에서 넘어오는 발화 지표
    """
    recent_wpm: float = 0.0
    average_wpm: float = 0.0
    filler_count: int = 0
    silence_duration: int = 0
    hesitation_score: float = 0.0
    stress_score: float = 0.0


class ContextStateInput(BaseModel):
    """
    발표 맥락 상태
    """
    current_topic: Optional[str] = None
    drift_score: float = 0.0
    topic_shift_detected: bool = False

    # LLM 판단에 필요한 실제 발화 내용
    latest_utterance: str = ""
    recent_transcript: str = ""

    # 발표 자료/대본이 있으면 나중에 연결 가능
    slide_context: Optional[str] = None
    script_context: Optional[str] = None


class InterruptDecisionInput(BaseModel):
    """
    Interrupt Decision Engine 전체 입력
    """
    speech_metrics: SpeechMetricsInput
    context_state: ContextStateInput

    cooldown_remaining_ms: int = 0
    pressure_level: str = "medium"
    interrupt_enabled: bool = True

    presentation_type: str = "academic"
    audience_type: str = "professor"

    previous_questions: List[str] = Field(default_factory=list)


class InterruptDecisionResult(BaseModel):
    """
    Interrupt Decision Engine 판단 결과
    """
    should_interrupt: bool
    reason: str
    interrupt_type: Optional[str] = None
    triggered_by: List[str] = Field(default_factory=list)

    # LLM 판단 근거 확인용
    confidence: float = 0.0