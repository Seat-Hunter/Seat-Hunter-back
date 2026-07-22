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
    AnswerEvaluationLogItem,
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
        print(f"[end_session] 호출됨. session_id={session_id}, current_state={current_state}")

        if current_state == SessionState.FINISHED:
            print(f"[end_session] 이미 FINISHED 상태 → 스킵")
            return
        await sr.set_state(SessionState.FINISHED)

        # 리포트 생성 실패 시 폴백 저장에 쓰는 기본값 (try 초반에 실제 값으로 대체됨)
        metrics: dict = {}
        interrupt_list: list = []
        actual_avg_wpm: float = 0.0
        silence_count: int = 0

        try:
            print(f"[리포트] 생성 시작: {session_id}")
            metrics = await sr.get_metrics()
            print(f"[리포트] metrics={metrics}")

            interrupt_raw = await sr.r.get(f"session:{session_id}:interrupt_log")
            interrupt_list = json.loads(interrupt_raw) if interrupt_raw else []

            answer_raw = await sr.r.get(f"session:{session_id}:answer_log")
            answer_log = json.loads(answer_raw) if answer_raw else []

            config_raw = await sr.r.get(f"session:{session_id}:config")
            config = json.loads(config_raw) if config_raw else {}
            script_text = config.get("script_text") or None

            # Supabase scripts 테이블에서 전체 발화 텍스트와 실제 WPM 계산
            sb = get_supabase()

            # Redis answer_log가 비어 있으면 Supabase question_answers에서 조회
            if not answer_log:
                try:
                    answers_res = sb.table("question_answers") \
                        .select("question_text, answer_text, answer_score, follow_up_needed") \
                        .eq("session_id", session_id) \
                        .order("created_at") \
                        .execute()
                    answer_log = [
                        {
                            "question_text": row.get("question_text", ""),
                            "user_answer": row.get("answer_text", ""),
                            "answer_score": row.get("answer_score", 0),
                            "follow_up_needed": row.get("follow_up_needed", False),
                            "audience_reaction": "",
                        }
                        for row in (answers_res.data or [])
                        if row.get("answer_text")
                    ]
                except Exception as e:
                    print(f"[리포트] question_answers 조회 실패: {e}")

            scripts_res = sb.table("scripts") \
                .select("transcript, start_ms, end_ms") \
                .eq("session_id", session_id) \
                .order("segment_index") \
                .execute()

            if scripts_res.data:
                transcript_text = " ".join(s["transcript"] for s in scripts_res.data)
                total_words = sum(len(s["transcript"].split()) for s in scripts_res.data)
                first_start = scripts_res.data[0].get("start_ms") or 0
                last_end = scripts_res.data[-1].get("end_ms") or 0
                if last_end > first_start + 1000:
                    duration_min = (last_end - first_start) / 60000
                    calculated_avg_wpm = round(total_words / duration_min, 1) if duration_min > 0 else 0.0
                elif config.get("duration_seconds", 0) > 0:
                    duration_min = config["duration_seconds"] / 60
                    calculated_avg_wpm = round(total_words / duration_min, 1)
                else:
                    calculated_avg_wpm = 0.0
            else:
                recent_transcript_list = await sr.get_recent_transcript()
                transcript_text = " ".join(recent_transcript_list) if recent_transcript_list else ""
                calculated_avg_wpm = 0.0

            # Redis WPM이 0이면 scripts 기반 계산값 사용
            redis_avg_wpm = metrics.get("average_wpm", metrics.get("current_wpm", 0))
            actual_avg_wpm = redis_avg_wpm if redis_avg_wpm > 0 else calculated_avg_wpm

            snapshot = SpeechMetricsSnapshot(
                recent_wpm=actual_avg_wpm,
                average_wpm=actual_avg_wpm,
                filler_count=metrics.get("filler_count_recent", 0),
                silence_duration=metrics.get("silence_ms", 0),
                hesitation_score=0.0,
                stress_score=metrics.get("stress_score", 0),
            )
            silence_count = metrics.get("silence_count", 0)

            # 대응 점수(response_score) 폴백 계산용 입력 (LLM 평가 실패 시에만 사용)
            wpm = actual_avg_wpm
            if 100 <= wpm <= 160:
                wpm_recovery = 80.0
            elif 80 <= wpm < 100 or 160 < wpm <= 190:
                wpm_recovery = 60.0
            elif wpm > 0:
                wpm_recovery = 40.0
            else:
                wpm_recovery = 50.0
            if answer_log:
                avg_ans = sum(item.get("answer_score", 50) for item in answer_log) / len(answer_log)
                wpm_recovery = wpm_recovery * 0.5 + avg_ans * 0.5

            filler_total = metrics.get("filler_count_recent", 0)
            filler_reduction = max(10.0, 100.0 - filler_total * 8)

            silence_ms = metrics.get("silence_ms", 0)
            if silence_ms == 0:
                silence_reduction = 90.0
            elif silence_ms < 2000:
                silence_reduction = 70.0
            elif silence_ms < 5000:
                silence_reduction = 50.0
            else:
                silence_reduction = 30.0

            answer_eval_log = [
                AnswerEvaluationLogItem(
                    question_text=item.get("question_text", ""),
                    user_answer=item.get("user_answer", ""),
                    answer_score=item.get("answer_score", 0),
                    follow_up_needed=item.get("follow_up_needed", False),
                    audience_reaction=item.get("audience_reaction", ""),
                )
                for item in answer_log
            ]

            report_input = ReportGenerationInput(
                speech_metrics=[snapshot],
                recovery_metrics=RecoveryMetricsInput(
                    wpm_recovery_speed_score=wpm_recovery,
                    filler_reduction_score=filler_reduction,
                    silence_reduction_score=silence_reduction,
                ),
                user_pattern=UserPatternInput(),
                answer_evaluation_log=answer_eval_log,
                transcript_text=transcript_text,
                script_text=script_text,
            )

            result = await asyncio.to_thread(ReportService().generate_report, report_input)
            print(f"[리포트] 생성 완료. overall_score={result.overall_score}")

            # presentation_histories UPDATE (단일 테이블)
            # presentation_histories UPDATE (단일 테이블)
            sb = get_supabase()
            
            # 💡 [복구 완료]: 지워졌던 update_res = 변수 선언부를 다시 앞에 붙여주었습니다.
            update_res = sb.table("presentation_histories").update({
                "avg_wpm":         result.summary.avg_wpm,
                "filler_count":   result.summary.filler_count,
                "silence_count":  silence_count,
                "interrupt_count": len(interrupt_list),
                "recovery_score": result.response_score if result.response_score is not None else 0,
                "overall_score":  result.overall_score,
                "strengths":      json.dumps(result.strengths,    ensure_ascii=False),
                "weaknesses":     json.dumps(result.weaknesses,   ensure_ascii=False),
                "feedback":       json.dumps(result.improvements, ensure_ascii=False),
                "criteria_scores": json.dumps(
                    [item.model_dump() for item in result.criteria_scores], ensure_ascii=False
                ),
                "curriculum_next": result.curriculum_next,
                "interrupts":     json.dumps(interrupt_list,      ensure_ascii=False),
            }).eq("session_id", session_id).execute()

            if update_res.data:
                print(f"[리포트] Supabase 저장 완료: {session_id}")
            else:
                print(f"[리포트] Supabase UPDATE 매칭 행 없음 — session_id={session_id}가 DB에 없을 수 있습니다.")

        except Exception as e:
            import traceback
            print(f"[리포트 생성 에러] {type(e).__name__}: {e}")
            traceback.print_exc()

            # LLM 리포트 생성이 실패해도 기본 리포트를 저장한다.
            # (overall_score가 계속 0/NULL이면 프론트 리포트 조회가 영영 404
            #  → "피드백을 불러오지 못했습니다"가 되는 것을 방지)
            try:
                sb = get_supabase()
                sb.table("presentation_histories").update({
                    "avg_wpm":         actual_avg_wpm,
                    "filler_count":    metrics.get("filler_count_recent", 0),
                    "silence_count":   silence_count,
                    "interrupt_count": len(interrupt_list),
                    "recovery_score":  0,
                    "overall_score":   50,
                    "strengths":       json.dumps([], ensure_ascii=False),
                    "weaknesses":      json.dumps([], ensure_ascii=False),
                    "feedback":        json.dumps(
                        ["AI 피드백 생성 중 오류가 발생해 기본 리포트로 대체되었습니다."],
                        ensure_ascii=False,
                    ),
                    "criteria_scores": json.dumps([], ensure_ascii=False),
                    "curriculum_next": "",
                    "interrupts":      json.dumps(interrupt_list, ensure_ascii=False),
                }).eq("session_id", session_id).execute()
                print(f"[리포트] 기본 리포트로 대체 저장 완료: {session_id}")
            except Exception as e2:
                print(f"[리포트] 기본 리포트 저장도 실패: {e2}")

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