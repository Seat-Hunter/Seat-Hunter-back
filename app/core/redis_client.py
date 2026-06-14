import json
import redis.asyncio as redis
from app.core.config import settings

_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)

def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


class SessionRedis:
    def __init__(self, session_id: str):
        self.sid = session_id
        self.r = get_redis()

    async def set_state(self, state: str):
        await self.r.set(f"session:{self.sid}:state", state)

    async def get_state(self) -> str | None:
        return await self.r.get(f"session:{self.sid}:state")

    async def set_metrics(self, metrics: dict):
        await self.r.set(f"session:{self.sid}:metrics", json.dumps(metrics))

    async def get_metrics(self) -> dict:
        raw = await self.r.get(f"session:{self.sid}:metrics")
        return json.loads(raw) if raw else {}

    async def push_transcript(self, text: str, max_sentences: int = 10):
        key = f"session:{self.sid}:recent_transcript"
        await self.r.rpush(key, text)
        await self.r.ltrim(key, -max_sentences, -1)

    async def get_recent_transcript(self) -> list[str]:
        return await self.r.lrange(f"session:{self.sid}:recent_transcript", 0, -1)

    async def set_last_interrupt_at(self, ts: float):
        await self.r.set(f"session:{self.sid}:last_interrupt_at", ts)

    async def get_last_interrupt_at(self) -> float | None:
        val = await self.r.get(f"session:{self.sid}:last_interrupt_at")
        return float(val) if val else None

    async def set_tts_playing(self, flag: bool):
        await self.r.set(f"session:{self.sid}:is_tts_playing", int(flag))

    async def get_tts_playing(self) -> bool:
        val = await self.r.get(f"session:{self.sid}:is_tts_playing")
        return bool(int(val)) if val else False

    async def set_user_speaking(self, flag: bool):
        await self.r.set(f"session:{self.sid}:is_user_speaking", int(flag))

    async def get_user_speaking(self) -> bool:
        val = await self.r.get(f"session:{self.sid}:is_user_speaking")
        return bool(int(val)) if val else False

    async def set_current_question(self, question: dict):
        await self.r.set(f"session:{self.sid}:current_question", json.dumps(question))

    async def get_current_question(self) -> dict | None:
        raw = await self.r.get(f"session:{self.sid}:current_question")
        return json.loads(raw) if raw else None

    async def delete_all(self):
        keys = await self.r.keys(f"session:{self.sid}:*")
        if keys:
            await self.r.delete(*keys)