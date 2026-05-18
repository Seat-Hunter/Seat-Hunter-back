from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import session, report, health
from app.ws import session_ws
from app.core.config import settings
from app.api.auth import router as auth_router

# DB 테이블 생성용 import
from app.db.database import Base, engine
from app.models.user import User


# User 모델 기준으로 users 테이블 생성
# 이미 테이블이 있으면 새로 만들지 않고 넘어감
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="Seat Hunter — Speech Simulation API",
    version="0.1.0",
    description=(
        "AI 발표 트레이닝 시뮬레이터 백엔드.\n\n"
        "REST API로 세션을 생성/제어하고, WebSocket(`/ws/sessions/{session_id}`)으로 "
        "실시간 음성 분석·인터럽트 질문·TTS 응답을 주고받습니다.\n\n"
        "**Swagger UI**: `/docs`  |  **ReDoc**: `/redoc`"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# app/main.py 파일 내부

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router, prefix="/api/v1", tags=["Session"])
app.include_router(report.router, prefix="/api/v1", tags=["Report"])
app.include_router(health.router, tags=["Health"])
app.include_router(session_ws.router, tags=["WebSocket"])
app.include_router(auth_router)

app.mount("/", StaticFiles(directory=".", html=True), name="static")