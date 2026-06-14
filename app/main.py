from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import session, report, health
from app.ws import session_ws
from app.core.config import settings
from app.api.auth import router as auth_router

app = FastAPI(
    title="SpeechLab — Speech Simulation API",
    version="0.2.0",
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
    allow_origins=["*"],  # 👈 기존 settings.cors_origins_list 대신 ["*"]로 변경!
    allow_credentials=True,  # 만약 "*" 설정 시 에러가 나면 allow_credentials=False로 바꾸거나 방법 2를 쓰세요.
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router,  prefix="/api/v1", tags=["Session"])
app.include_router(report.router,   prefix="/api/v1", tags=["Report"])
app.include_router(health.router,   tags=["Health"])
app.include_router(session_ws.router, tags=["WebSocket"])
app.include_router(auth_router)

app.mount("/", StaticFiles(directory=".", html=True), name="static")
