from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://localhost:6379"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # External API Keys
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    gemini_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_question_model: str = "gpt-5-mini"

    # Auth
    secret_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


settings = Settings()