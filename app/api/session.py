from fastapi import APIRouter
from app.schemas.session import SessionCreateRequest, SessionCreateResponse, SessionState
from app.services.session_service import SessionService

router = APIRouter()
service = SessionService()

@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(body: SessionCreateRequest):
    session_id = await service.create_session(body.model_dump())
    return SessionCreateResponse(session_id=session_id, state=SessionState.READY)

@router.post("/sessions/{session_id}/start")
async def start_session(session_id: str):
    await service.start_session(session_id)
    return {"session_id": session_id, "state": SessionState.RUNNING}

@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    await service.end_session(session_id)
    return {"session_id": session_id, "state": SessionState.FINISHED}