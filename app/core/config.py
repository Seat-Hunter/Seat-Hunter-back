from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    supabase_url: str = ""
    supabase_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    gemini_api_key: str = ""

    # CORS: 쉼표로 구분된 허용 오리진 목록
    # 예) CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    class Config:
        env_file = ".env"


settings = Settings()