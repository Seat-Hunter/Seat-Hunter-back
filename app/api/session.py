from fastapi import APIRouter
from app.schemas.session import SessionCreateRequest, SessionCreateResponse, SessionState
from app.services.session_service import SessionService

router = APIRouter()
service = SessionService()


@router.post(
    "/sessions",
    response_model=SessionCreateResponse,
    summary="세션 생성",
    description=(
        "발표 시뮬레이션 세션을 생성합니다. "
        "생성 후 반환된 `session_id`로 WebSocket에 연결하고 `/start`를 호출하세요."
    ),
    status_code=201,
)
async def create_session(body: SessionCreateRequest):
    session_id = await service.create_session(body.model_dump())
    return SessionCreateResponse(session_id=session_id, state=SessionState.READY)


@router.post(
    "/sessions/{session_id}/start",
    summary="세션 시작",
    description="세션 상태를 `READY` → `RUNNING`으로 전환합니다. WebSocket 연결 후 호출하세요.",
)
async def start_session(session_id: str):
    await service.start_session(session_id)
    return {"session_id": session_id, "state": SessionState.RUNNING}


@router.post(
    "/sessions/{session_id}/end",
    summary="세션 종료",
    description=(
        "세션을 종료하고 분석 리포트를 자동 생성합니다. "
        "종료 후 `/report` 엔드포인트로 결과를 조회할 수 있습니다."
    ),
)
async def end_session(session_id: str):
    await service.end_session(session_id)
    return {"session_id": session_id, "state": SessionState.FINISHED}