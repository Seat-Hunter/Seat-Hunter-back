from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import session, report, health
from app.ws import session_ws

app = FastAPI(title="Speech Simulation Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router, prefix="/api/v1")
app.include_router(report.router, prefix="/api/v1")
app.include_router(health.router)
app.include_router(session_ws.router)