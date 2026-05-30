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
from app.schemas.interrupt import InterruptDecisionInput, SpeechMetricsInput, ContextStateInput
from app.schemas.question import QuestionGenerationInput

router = APIRouter()
session_service = SessionService()


def _generate_feedback(analysis) -> str | None:
    if analysis.recent_wpm > 160:
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


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)
    sr = SessionRedis(session_id)
    stt = STTAggregator(session_id)
    speech_analyzer = SpeechAnalysisService()
    interrupt_service = InterruptService()
    question_service = QuestionService()
    audience_service = AudienceService()
    previous_questions = []
    current_question: str | None = None
    answer_buffer: list[str] = []
    follow_up_count: int = 0
    answer_timer_task: asyncio.Task | None = None
    MAX_FOLLOW_UPS = 2
    ANSWER_SILENCE_SEC = 5
    await stt.start_deepgram()

    async def on_final_transcript(text: str, start_ms: int, end_ms: int):
        try:
            # 1. Speech Analysis
            analysis = await speech_analyzer.analyze(SpeechAnalysisInput(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                is_speaking=True,
                is_interrupt=False,
            ))

            # 2. Redis 메트릭 업데이트
            await sr.set_metrics({
                "current_wpm":        analysis.recent_wpm,
                "average_wpm":        analysis.average_wpm,
                "filler_count_recent": analysis.filler_count,
                "silence_ms":         analysis.silence_duration,
                "silence_count":      analysis.silence_count,
                "stress_score":       analysis.stress_score,
            })

            # 3. live_metrics broadcast
            await ws_manager.broadcast(session_id, make_live_metrics(
                wpm=analysis.recent_wpm,
                filler_count=analysis.filler_count,
                silence_ms=analysis.silence_duration,
                stress_score=analysis.stress_score,
            ))

            # 4. audience_reaction broadcast
            audience_payload = audience_service.evaluate(analysis)
            await ws_manager.broadcast(session_id, audience_payload)

            # 5. live_feedback broadcast
            feedback = _generate_feedback(analysis)
            if feedback:
                await ws_manager.broadcast(session_id, {
                    "type": "live_feedback",
                    "message": feedback,
                })

            # 6. TTS 재생 중이면 인터럽트 판단 스킵
            if await sr.get_tts_playing():
                return

            # 7. cooldown 계산
            last_interrupt = await sr.get_last_interrupt_at()
            cooldown_remaining = 0
            if last_interrupt:
                elapsed = (time.time() - last_interrupt) * 1000
                cooldown_remaining = max(0, 30000 - elapsed)

            # 8. Interrupt 판단
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

            if decision.should_interrupt:
                await sr.set_last_interrupt_at(time.time())
                recent_transcript = await sr.get_recent_transcript()

                # 9. 질문 생성 (Gemini AI, 폴백: 룰 기반)
                question_result = await question_service.generate_question_ai(QuestionGenerationInput(
                    current_topic=None,
                    recent_context=recent_transcript,
                    audience_type="professor",
                    presentation_type="academic",
                    pressure_level="medium",
                    previous_questions=previous_questions,
                ))
                previous_questions.append(question_result.question_text)
                current_question = question_result.question_text
                follow_up_count = 0
                q_id = f"q_{len(previous_questions)}"

                # 인터럽트 로그를 Redis에 누적 저장 (세션 종료 시 DB 기록용)
                _log_raw = await sr.r.get(f"session:{session_id}:interrupt_log")
                _log = json.loads(_log_raw) if _log_raw else []
                _log.append({"question_text": question_result.question_text, "reason": decision.reason})
                await sr.r.set(f"session:{session_id}:interrupt_log", json.dumps(_log, ensure_ascii=False))

                # 10. interrupt_question broadcast
                await ws_manager.broadcast(session_id, {
                    "type": "interrupt_question",
                    "question_id": q_id,
                    "question_text": question_result.question_text,
                    "pressure_level": "medium",
                })

                # 11. TTS 생성 및 broadcast
                await sr.set_tts_playing(True)
                await sr.set_state(SessionState.INTERRUPTED)
                await ws_manager.broadcast(session_id, make_session_state(SessionState.INTERRUPTED))
                try:
                    audio_bytes = await text_to_speech_bytes(question_result.question_text, "medium")
                    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                    await ws_manager.broadcast(session_id, {
                        "type": "tts_audio",
                        "question_id": q_id,
                        "question_text": question_result.question_text,
                        "audio_base64": audio_b64,
                        "format": "mp3",
                    })
                except Exception as e:
                    print(f"[TTS 에러] {e}")
                    await sr.set_tts_playing(False)

        except Exception as e:
            print(f"[분석 파이프라인 에러] {e}")

    async def resume_presentation():
        nonlocal current_question, follow_up_count
        current_question = None
        follow_up_count = 0
        await ws_manager.broadcast(session_id, {"type": "question_resolved"})
        await sr.set_state(SessionState.RUNNING)
        await ws_manager.broadcast(session_id, make_session_state(SessionState.RUNNING))

    async def evaluate_and_maybe_follow_up():
        nonlocal current_question, answer_buffer, follow_up_count, answer_timer_task
        try:
            await asyncio.sleep(ANSWER_SILENCE_SEC)
        except asyncio.CancelledError:
            return

        user_answer = " ".join(answer_buffer).strip()
        answer_buffer.clear()

        if not user_answer or not current_question or follow_up_count >= MAX_FOLLOW_UPS:
            await resume_presentation()
            return

        from app.schemas.question import AnswerEvaluationInput
        eval_result = await question_service.evaluate_answer_ai(AnswerEvaluationInput(
            question_text=current_question,
            user_answer=user_answer,
            recent_context=await sr.get_recent_transcript(),
            pressure_level="medium",
        ))

        await ws_manager.broadcast(session_id, {
            "type": "audience_reaction",
            "reaction": eval_result.audience_reaction,
        })

        if eval_result.follow_up_needed and eval_result.follow_up_question:
            follow_up_count += 1
            current_question = eval_result.follow_up_question
            q_id = f"follow_up_{follow_up_count}"

            await ws_manager.broadcast(session_id, {
                "type": "interrupt_question",
                "question_id": q_id,
                "question_text": eval_result.follow_up_question,
                "is_follow_up": True,
            })
            await sr.set_tts_playing(True)
            await sr.set_state(SessionState.INTERRUPTED)
            await ws_manager.broadcast(session_id, make_session_state(SessionState.INTERRUPTED))
            try:
                audio_bytes = await text_to_speech_bytes(eval_result.follow_up_question, "medium")
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                await ws_manager.broadcast(session_id, {
                    "type": "tts_audio",
                    "question_id": q_id,
                    "question_text": eval_result.follow_up_question,
                    "audio_base64": audio_b64,
                    "format": "mp3",
                })
            except Exception as e:
                print(f"[꼬리질문 TTS 에러] {e}")
                await sr.set_tts_playing(False)
                await resume_presentation()
        else:
            await resume_presentation()

    async def on_partial_transcript(text: str, start_ms: int, end_ms: int):
        pass

    stt.set_on_final_transcript(on_final_transcript)
    stt.set_on_partial_transcript(on_partial_transcript)

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            tts_playing = await sr.get_tts_playing()

            if msg_type == "audio_chunk":
                if not tts_playing:
                    await stt.send_audio(msg["audio_base64"])

            elif msg_type == "partial_transcript":
                if not tts_playing:
                    text = msg.get("text", "").strip()
                    if msg.get("is_final") and text:
                        ts = msg.get("timestamp_ms", int(time.time() * 1000))
                        current_state = await sr.get_state()
                        if current_state == SessionState.ANSWERING:
                            # 답변 수집 중 → 버퍼에 추가 후 침묵 타이머 재시작
                            answer_buffer.append(text)
                            if answer_timer_task and not answer_timer_task.done():
                                answer_timer_task.cancel()
                            answer_timer_task = asyncio.create_task(evaluate_and_maybe_follow_up())
                        else:
                            # 일반 발표 → 인터럽트 파이프라인
                            await sr.push_transcript(text)
                            await on_final_transcript(text, ts, ts)
                    else:
                        await stt.handle_partial(text)

            elif msg_type == "vad_state":
                if not tts_playing:
                    await sr.set_user_speaking(msg["is_speaking"])

            elif msg_type == "tts_finished":
                await sr.set_tts_playing(False)
                current_state = await sr.get_state()
                if current_state in (SessionState.INTERRUPTED, SessionState.ANSWERING):
                    # 질문 TTS 종료 → 답변 수집 시작 (5초 침묵 시 평가)
                    await sr.set_state(SessionState.ANSWERING)
                    await ws_manager.broadcast(session_id, make_session_state(SessionState.ANSWERING))
                    if answer_timer_task and not answer_timer_task.done():
                        answer_timer_task.cancel()
                    answer_timer_task = asyncio.create_task(evaluate_and_maybe_follow_up())

            elif msg_type == "answer_state":
                if msg.get("state") == "started":
                    await sr.set_state(SessionState.ANSWERING)
                    await ws_manager.broadcast(
                        session_id, make_session_state(SessionState.ANSWERING)
                    )

            elif msg_type == "interrupt_question":
                question_text = msg.get("question_text", "")
                pressure_level = msg.get("pressure_level", "medium")
                if question_text:
                    await sr.set_tts_playing(True)
                    await sr.set_state(SessionState.INTERRUPTED)
                    await ws_manager.broadcast(
                        session_id, make_session_state(SessionState.INTERRUPTED)
                    )
                    try:
                        audio_bytes = await text_to_speech_bytes(question_text, pressure_level)
                        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                        await ws_manager.broadcast(session_id, {
                            "type": "tts_audio",
                            "question_text": question_text,
                            "audio_base64": audio_b64,
                            "format": "mp3",
                        })
                    except Exception as e:
                        print(f"[TTS 에러] {e}")
                        await sr.set_tts_playing(False)

    except WebSocketDisconnect:
        current_state = await sr.get_state()
        if current_state not in [SessionState.FINISHED, SessionState.CANCELLED, None]:
            print(f"[WS 끊김] 세션 {session_id} 자동 종료")
            await session_service.end_session(session_id)
    except Exception as e:
        print(f"[WS 에러] {e}")
    finally:
        await stt.close()
        ws_manager.disconnect(session_id, websocket)