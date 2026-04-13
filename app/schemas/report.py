from typing import List, Optional
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """
    전체 transcript의 한 세그먼트
    """
    text: str
    start_ms: int
    end_ms: int


class InterruptLogItem(BaseModel):
    """
    인터럽트 로그 한 건
    """
    question_text: str
    reason: str
    interrupt_type: Optional[str] = None
    answered: bool = False
    answer_score: Optional[float] = None
    follow_up_count: int = 0


class AnswerEvaluationLogItem(BaseModel):
    """
    답변 평가 로그 한 건
    """
    question_text: str
    user_answer: str
    answer_score: float
    follow_up_needed: bool
    audience_reaction: str


class SpeechMetricsSnapshot(BaseModel):
    """
    세션 중 저장된 발화 지표 스냅샷
    """
    recent_wpm: float
    average_wpm: float
    filler_count: int
    silence_duration: int
    hesitation_score: float
    stress_score: float


class RecoveryMetricsInput(BaseModel):
    """
    인터럽트 후 회복 지표 입력
    """
    wpm_recovery_speed_score: float
    filler_reduction_score: float
    silence_reduction_score: float


class UserPatternInput(BaseModel):
    """
    사용자 누적 패턴 입력
    """
    session_count: int = 0
    repeated_weaknesses: List[str] = Field(default_factory=list)


class ReportGenerationInput(BaseModel):
    """
    Report Generator 전체 입력
    """
    transcript: List[TranscriptSegment] = Field(default_factory=list)
    interrupt_log: List[InterruptLogItem] = Field(default_factory=list)
    answer_evaluation_log: List[AnswerEvaluationLogItem] = Field(default_factory=list)
    speech_metrics: List[SpeechMetricsSnapshot] = Field(default_factory=list)
    recovery_metrics: RecoveryMetricsInput
    user_pattern: UserPatternInput = Field(default_factory=UserPatternInput)


class ReportSummary(BaseModel):
    """
    요약 통계
    """
    avg_wpm: float
    max_wpm: float
    filler_count: int
    silence_count: int
    interrupt_count: int
    avg_answer_score: float


class UserPatternOutput(BaseModel):
    """
    누적 패턴 갱신 결과
    """
    session_count: int
    repeated_weaknesses: List[str]
    trend: str


class ReportGenerationResult(BaseModel):
    """
    최종 리포트 생성 결과
    """
    summary: ReportSummary
    strengths: List[str]
    weaknesses: List[str]
    improvements: List[str]
    overall_score: float
    recovery_score: float
    curriculum_next: str
    updated_pattern: UserPatternOutput


class ReportFeedback(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    improvements: List[str]


class ReportResponse(BaseModel):
    session_id: str
    summary: ReportSummary
    feedback: ReportFeedback
    curriculum_next: Optional[str] = None