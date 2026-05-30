import asyncio
import json
import uuid

from app.core.redis_client import SessionRedis
from app.core.supabase_client import get_supabase
from app.schemas.session import SessionState
from app.services.report_service import ReportService
from app.schemas.report import (
    ReportGenerationInput,
    RecoveryMetricsInput,
    UserPatternInput,
    SpeechMetricsSnapshot,
)


class SessionService:

    async def create_session(self, config: dict) -> str:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        sr = SessionRedis(session_id)
        await sr.set_state(SessionState.READY)

        # config 전체를 Redis에 보관 (세션 종료 시 DB 저장에 사용)
        await sr.r.set(f"session:{session_id}:config", json.dumps(config))

        # presentation_histories에 초기 행 INSERT
        sb = get_supabase()
        sb.table("presentation_histories").insert({
            "user_id":            config.get("user_id", 1),
            "session_id":         session_id,
            "title":              config.get("title"),
            "presentation_type":  config.get("presentation_type"),
            "audience_type":      config.get("audience_type"),
            "duration_seconds":   config.get("duration_seconds"),
        }).execute()

        return session_id

    async def start_session(self, session_id: str):
        await SessionRedis(session_id).set_state(SessionState.RUNNING)

    async def end_session(self, session_id: str):
        sr = SessionRedis(session_id)
        current_state = await sr.get_state()
        if current_state == SessionState.FINISHED:
            return
        await sr.set_state(SessionState.FINISHED)

        try:
            print(f"[리포트] 생성 시작: {session_id}")
            metrics = await sr.get_metrics()

            # 인터럽트 로그 수집
            interrupt_raw = await sr.r.get(f"session:{session_id}:interrupt_log")
            interrupt_list = json.loads(interrupt_raw) if interrupt_raw else []

            snapshot = SpeechMetricsSnapshot(
                recent_wpm=metrics.get("current_wpm", 0),
                average_wpm=metrics.get("current_wpm", 0),
                filler_count=metrics.get("filler_count_recent", 0),
                silence_duration=metrics.get("silence_ms", 0),
                hesitation_score=0.0,
                stress_score=metrics.get("stress_score", 0),
            )
            silence_count = metrics.get("silence_count", 0)

            report_input = ReportGenerationInput(
                speech_metrics=[snapshot],
                recovery_metrics=RecoveryMetricsInput(
                    wpm_recovery_speed_score=50.0,
                    filler_reduction_score=50.0,
                    silence_reduction_score=50.0,
                ),
                user_pattern=UserPatternInput(),
            )

            result = await asyncio.to_thread(ReportService().generate_report, report_input)
            print(f"[리포트] 완료. overall_score={result.overall_score}")

            # presentation_histories UPDATE (단일 테이블)
            sb = get_supabase()
            sb.table("presentation_histories").update({
                "avg_wpm":        result.summary.avg_wpm,
                "filler_count":   result.summary.filler_count,
                "silence_count":  silence_count,
                "interrupt_count": len(interrupt_list),
                "recovery_score": result.recovery_score,
                "overall_score":  result.overall_score,
                "strengths":      json.dumps(result.strengths,    ensure_ascii=False),
                "weaknesses":     json.dumps(result.weaknesses,   ensure_ascii=False),
                "feedback":       json.dumps(result.improvements, ensure_ascii=False),
                "curriculum_next": result.curriculum_next,
                "interrupts":     json.dumps(interrupt_list,      ensure_ascii=False),
            }).eq("session_id", session_id).execute()

            print(f"[리포트] Supabase 저장 완료: {session_id}")

            # 프론트에 저장 완료 알림 (WS가 아직 열려있을 때만)
            from app.core.websocket_manager import ws_manager
            try:
                await ws_manager.broadcast(session_id, {
                    "type": "report_saved",
                    "overall_score": result.overall_score,
                })
            except Exception:
                pass  # WS 이미 끊긴 경우 무시

        except Exception as e:
            import traceback
            print(f"[리포트 생성 에러] {type(e).__name__}: {e}")
            traceback.print_exc()

        await sr.delete_all()

    async def cancel_session(self, session_id: str):
        sr = SessionRedis(session_id)
        current_state = await sr.get_state()
        if current_state == SessionState.CANCELLED:
            return
        await sr.set_state(SessionState.CANCELLED)

        # 타이밍상 end_session()이 먼저 실행돼 FINISHED 상태가 됐어도
        # 명시적 취소이므로 DB 기록은 무조건 삭제한다
        sb = get_supabase()
        try:
            sb.table("scripts").delete().eq("session_id", session_id).execute()
        except Exception as e:
            print(f"[취소] scripts 삭제 실패: {e}")
        try:
            sb.table("presentation_histories").delete().eq("session_id", session_id).execute()
        except Exception as e:
            print(f"[취소] presentation_histories 삭제 실패: {e}")

        await sr.delete_all()

    async def transition_state(self, session_id: str, new_state: SessionState):
        await SessionRedis(session_id).set_state(new_state)

    async def get_state(self, session_id: str) -> str | None:
        return await SessionRedis(session_id).get_state()