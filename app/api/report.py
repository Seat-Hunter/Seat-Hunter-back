from fastapi import APIRouter, HTTPException
from app.repositories import report_repository, session_repository, interrupt_repository

router = APIRouter()


@router.get(
    "/sessions/{session_id}/report",
    summary="세션 리포트 조회",
    description=(
        "세션 종료 후 생성된 분석 리포트를 반환합니다. "
        "세션이 아직 종료되지 않았거나 리포트 생성 전이면 404를 반환합니다."
    ),
    responses={404: {"description": "리포트 없음"}},
)
async def get_report(session_id: str):
    report = await report_repository.get_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="리포트 없음. 세션이 아직 종료되지 않았거나 생성 전입니다.")
    return report


@router.get(
    "/users/{user_id}/sessions",
    summary="유저 세션 목록 조회",
    description="특정 유저의 전체 발표 세션 이력을 반환합니다.",
)
async def get_user_sessions(user_id: int):
    sessions = await session_repository.get_user_sessions(user_id)
    return sessions


@router.get(
    "/sessions/{session_id}/interrupts",
    summary="세션 인터럽트 목록 조회",
    description="세션 중 발생한 모든 인터럽트 질문 이력을 반환합니다.",
)
async def get_session_interrupts(session_id: str):
    interrupts = await interrupt_repository.get_session_interrupts(session_id)
    return interrupts