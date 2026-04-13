# Speech Analyzer의 입력 및 출력 스키마 정의

from pydantic import BaseModel


class SpeechAnalysisInput(BaseModel):
    """Speech Analyzer 입력 데이터"""
    text: str
    start_ms: int
    end_ms: int
    is_speaking: bool
    is_interrupt: bool = False


class SpeechAnalysisResult(BaseModel):
    """Speech Analyzer 출력 데이터"""
    recent_wpm: float
    average_wpm: float
    filler_count: int
    silence_duration: int
    silence_count: int
    response_latency: int
    hesitation_score: float
    stress_score: float