# 세션 종료 후 종합 리포트를 생성할 때 사용하는 입력 및 출력 데이터 구조를 정의하는 스키마 파일
# 이 파일은 transcript, interrupt log, answer evaluation log, speech metrics, recovery metrics를 받아
# 최종 요약 통계, 점수, 개선 포인트, 누적 패턴, 커리큘럼 추천을 반환하기 위한 형식을 정의한다.

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

    - wpm_recovery_speed_score: 정상 말속도로 회복하는 속도 (0~100)
    - filler_reduction_score: 필러 감소율 점수 (0~100)
    - silence_reduction_score: 침묵 감소 점수 (0~100)
    """
    wpm_recovery_speed_score: float
    filler_reduction_score: float
    silence_reduction_score: float


class UserPatternInput(BaseModel):
    """
    사용자 누적 패턴 입력
    기존 저장값이 있다면 이 구조로 넘겨받아 갱신할 수 있다.
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