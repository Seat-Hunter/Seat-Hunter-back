from supabase import create_client
from app.core.config import settings

supabase = create_client(settings.supabase_url, settings.supabase_key)


async def insert_interrupt(session_id: str, question_id: str, question_text: str,
                            reason: str, pressure_level: str, triggered_at_ms: int):
    supabase.table("interrupt_events").insert({
        "session_id": session_id,
        "question_id": question_id,
        "question_text": question_text,
        "reason": reason,
        "pressure_level": pressure_level,
        "triggered_at_ms": triggered_at_ms,
    }).execute()


async def get_session_interrupts(session_id: str):
    res = supabase.table("interrupt_events").select("*").eq("session_id", session_id).execute()
    return res.data