from fastapi import APIRouter, HTTPException
from app.repositories import report_repository, session_repository, interrupt_repository

router = APIRouter()


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str):
    report = await report_repository.get_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="리포트 없음. 세션이 아직 종료되지 않았거나 생성 전입니다.")
    return report


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(user_id: int):
    sessions = await session_repository.get_user_sessions(user_id)
    return sessions


@router.get("/sessions/{session_id}/interrupts")
async def get_session_interrupts(session_id: str):
    interrupts = await interrupt_repository.get_session_interrupts(session_id)
    return interrupts