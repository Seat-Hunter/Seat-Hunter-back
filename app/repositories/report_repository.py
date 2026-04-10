from supabase import create_client
from app.core.config import settings

supabase = create_client(settings.supabase_url, settings.supabase_key)


async def insert_report(session_id: str, report: dict):
    supabase.table("session_reports").insert({
        "session_id": session_id,
        **report,
    }).execute()


async def get_report(session_id: str):
    res = supabase.table("session_reports").select("*").eq("session_id", session_id).execute()
    return res.data[0] if res.data else None