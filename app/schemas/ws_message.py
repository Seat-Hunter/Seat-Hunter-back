from pydantic import BaseModel
from typing import Literal

class AudioChunkMsg(BaseModel):
    type: Literal["audio_chunk"]
    timestamp_ms: int
    audio_base64: str

class PartialTranscriptMsg(BaseModel):
    type: Literal["partial_transcript"]
    timestamp_ms: int
    text: str

class VadStateMsg(BaseModel):
    type: Literal["vad_state"]
    timestamp_ms: int
    is_speaking: bool

class TtsFinishedMsg(BaseModel):
    type: Literal["tts_finished"]
    question_id: str

class AnswerStateMsg(BaseModel):
    type: Literal["answer_state"]
    question_id: str
    state: Literal["started", "ended"]

def make_partial_transcript(text: str) -> dict:
    return {"type": "partial_transcript", "text": text}

def make_final_transcript(segment_id: str, text: str, start_ms: int, end_ms: int) -> dict:
    return {"type": "final_transcript", "segment_id": segment_id,
            "text": text, "start_ms": start_ms, "end_ms": end_ms}

def make_live_metrics(wpm: float, filler_count: int, silence_ms: int, stress_score: float) -> dict:
    return {"type": "live_metrics", "wpm": wpm, "filler_count": filler_count,
            "silence_ms": silence_ms, "stress_score": stress_score}

def make_session_state(state: str) -> dict:
    return {"type": "session_state", "state": state}

def make_stop_tts(reason: str = "barge_in_detected") -> dict:
    return {"type": "stop_tts", "reason": reason}