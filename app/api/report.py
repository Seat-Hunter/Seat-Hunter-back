import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from app.core.supabase_client import get_supabase
from app.api.deps import get_current_user_id

router = APIRouter()

# end_session()의 리포트 생성(Gemini 호출 포함)이 끝나기 전에 조회 요청이 오면
# 바로 404를 내지 않고 최대 20초까지 기다렸다가 다시 확인한다.
REPORT_POLL_INTERVAL_SEC = 2
REPORT_POLL_TIMEOUT_SEC = 20


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

    elapsed = 0.0
    while True:
        res = sb.table("presentation_histories").select("*").eq("session_id", session_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="리포트 없음. 세션이 종료되지 않았거나 생성 전입니다.")

        row = res.data[0]

        # overall_score가 NULL(0) 이면 end_session()이 아직 완료되지 않은 것.
        # Supabase 테이블 DEFAULT가 0인 경우 NULL 대신 0이 오므로 둘 다 처리.
        if row.get("overall_score"):
            break

        if elapsed >= REPORT_POLL_TIMEOUT_SEC:
            raise HTTPException(status_code=404, detail="리포트 생성 중입니다. 잠시 후 다시 시도하세요.")

        await asyncio.sleep(REPORT_POLL_INTERVAL_SEC)
        elapsed += REPORT_POLL_INTERVAL_SEC

    # scripts 조회
    scripts_res = sb.table("scripts") \
        .select("transcript, start_ms, end_ms, segment_index, timestamp") \
        .eq("session_id", session_id) \
        .order("segment_index") \
        .execute()
    full_script = " ".join([s["transcript"] for s in scripts_res.data]) if scripts_res.data else ""

    return {
        "session_id":         row["session_id"],
        "topic":              row.get("title"),
        "presentation_type":  row.get("presentation_type"),
        "audience_type":      row.get("audience_type"),
        "audience_count":     row.get("audience_count"),
        "pressure_level":     row.get("pressure_level"),
        "duration_seconds":   row.get("duration_seconds"),
        "avg_wpm":            row.get("avg_wpm", 0),
        "filler_count":       row.get("filler_count", 0),
        "silence_count":      row.get("silence_count", 0),
        "interrupt_count":    row.get("interrupt_count", 0),
        "response_score":     row.get("recovery_score", 0),
        "overall_score":      row.get("overall_score", 0),
        "criteria_scores":    _parse_json_field(row.get("criteria_scores")),
        "strengths":          _parse_json_field(row.get("strengths")),
        "weaknesses":         _parse_json_field(row.get("weaknesses")),
        "improvements":       _parse_json_field(row.get("feedback")),
        "curriculum_next":    row.get("curriculum_next"),
        "interrupts":         _parse_json_field(row.get("interrupts")),
        "created_at":         row.get("created_at"),
        "script_segments":    scripts_res.data,
        "full_script":        full_script,
    }


@router.get(
    "/sessions/{session_id}/scripts",
    summary="세션 대본 조회",
)
async def get_session_scripts(session_id: str):
    sb = get_supabase()
    res = sb.table("scripts") \
        .select("transcript, start_ms, end_ms, segment_index, timestamp") \
        .eq("session_id", session_id) \
        .order("segment_index") \
        .execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="스크립트가 없습니다.")
    return {
        "session_id":  session_id,
        "segments":    res.data,
        "full_script": " ".join([s["transcript"] for s in res.data]),
    }


@router.get(
    "/users/me/sessions",
    summary="내 세션 목록 조회",
)
async def get_user_sessions(user_id: int = Depends(get_current_user_id)):
    sb = get_supabase()
    res = sb.table("presentation_histories") \
        .select(
            "id, session_id, title, presentation_type, audience_type, audience_count, "
            "pressure_level, duration_seconds, overall_score, interrupt_count, created_at"
        ) \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()
    return res.data


@router.delete(
    "/sessions/{session_id}",
    summary="세션 삭제",
)
async def delete_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    sb = get_supabase()
    res = sb.table("presentation_histories") \
        .select("session_id") \
        .eq("session_id", session_id) \
        .eq("user_id", user_id) \
        .execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    sb.table("scripts").delete().eq("session_id", session_id).execute()
    sb.table("question_answers").delete().eq("session_id", session_id).execute()
    sb.table("presentation_histories").delete().eq("session_id", session_id).execute()

    return {"deleted": True, "session_id": session_id}


@router.delete(
    "/users/me/sessions",
    summary="내 세션 전체 삭제",
)
async def delete_all_user_sessions(user_id: int = Depends(get_current_user_id)):
    sb = get_supabase()
    res = sb.table("presentation_histories").select("session_id").eq("user_id", user_id).execute()
    session_ids = [row["session_id"] for row in (res.data or [])]

    if session_ids:
        sb.table("scripts").delete().in_("session_id", session_ids).execute()
        sb.table("question_answers").delete().in_("session_id", session_ids).execute()
        sb.table("presentation_histories").delete().eq("user_id", user_id).execute()

    return {"deleted_count": len(session_ids)}


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


@router.get(
    "/sessions/{session_id}/answers",
    summary="세션 질문/답변 목록 조회",
)
async def get_session_answers(session_id: str):
    sb = get_supabase()
    res = sb.table("question_answers") \
        .select("*") \
        .eq("session_id", session_id) \
        .order("created_at", desc=False) \
        .execute()
    return res.data or []
