# Context Tracker에서 사용하는 입력 및 출력 데이터 구조 정의
# 슬라이딩 윈도우 기반으로 발표의 주제 흐름과 진행률을 추적한다.

from typing import List, Optional
from pydantic import BaseModel, Field


class ContextTrackerInput(BaseModel):
    """
    Context Tracker 입력 데이터
    """
    transcript: str
    slide_texts: List[str]
    window_size: int = 5


class ContextTrackerResult(BaseModel):
    """
    Context Tracker 출력 데이터
    """
    current_topic: Optional[str]
    progress_index: float
    drift_score: float
    recent_context: List[str] = Field(default_factory=list)