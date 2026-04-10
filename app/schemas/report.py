from pydantic import BaseModel
from typing import List, Optional

class ReportSummary(BaseModel):
    avg_wpm: float
    filler_count: int
    interrupt_count: int
    recovery_score: float
    overall_score: float

class ReportFeedback(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    improvements: List[str]

class ReportResponse(BaseModel):
    session_id: str
    summary: ReportSummary
    feedback: ReportFeedback
    curriculum_next: Optional[str] = None