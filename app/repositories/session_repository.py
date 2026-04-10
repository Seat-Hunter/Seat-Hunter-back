from supabase import create_client
from app.core.config import settings
import datetime

supabase = create_client(settings.supabase_url, settings.supabase_key)


async def insert_session(session_id: str, config: dict):
    supabase.table("presentation_sessions").insert({
        "id": session_id,
        "user_id": config.get("user_id", 1),
        "status": "READY",
        "presentation_type": config.get("presentation_type"),
        "audience_type": config.get("audience_type"),
        "audience_count": config.get("audience_count"),
        "pressure_level": config.get("pressure_level"),
        "duration_seconds": config.get("duration_seconds"),
        "interrupt_enabled": config.get("interrupt_enabled"),
    }).execute()

    script = config.get("script_text")
    slides = config.get("slide_texts")
    if script or slides:
        supabase.table("session_configs").insert({
            "session_id": session_id,
            "script_text": script,
            "slide_texts_json": slides,
        }).execute()


async def update_session_started(session_id: str):
    supabase.table("presentation_sessions").update({
        "status": "RUNNING",
        "started_at": datetime.datetime.utcnow().isoformat(),
    }).eq("id", session_id).execute()


async def update_session_ended(session_id: str):
    supabase.table("presentation_sessions").update({
        "status": "FINISHED",
        "ended_at": datetime.datetime.utcnow().isoformat(),
    }).eq("id", session_id).execute()


async def get_session(session_id: str):
    res = supabase.table("presentation_sessions").select("*").eq("id", session_id).execute()
    return res.data[0] if res.data else None


async def get_user_sessions(user_id: int):
    res = supabase.table("presentation_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return res.data