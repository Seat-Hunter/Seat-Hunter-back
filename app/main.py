from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import session, report, health
from app.ws import session_ws
from fastapi.staticfiles import StaticFiles
from app.core.config import settings

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

# allow_origins=["*"] 과 allow_credentials=True 를 동시에 사용하면
# 브라우저가 CORS preflight를 거부합니다. 명시적 오리진 목록을 사용합니다.
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

app.mount("/", StaticFiles(directory=".", html=True), name="static")