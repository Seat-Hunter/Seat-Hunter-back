from fastapi import APIRouter, HTTPException
from app.core.supabase_client import get_supabase
import json

router = APIRouter()


def _parse_json_field(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []


@router.get(
    "/sessions/{session_id}/report",
    summary="세션 리포트 조회",
)
async def get_report(session_id: str):
    sb = get_supabase()
    res = sb.table("presentation_histories").select("*").eq("session_id", session_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="리포트 없음. 세션이 종료되지 않았거나 생성 전입니다.")

    row = res.data[0]
    return {
        "session_id":         row["session_id"],
        "presentation_type":  row.get("presentation_type"),
        "audience_type":      row.get("audience_type"),
        "duration_seconds":   row.get("duration_seconds"),
        "avg_wpm":            row.get("avg_wpm", 0),
        "filler_count":       row.get("filler_count", 0),
        "silence_count":      row.get("silence_count", 0),
        "interrupt_count":    row.get("interrupt_count", 0),
        "recovery_score":     row.get("recovery_score", 0),
        "overall_score":      row.get("overall_score", 0),
        "strengths":          _parse_json_field(row.get("strengths")),
        "weaknesses":         _parse_json_field(row.get("weaknesses")),
        "improvements":       _parse_json_field(row.get("feedback")),
        "curriculum_next":    row.get("curriculum_next"),
        "interrupts":         _parse_json_field(row.get("interrupts")),
        "created_at":         row.get("created_at"),
    }


@router.get(
    "/users/{user_id}/sessions",
    summary="유저 세션 목록 조회",
)
async def get_user_sessions(user_id: int):
    sb = get_supabase()
    res = sb.table("presentation_histories") \
        .select("id, session_id, title, presentation_type, audience_type, duration_seconds, overall_score, created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()
    return res.data


@router.get(
    "/sessions/{session_id}/interrupts",
    summary="세션 인터럽트 목록 조회",
)
async def get_session_interrupts(session_id: str):
    sb = get_supabase()
    res = sb.table("presentation_histories").select("interrupts").eq("session_id", session_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return _parse_json_field(res.data[0].get("interrupts"))
