from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class PressureLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

class SessionState(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    ANSWERING = "ANSWERING"
    FINISHED = "FINISHED"

class SessionCreateRequest(BaseModel):
    user_id: int
    presentation_type: str
    audience_type: str
    audience_count: Optional[int] = None
    pressure_level: PressureLevel = PressureLevel.medium
    duration_seconds: int = 300
    interrupt_enabled: bool = True
    script_text: Optional[str] = None
    slide_texts: Optional[List[str]] = None

class SessionCreateResponse(BaseModel):
    session_id: str
    state: SessionState