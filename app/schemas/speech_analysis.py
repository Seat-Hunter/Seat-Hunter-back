# Speech Analyzer의 입력 및 출력 스키마 정의

from pydantic import BaseModel


class SpeechAnalysisInput(BaseModel):
    """Speech Analyzer 입력 데이터"""
    text: str
    start_ms: int
    end_ms: int
    is_speaking: bool
    is_interrupt: bool = False
    excluded_ms: int = 0  # 질문 청취/답변/평가 대기 등 평균 WPM 계산에서 제외할 누적 시간(ms)


class SpeechAnalysisResult(BaseModel):
    """Speech Analyzer 출력 데이터"""
    recent_wpm: float
    average_wpm: float
    filler_count: int           # 세션 전체 누적 필러 수
    filler_count_segment: int   # 이번 세그먼트 필러 수 (피드백 판단용)
    silence_duration: int       # 세션 전체 누적 침묵 ms
    current_silence_ms: int     # 직전 세그먼트 이후 침묵 ms (피드백 판단용)
    silence_count: int
    response_latency: int
    hesitation_score: float
    stress_score: float