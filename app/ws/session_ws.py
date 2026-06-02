import asyncio
import json
import base64
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket_manager import ws_manager
from app.core.redis_client import SessionRedis
from app.services.stt_service import STTAggregator
from app.services.session_service import SessionService
from app.services.tts_service import text_to_speech_bytes
from app.services.speech_analysis_service import SpeechAnalysisService
from app.services.interrupt_service import InterruptService
from app.services.question_service import QuestionService
from app.services.audience_service import AudienceService
from app.schemas.ws_message import make_session_state, make_live_metrics
from app.schemas.session import SessionState
from app.schemas.speech_analysis import SpeechAnalysisInput
from app.schemas.interrupt import (
    InterruptDecisionInput,
    SpeechMetricsInput,
    ContextStateInput,
)
from app.schemas.question import (
    QuestionGenerationInput,
    AnswerEvaluationInput,
)

router = APIRouter()
session_service = SessionService()


def _generate_feedback(analysis) -> str | None:
    if analysis.recent_wpm > 170:
        return "말속도가 너무 빠릅니다. 천천히 말씀해보세요."
    if 0 < analysis.recent_wpm < 60:
        return "말속도가 너무 느립니다. 조금 더 빠르게 말씀해보세요."
    if analysis.filler_count_segment >= 3:
        return "필러 단어가 늘고 있습니다. 잠깐 멈추고 정리 후 말씀해보세요."
    if analysis.stress_score > 0.85:
        return "긴장이 감지됩니다. 천천히 호흡하고 말씀해보세요."
    if analysis.current_silence_ms > 4000:
        return "침묵이 길어지고 있습니다. 다음 내용을 이어가보세요."
    return None


def _safe_session_state_name(state) -> str | None:
    if state is None:
        return None

    if isinstance(state, SessionState):
        return state.value

    return str(state)


def _is_state(state, target: SessionState) -> bool:
    return _safe_session_state_name(state) == target.value


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)

    sr = SessionRedis(session_id)
    stt = STTAggregator(session_id)
    speech_analyzer = SpeechAnalysisService()
    interrupt_service = InterruptService()
    question_service = QuestionService()
    audience_service = AudienceService()

    previous_questions: list[str] = []

    current_question: str | None = None
    current_question_id: str | None = None
    parent_question_id: str | None = None

    answer_buffer: list[str] = []
    follow_up_count: int = 0

    answer_timer_task: asyncio.Task | None = None
    no_answer_timer_task: asyncio.Task | None = None

    answer_started: bool = False
    answer_started_at: float | None = None
    last_answer_at: float | None = None

    MAX_FOLLOW_UPS = 2

    # 마지막 답변 조각 이후 이 시간 동안 추가 답변이 없으면 평가
    ANSWER_SILENCE_SEC = 3.0

    # 질문 후 사용자가 아예 답변하지 않을 때 기다리는 최대 시간
    NO_ANSWER_TIMEOUT_SEC = 12.0

    deepgram_started = False
    websocket_closed = False

    # ============================================================
    # 안전 종료 유틸
    # ============================================================

    async def safe_close_stt(reason: str = ""):
        nonlocal deepgram_started

        if not deepgram_started:
            return

        try:
            print(f"[STT] Deepgram 연결 종료 시도: {reason}")
            await stt.close()
        except Exception as e:
            print(f"[STT 종료 무시 가능한 에러] {e}")
        finally:
            deepgram_started = False

    async def safe_broadcast(payload: dict):
        if websocket_closed:
            return

        try:
            await ws_manager.broadcast(session_id, payload)
        except Exception as e:
            print(f"[WS broadcast 에러 무시] {e}")

    async def safe_set_tts_playing(value: bool):
        try:
            await sr.set_tts_playing(value)
        except Exception as e:
            print(f"[Redis] tts_playing 설정 실패: {e}")

    # ============================================================
    # 질문 흐름 중심 디버그 로그
    # ============================================================

    def log_new_question(question_id: str, question_text: str):
        print("\n========== [질문 흐름] 새 질문 ==========")
        print(f"질문 ID: {question_id}")
        print(f"질문 내용: {question_text}")
        print(f"꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("========================================\n")

    def log_answer_started():
        print("\n========== [답변 시작] ==========")
        print(f"질문 ID: {current_question_id}")
        print(f"질문 내용: {current_question}")
        print(f"꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("================================\n")

    def log_answer_segment(text: str):
        print("\n========== [답변 조각 추가] ==========")
        print(f"질문 ID: {current_question_id}")
        print(f"질문 내용: {current_question}")
        print(f"추가된 답변 조각: {text}")
        print(f"현재 누적 답변: {' '.join(answer_buffer)}")
        print(f"꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("====================================\n")

    def log_answer_received(
        question_id: str | None,
        question_text: str | None,
        user_answer: str,
    ):
        print("\n========== [답변 수신] ==========")
        print(f"질문 ID: {question_id}")
        print(f"질문 내용: {question_text}")
        print(f"사용자 답변: {user_answer}")
        print("================================\n")

    def log_answer_evaluation(
        question_id: str | None,
        question_text: str | None,
        user_answer: str,
        eval_result,
    ):
        print("\n========== [답변 평가] ==========")
        print(f"질문 ID: {question_id}")
        print(f"질문 내용: {question_text}")
        print(f"사용자 답변: {user_answer}")
        print(f"점수: {eval_result.answer_score}")
        print(f"평가 이유: {eval_result.evaluation_reason}")
        print(f"청중 반응: {eval_result.audience_reaction}")
        print(f"꼬리질문 필요 여부: {eval_result.follow_up_needed}")
        print(f"다음 꼬리질문: {eval_result.follow_up_question}")
        print(f"현재 꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("================================\n")

    def log_follow_up(question_id: str, follow_up_question: str):
        print(f"\n========== [꼬리질문 {follow_up_count}회차] ==========")
        print(f"부모 질문 ID: {parent_question_id}")
        print(f"꼬리질문 ID: {question_id}")
        print(f"꼬리질문 내용: {follow_up_question}")
        print(f"꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("====================================\n")

    def log_follow_up_finished(reason: str):
        print("\n========== [질문 흐름 종료] ==========")
        print(f"종료 이유: {reason}")
        print(f"마지막 질문 ID: {current_question_id}")
        print(f"마지막 질문 내용: {current_question}")
        print(f"최종 꼬리질문 횟수: {follow_up_count}/{MAX_FOLLOW_UPS}")
        print("발표로 복귀합니다.")
        print("====================================\n")

    def log_tts_fallback(question_id: str, question_text: str, error_message: str):
        print("\n========== [TTS 실패 - 텍스트 질문 진행] ==========")
        print(f"질문 ID: {question_id}")
        print(f"질문 내용: {question_text}")
        print(f"오류 내용: {error_message}")
        print("음성 없이 텍스트 질문으로 답변 상태에 진입합니다.")
        print("=================================================\n")

    # ============================================================
    # 상태 전환 함수
    # ============================================================

    async def cancel_answer_timers():
        nonlocal answer_timer_task
        nonlocal no_answer_timer_task

        if answer_timer_task and not answer_timer_task.done():
            answer_timer_task.cancel()
        answer_timer_task = None

        if no_answer_timer_task and not no_answer_timer_task.done():
            no_answer_timer_task.cancel()
        no_answer_timer_task = None

    async def resume_presentation():
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal follow_up_count
        nonlocal answer_buffer
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at

        current_question = None
        current_question_id = None
        parent_question_id = None
        follow_up_count = 0

        answer_buffer.clear()
        answer_started = False
        answer_started_at = None
        last_answer_at = None

        await cancel_answer_timers()

        await safe_set_tts_playing(False)
        await safe_broadcast({"type": "question_resolved"})

        try:
            await sr.set_state(SessionState.RUNNING)
            await safe_broadcast(make_session_state(SessionState.RUNNING))
        except Exception as e:
            print(f"[상태 복귀 에러] {e}")

    async def start_answer_timer():
        nonlocal answer_timer_task

        if answer_timer_task and not answer_timer_task.done():
            answer_timer_task.cancel()

        answer_timer_task = asyncio.create_task(evaluate_and_maybe_follow_up())

    async def start_no_answer_timer():
        nonlocal no_answer_timer_task

        if no_answer_timer_task and not no_answer_timer_task.done():
            no_answer_timer_task.cancel()

        no_answer_timer_task = asyncio.create_task(handle_no_answer_timeout())

    async def handle_no_answer_timeout():
        try:
            await asyncio.sleep(NO_ANSWER_TIMEOUT_SEC)
        except asyncio.CancelledError:
            return

        current_state = await sr.get_state()

        if _is_state(current_state, SessionState.ANSWERING) and not answer_started:
            print("\n========== [답변 없음] ==========")
            print(f"질문 ID: {current_question_id}")
            print(f"질문 내용: {current_question}")
            print(f"{NO_ANSWER_TIMEOUT_SEC}초 동안 답변이 없어 발표로 복귀합니다.")
            print("===============================\n")

            await safe_broadcast({
                "type": "answer_timeout",
                "question_id": current_question_id,
                "parent_question_id": parent_question_id,
                "question_text": current_question,
                "message": "답변이 없어 발표로 복귀합니다.",
            })

            log_follow_up_finished("답변 없음")
            await resume_presentation()

    async def enter_answering_state():
        """
        답변 상태로만 진입한다.
        여기서 답변 평가 타이머를 시작하면 안 된다.
        실제 답변 final transcript가 들어온 뒤 start_answer_timer()를 시작한다.
        """
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at
        nonlocal answer_buffer

        await safe_set_tts_playing(False)

        answer_buffer.clear()
        answer_started = False
        answer_started_at = None
        last_answer_at = None

        try:
            await sr.set_state(SessionState.ANSWERING)
            await safe_broadcast(make_session_state(SessionState.ANSWERING))
        except Exception as e:
            print(f"[ANSWERING 상태 전환 에러] {e}")

        await start_no_answer_timer()

    # ============================================================
    # TTS 생성 + 실패 fallback
    # ============================================================

    async def send_question_tts_or_fallback(
        *,
        question_id: str,
        question_text: str,
        pressure_level: str = "medium",
        is_follow_up: bool = False,
        follow_up_count_value: int = 0,
    ) -> bool:
        await safe_set_tts_playing(True)

        try:
            await sr.set_state(SessionState.INTERRUPTED)
            await safe_broadcast(make_session_state(SessionState.INTERRUPTED))
        except Exception as e:
            print(f"[INTERRUPTED 상태 전환 에러] {e}")

        try:
            audio_bytes = await asyncio.wait_for(
                text_to_speech_bytes(question_text, pressure_level),
                timeout=10,
            )

            if not audio_bytes:
                raise RuntimeError("TTS 결과 audio_bytes가 비어 있습니다.")

            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            await safe_broadcast({
                "type": "tts_audio",
                "question_id": question_id,
                "parent_question_id": parent_question_id,
                "question_text": question_text,
                "audio_base64": audio_b64,
                "format": "mp3",
                "is_follow_up": is_follow_up,
                "follow_up_count": follow_up_count_value,
                "max_follow_ups": MAX_FOLLOW_UPS,
            })

            return True

        except asyncio.TimeoutError:
            error_message = "TTS 생성 시간 초과"

        except Exception as e:
            error_message = str(e)

        log_tts_fallback(question_id, question_text, error_message)

        await safe_set_tts_playing(False)

        await safe_broadcast({
            "type": "tts_error",
            "question_id": question_id,
            "parent_question_id": parent_question_id,
            "question_text": question_text,
            "message": "TTS 생성에 실패해서 텍스트 질문으로 진행합니다.",
            "is_follow_up": is_follow_up,
            "follow_up_count": follow_up_count_value,
            "max_follow_ups": MAX_FOLLOW_UPS,
        })

        await enter_answering_state()

        return False

    # ============================================================
    # 발표 transcript 처리
    # ============================================================

    async def on_final_transcript(text: str, start_ms: int, end_ms: int):
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal follow_up_count
        nonlocal answer_buffer

        try:
            analysis = await speech_analyzer.analyze(SpeechAnalysisInput(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                is_speaking=True,
                is_interrupt=False,
            ))

            await sr.set_metrics({
                "current_wpm": analysis.recent_wpm,
                "average_wpm": analysis.average_wpm,
                "filler_count_recent": analysis.filler_count,
                "silence_ms": analysis.silence_duration,
                "silence_count": analysis.silence_count,
                "stress_score": analysis.stress_score,
            })

            await safe_broadcast(make_live_metrics(
                wpm=analysis.recent_wpm,
                filler_count=analysis.filler_count,
                silence_ms=analysis.silence_duration,
                stress_score=analysis.stress_score,
            ))

            audience_payload = audience_service.evaluate(analysis)
            await safe_broadcast(audience_payload)

            feedback = _generate_feedback(analysis)
            if feedback:
                await safe_broadcast({
                    "type": "live_feedback",
                    "message": feedback,
                })

            if await sr.get_tts_playing():
                return

            current_state = await sr.get_state()
            if _is_state(current_state, SessionState.ANSWERING):
                return

            last_interrupt = await sr.get_last_interrupt_at()
            cooldown_remaining = 0

            if last_interrupt:
                elapsed = (time.time() - last_interrupt) * 1000
                cooldown_remaining = max(0, 30000 - elapsed)

            interrupt_input = InterruptDecisionInput(
                speech_metrics=SpeechMetricsInput(
                    recent_wpm=analysis.recent_wpm,
                    average_wpm=analysis.average_wpm,
                    filler_count=analysis.filler_count,
                    silence_duration=analysis.silence_duration,
                    hesitation_score=analysis.hesitation_score,
                    stress_score=analysis.stress_score,
                ),
                context_state=ContextStateInput(
                    drift_score=0.0,
                    topic_shift_detected=False,
                ),
                interrupt_enabled=True,
                cooldown_remaining_ms=int(cooldown_remaining),
                pressure_level="medium",
            )

            decision = interrupt_service.decide(interrupt_input)
            if not decision.should_interrupt:
                return

            if not decision.should_interrupt:
                return

            await sr.set_last_interrupt_at(time.time())
            recent_transcript = await sr.get_recent_transcript()

            question_result = await question_service.generate_question_ai(
                QuestionGenerationInput(
                    current_topic=None,
                    recent_context=recent_transcript,
                    audience_type="professor",
                    presentation_type="academic",
                    pressure_level="medium",
                    previous_questions=previous_questions,
                )
            )

            previous_questions.append(question_result.question_text)

            current_question = question_result.question_text
            follow_up_count = 0

            answer_buffer.clear()

            q_id = f"q_{len(previous_questions)}"
            current_question_id = q_id
            parent_question_id = q_id

            log_new_question(q_id, current_question)

            try:
                _log_raw = await sr.r.get(f"session:{session_id}:interrupt_log")
                _log = json.loads(_log_raw) if _log_raw else []

                _log.append({
                    "question_id": q_id,
                    "parent_question_id": parent_question_id,
                    "question_text": question_result.question_text,
                    "reason": decision.reason,
                    "is_follow_up": False,
                    "follow_up_count": 0,
                    "max_follow_ups": MAX_FOLLOW_UPS,
                    "created_at": time.time(),
                })

                await sr.r.set(
                    f"session:{session_id}:interrupt_log",
                    json.dumps(_log, ensure_ascii=False)
                )
            except Exception as e:
                print(f"[질문 로그 저장 에러] {e}")

            await safe_broadcast({
                "type": "interrupt_question",
                "question_id": q_id,
                "parent_question_id": parent_question_id,
                "question_text": question_result.question_text,
                "pressure_level": "medium",
                "is_follow_up": False,
                "follow_up_count": follow_up_count,
                "max_follow_ups": MAX_FOLLOW_UPS,
            })

            await send_question_tts_or_fallback(
                question_id=q_id,
                question_text=question_result.question_text,
                pressure_level="medium",
                is_follow_up=False,
                follow_up_count_value=follow_up_count,
            )

        except Exception as e:
            print(f"[분석 파이프라인 에러] {e}")

    # ============================================================
    # 답변 수집
    # ============================================================

    async def append_answer_segment(text: str):
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at
        nonlocal no_answer_timer_task

        clean_text = text.strip()

        if not clean_text:
            return

        if not current_question or not current_question_id:
            print(f"[답변 조각 무시] 현재 질문 없음: {clean_text}")
            return

        now = time.time()

        if not answer_started:
            answer_started = True
            answer_started_at = now

            if no_answer_timer_task and not no_answer_timer_task.done():
                no_answer_timer_task.cancel()
                no_answer_timer_task = None

            log_answer_started()

        last_answer_at = now
        answer_buffer.append(clean_text)

        log_answer_segment(clean_text)

        await safe_broadcast({
            "type": "answer_partial_collected",
            "question_id": current_question_id,
            "parent_question_id": parent_question_id,
            "question_text": current_question,
            "is_follow_up": follow_up_count > 0,
            "follow_up_count": follow_up_count,
            "max_follow_ups": MAX_FOLLOW_UPS,
            "text": clean_text,
            "answer_so_far": " ".join(answer_buffer),
        })

        await start_answer_timer()

    # ============================================================
    # 답변 평가 + 꼬리질문 판단
    # ============================================================

    async def evaluate_and_maybe_follow_up():
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal answer_buffer
        nonlocal follow_up_count
        nonlocal answer_timer_task
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at

        try:
            await asyncio.sleep(ANSWER_SILENCE_SEC)
        except asyncio.CancelledError:
            return

        if not answer_started:
            print("[답변 평가 보류] 아직 답변이 시작되지 않았습니다.")
            return

        now = time.time()

        if last_answer_at is not None:
            silence_after_last_answer = now - last_answer_at

            if silence_after_last_answer < ANSWER_SILENCE_SEC:
                print("[답변 평가 보류] 아직 답변이 이어지는 중입니다.")
                await start_answer_timer()
                return

        user_answer = " ".join(answer_buffer).strip()

        log_answer_received(
            current_question_id,
            current_question,
            user_answer,
        )

        if not user_answer:
            print("[답변 평가 보류] 누적 답변이 비어 있습니다.")
            return

        if not current_question or not current_question_id:
            log_follow_up_finished("현재 질문이 없음")
            await resume_presentation()
            return

        try:
            eval_result = await question_service.evaluate_answer_ai(
                AnswerEvaluationInput(
                    question_text=current_question,
                    user_answer=user_answer,
                    recent_context=await sr.get_recent_transcript(),
                    pressure_level="medium",
                    follow_up_count=follow_up_count,
                    max_follow_ups=MAX_FOLLOW_UPS,
                )
            )
        except Exception as e:
            print(f"[답변 평가 에러] {e} → 발표로 복귀합니다.")
            log_follow_up_finished("답변 평가 실패")
            await resume_presentation()
            return

        log_answer_evaluation(
            current_question_id,
            current_question,
            user_answer,
            eval_result,
        )

        try:
            _log_raw = await sr.r.get(f"session:{session_id}:answer_log")
            _answer_log = json.loads(_log_raw) if _log_raw else []

            _answer_log.append({
                "question_id": current_question_id,
                "parent_question_id": parent_question_id,
                "question_text": current_question,
                "user_answer": user_answer,
                "answer_score": eval_result.answer_score,
                "evaluation_reason": eval_result.evaluation_reason,
                "audience_reaction": eval_result.audience_reaction,
                "follow_up_needed": eval_result.follow_up_needed,
                "follow_up_question": eval_result.follow_up_question,
                "is_follow_up": follow_up_count > 0,
                "follow_up_count": follow_up_count,
                "max_follow_ups": MAX_FOLLOW_UPS,
                "created_at": time.time(),
            })

            await sr.r.set(
                f"session:{session_id}:answer_log",
                json.dumps(_answer_log, ensure_ascii=False)
            )

        except Exception as e:
            print(f"[답변 로그 저장 에러] {e}")

        await safe_broadcast({
            "type": "answer_evaluated",
            "question_id": current_question_id,
            "parent_question_id": parent_question_id,
            "question_text": current_question,
            "user_answer": user_answer,
            "answer_score": eval_result.answer_score,
            "evaluation_reason": eval_result.evaluation_reason,
            "audience_reaction": eval_result.audience_reaction,
            "follow_up_needed": eval_result.follow_up_needed,
            "follow_up_question": eval_result.follow_up_question,
            "is_follow_up": follow_up_count > 0,
            "follow_up_count": follow_up_count,
            "max_follow_ups": MAX_FOLLOW_UPS,
        })

        await safe_broadcast({
            "type": "audience_reaction",
            "reaction": eval_result.audience_reaction,
            "answer_score": eval_result.answer_score,
            "evaluation_reason": eval_result.evaluation_reason,
            "follow_up_needed": eval_result.follow_up_needed,
            "follow_up_count": follow_up_count,
            "max_follow_ups": MAX_FOLLOW_UPS,
        })

        answer_buffer.clear()
        answer_started = False
        answer_started_at = None
        last_answer_at = None

        await cancel_answer_timers()

        if follow_up_count >= MAX_FOLLOW_UPS:
            log_follow_up_finished("최대 꼬리질문 횟수 도달")
            await resume_presentation()
            return

        if not eval_result.follow_up_needed or not eval_result.follow_up_question:
            log_follow_up_finished("꼬리질문 불필요")
            await resume_presentation()
            return

        follow_up_count += 1
        current_question = eval_result.follow_up_question
        current_question_id = f"{parent_question_id}_follow_up_{follow_up_count}"

        answer_buffer.clear()
        answer_started = False
        answer_started_at = None
        last_answer_at = None

        log_follow_up(current_question_id, current_question)

        try:
            _log_raw = await sr.r.get(f"session:{session_id}:interrupt_log")
            _log = json.loads(_log_raw) if _log_raw else []

            _log.append({
                "question_id": current_question_id,
                "parent_question_id": parent_question_id,
                "question_text": eval_result.follow_up_question,
                "reason": "follow_up",
                "is_follow_up": True,
                "follow_up_count": follow_up_count,
                "max_follow_ups": MAX_FOLLOW_UPS,
                "created_at": time.time(),
            })

            await sr.r.set(
                f"session:{session_id}:interrupt_log",
                json.dumps(_log, ensure_ascii=False)
            )

        except Exception as e:
            print(f"[꼬리질문 로그 저장 에러] {e}")

        await safe_broadcast({
            "type": "interrupt_question",
            "question_id": current_question_id,
            "parent_question_id": parent_question_id,
            "question_text": eval_result.follow_up_question,
            "is_follow_up": True,
            "follow_up_count": follow_up_count,
            "max_follow_ups": MAX_FOLLOW_UPS,
            "pressure_level": "medium",
        })

        await send_question_tts_or_fallback(
            question_id=current_question_id,
            question_text=eval_result.follow_up_question,
            pressure_level="medium",
            is_follow_up=True,
            follow_up_count_value=follow_up_count,
        )

    stt.set_on_final_transcript(on_final_transcript)

    # ============================================================
    # WebSocket 메시지 루프
    # ============================================================

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            tts_playing = await sr.get_tts_playing()

            if msg_type == "audio_chunk":
                if tts_playing:
                    continue

                audio_b64 = msg.get("audio_base64")

                if not audio_b64:
                    print("[STT] audio_base64 없음 → audio_chunk 생략")
                    continue

                if not deepgram_started:
                    try:
                        print("[STT] 첫 audio_chunk 수신 → Deepgram 시작")
                        await stt.start_deepgram()
                        deepgram_started = True
                    except Exception as e:
                        print(f"[STT 시작 에러] {e}")
                        await safe_close_stt("Deepgram 시작 실패")
                        continue

                try:
                    await stt.send_audio(audio_b64)
                except Exception as e:
                    print(f"[STT audio 전송 에러] {e}")
                    await safe_close_stt("audio 전송 실패")
                    continue

            elif msg_type == "partial_transcript":
                if tts_playing:
                    continue

                text = msg.get("text", "").strip()

                if msg.get("is_final") and text:
                    ts = msg.get("timestamp_ms", int(time.time() * 1000))
                    current_state = await sr.get_state()

                    if _is_state(current_state, SessionState.ANSWERING):
                        await append_answer_segment(text)
                    else:
                        await sr.push_transcript(text)
                        await on_final_transcript(text, ts, ts)

                else:
                    try:
                        await stt.handle_partial(text)
                    except Exception as e:
                        print(f"[STT partial 처리 에러] {e}")

            elif msg_type == "vad_state":
                if not tts_playing:
                    await sr.set_user_speaking(msg["is_speaking"])

            elif msg_type == "tts_finished":
                await safe_set_tts_playing(False)
                current_state = await sr.get_state()

                if (
                    _is_state(current_state, SessionState.INTERRUPTED)
                    or _is_state(current_state, SessionState.ANSWERING)
                ):
                    print(f"[TTS 종료] 답변 대기 상태 진입: question_id={current_question_id}")
                    await enter_answering_state()

            elif msg_type == "answer_state":
                if msg.get("state") == "started":
                    print(f"[답변 시작 신호] question_id={current_question_id}")
                    await enter_answering_state()

            elif msg_type == "interrupt_question":
                manual_question_text = msg.get("question_text", "")
                pressure_level = msg.get("pressure_level", "medium")

                if manual_question_text:
                    current_question = manual_question_text
                    follow_up_count = 0

                    answer_buffer.clear()

                    q_id = f"manual_{int(time.time() * 1000)}"
                    current_question_id = q_id
                    parent_question_id = q_id

                    log_new_question(q_id, current_question)

                    await safe_broadcast({
                        "type": "interrupt_question",
                        "question_id": q_id,
                        "parent_question_id": parent_question_id,
                        "question_text": current_question,
                        "pressure_level": pressure_level,
                        "is_follow_up": False,
                        "follow_up_count": follow_up_count,
                        "max_follow_ups": MAX_FOLLOW_UPS,
                    })

                    await send_question_tts_or_fallback(
                        question_id=q_id,
                        question_text=current_question,
                        pressure_level=pressure_level,
                        is_follow_up=False,
                        follow_up_count_value=follow_up_count,
                    )

            elif msg_type == "finish_session":
                print(f"[WS] 세션 종료 요청 수신: {session_id}")

                await cancel_answer_timers()
                await safe_close_stt("finish_session 수신")
                await safe_set_tts_playing(False)

                try:
                    await session_service.end_session(session_id)
                except Exception as e:
                    print(f"[세션 종료 처리 에러] {e}")

                await safe_broadcast({
                    "type": "session_finished",
                    "session_id": session_id,
                })

                break

            elif msg_type == "cancel_session":
                print(f"[WS] 세션 취소 요청 수신: {session_id}")

                await cancel_answer_timers()
                await safe_close_stt("cancel_session 수신")
                await safe_set_tts_playing(False)

                try:
                    cancelled_state = getattr(SessionState, "CANCELLED", None)

                    if cancelled_state is not None:
                        await sr.set_state(cancelled_state)
                    else:
                        await sr.set_state("CANCELLED")

                except Exception as e:
                    print(f"[세션 취소 상태 저장 에러] {e}")

                await safe_broadcast({
                    "type": "session_cancelled",
                    "session_id": session_id,
                })

                break

            else:
                print(f"[WS] 알 수 없는 메시지 타입: {msg_type}")

    except WebSocketDisconnect:
        websocket_closed = True

        current_state = await sr.get_state()
        current_state_name = _safe_session_state_name(current_state)

        finished_name = SessionState.FINISHED.value
        cancelled_name = "CANCELLED"

        if current_state_name not in [finished_name, cancelled_name, None]:
            print(f"[WS 끊김] 세션 {session_id} 자동 종료")
            await cancel_answer_timers()
            await safe_close_stt("WebSocketDisconnect")
            await safe_set_tts_playing(False)

            try:
                await session_service.end_session(session_id)
            except Exception as e:
                print(f"[세션 자동 종료 에러] {e}")

    except Exception as e:
        print(f"[WS 에러] {e}")
        await cancel_answer_timers()
        await safe_close_stt("WS 에러 발생")

    finally:
        websocket_closed = True

        await cancel_answer_timers()

        try:
            await safe_set_tts_playing(False)
        except Exception as e:
            print(f"[WS 종료 처리] tts_playing 초기화 실패: {e}")

        await safe_close_stt("finally 정리")

        try:
            ws_manager.disconnect(session_id, websocket)
        except Exception as e:
            print(f"[WS disconnect 정리 에러] {e}")