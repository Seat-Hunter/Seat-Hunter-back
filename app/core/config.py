# app/core/config.py
# 프로젝트 환경변수 설정 파일

from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://localhost:6379"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # PostgreSQL (Supabase DB 연결용)
    database_url: str = ""

    # API Keys
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    gemini_api_key: str = ""

    # JWT 토큰 서명/검증용 비밀 키
    secret_key: str = ""

    # CORS
    # 예:
    # CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    class Config:
        env_file = ".env"


settings = Settings()