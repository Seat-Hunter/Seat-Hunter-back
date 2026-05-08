import asyncio
import uuid
from app.core.redis_client import SessionRedis
from app.schemas.session import SessionState
from app.repositories import session_repository, report_repository
from app.services.report_service import ReportService
from app.schemas.report import (
    ReportGenerationInput,
    RecoveryMetricsInput,
    UserPatternInput,
)


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
        current_state = await sr.get_state()
        if current_state == SessionState.FINISHED:
            return
        await sr.set_state(SessionState.FINISHED)
        await session_repository.update_session_ended(session_id)

        # 리포트 자동 생성
        try:
            print(f"[리포트] 생성 시작: {session_id}")
            metrics = await sr.get_metrics()
            print(f"[리포트] metrics: {metrics}")
            report_service = ReportService()

            from app.schemas.report import SpeechMetricsSnapshot
            snapshot = SpeechMetricsSnapshot(
                recent_wpm=metrics.get("current_wpm", 0),
                average_wpm=metrics.get("current_wpm", 0),
                filler_count=metrics.get("filler_count_recent", 0),
                silence_duration=metrics.get("silence_ms", 0),
                hesitation_score=0.0,
                stress_score=metrics.get("stress_score", 0),
            )

            report_input = ReportGenerationInput(
                speech_metrics=[snapshot],
                recovery_metrics=RecoveryMetricsInput(
                    wpm_recovery_speed_score=50.0,
                    filler_reduction_score=50.0,
                    silence_reduction_score=50.0,
                ),
                user_pattern=UserPatternInput(),
            )

            print(f"[리포트] generate_report 호출 중...")
            result = await asyncio.to_thread(report_service.generate_report, report_input)
            print(f"[리포트] generate_report 완료. overall_score={result.overall_score}")

            await report_repository.insert_report(session_id, {
                "avg_wpm": result.summary.avg_wpm,
                "filler_count": result.summary.filler_count,
                "interrupt_count": result.summary.interrupt_count,
                "recovery_score": result.recovery_score,
                "overall_score": result.overall_score,
                "strengths_json": result.strengths,
                "weaknesses_json": result.weaknesses,
                "improvements_json": result.improvements,
                "curriculum_next": result.curriculum_next,
            })
            print(f"[리포트] Supabase 저장 완료: {session_id}")
        except Exception as e:
            import traceback
            print(f"[리포트 생성 에러] {type(e).__name__}: {e}")
            traceback.print_exc()

        await sr.delete_all()

    async def transition_state(self, session_id: str, new_state: SessionState):
        await SessionRedis(session_id).set_state(new_state)

    async def get_state(self, session_id: str) -> str | None:
        return await SessionRedis(session_id).get_state()