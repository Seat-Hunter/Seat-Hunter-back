from supabase import create_client
from app.core.config import settings

supabase = create_client(settings.supabase_url, settings.supabase_key)


async def insert_segment(session_id: str, segment_id: str, segment_index: int,
                          text: str, start_ms: int, end_ms: int, source: str = "deepgram"):
    supabase.table("speech_segments").insert({
        "session_id": session_id,
        "segment_index": segment_index,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "text": text,
        "source": source,
        "is_final": True,
    }).execute()