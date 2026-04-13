import uuid
from app.core.redis_client import SessionRedis
from app.schemas.session import SessionState
from app.repositories import session_repository


class SessionService:

    async def create_session(self, config: dict) -> str:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        sr = SessionRedis(session_id)
        await sr.set_state(SessionState.READY)
        await session_repository.insert_session(session_id, config)
        return session_id

    async def start_session(self, session_id: str):
        await SessionRedis(session_id).set_state(SessionState.RUNNING)
        await session_repository.update_session_started(session_id)

    async def end_session(self, session_id: str):
        sr = SessionRedis(session_id)
        await sr.set_state(SessionState.FINISHED)
        await session_repository.update_session_ended(session_id)
        await sr.delete_all()  # Redis 정리

    async def transition_state(self, session_id: str, new_state: SessionState):
        await SessionRedis(session_id).set_state(new_state)

    async def get_state(self, session_id: str) -> str | None:
        return await SessionRedis(session_id).get_state()