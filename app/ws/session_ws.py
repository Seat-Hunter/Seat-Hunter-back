import asyncio
import json
import base64
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket_manager import ws_manager
from app.core.redis_client import SessionRedis
from app.core.supabase_client import get_supabase
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


def _safe_session_state_name(state) -> str | None:
    if state is None:
        return None

    if isinstance(state, SessionState):
        return state.value

    return str(state)


def _is_state(state, target: SessionState) -> bool:
    return _safe_session_state_name(state) == target.value


def normalize_transcript(value) -> str:
    """
    InterruptService에는 recent_transcript를 문자열로 넘겨야 하므로
    Redis transcript 값을 항상 str로 변환한다.
    """
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value).strip()


def normalize_transcript_list(value) -> list[str]:
    """
    QuestionGenerationInput / AnswerEvaluationInput의 recent_context는
    list[str]를 기대하므로 Redis transcript 값을 항상 list[str]로 변환한다.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    text = str(value).strip()
    if not text:
        return []

    return [text]


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)

    sr = SessionRedis(session_id)
    stt = STTAggregator(session_id)
    speech_analyzer = SpeechAnalysisService()

    # LLM 기반 인터럽트 판단 서비스
    interrupt_service = InterruptService()

    question_service = QuestionService()
    audience_service = AudienceService()

    previous_questions: list[str] = []

    current_question: str | None = None
    current_question_id: str | None = None
    parent_question_id: str | None = None

    answer_buffer: list[str] = []
    follow_up_count: int = 0
    follow_up_history: list[dict] = []

    answer_timer_task: asyncio.Task | None = None
    accept_timeout_task: asyncio.Task | None = None

    answer_started: bool = False
    answer_started_at: float | None = None
    last_answer_at: float | None = None

    skipped_count: int = 0

    # 평균 WPM 계산에서 제외할 비발표 시간(질문 청취/답변/평가 대기) 누적
    non_presenting_started_at: float | None = None
    non_presenting_ms_total: float = 0.0

    QUESTION_ACCEPT_TIMEOUT_SEC = 20.0
    MAX_FOLLOW_UPS = 2

    deepgram_started = False
    websocket_closed = False

    # LLM 인터럽트 판단 호출 제한
    # 질문이 반드시 어느 정도 나와야 하므로 5초/40자보다 조금 완화
    last_llm_interrupt_check_at: float = 0.0
    last_llm_checked_transcript_len: int = 0

    LLM_INTERRUPT_CHECK_INTERVAL_SEC = 3.0
    LLM_INTERRUPT_MIN_TRANSCRIPT_DELTA = 25

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

    def log_llm_interrupt_decision(decision):
        print("\n========== [LLM 인터럽트 판단] ==========")
        print(f"should_interrupt: {decision.should_interrupt}")
        print(f"reason: {decision.reason}")
        print(f"interrupt_type: {decision.interrupt_type}")
        print(f"triggered_by: {decision.triggered_by}")
        print(f"confidence: {getattr(decision, 'confidence', None)}")
        print("========================================\n")

    # ============================================================
    # 상태 전환 함수
    # ============================================================

    async def cancel_answer_timers():
        nonlocal answer_timer_task

        if answer_timer_task and not answer_timer_task.done():
            answer_timer_task.cancel()
        answer_timer_task = None

    async def cancel_accept_timeout():
        nonlocal accept_timeout_task

        if accept_timeout_task and not accept_timeout_task.done():
            accept_timeout_task.cancel()
        accept_timeout_task = None

    async def handle_question_accept_timeout(question_id: str):
        """
        질문이 나온 뒤 일정 시간 동안 사용자가 질문 받기/답변하기를 누르지 않으면 스킵 처리
        """
        nonlocal skipped_count
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal follow_up_count
        nonlocal answer_buffer
        nonlocal non_presenting_started_at
        nonlocal non_presenting_ms_total

        try:
            await asyncio.sleep(QUESTION_ACCEPT_TIMEOUT_SEC)
        except asyncio.CancelledError:
            return

        if current_question_id != question_id:
            return

        skipped_count += 1
        print(f"\n[질문 스킵] {question_id} — {QUESTION_ACCEPT_TIMEOUT_SEC}초 초과, 스킵 횟수: {skipped_count}")

        await safe_broadcast({
            "type": "question_skipped",
            "question_id": question_id,
            "skipped_count": skipped_count,
        })

        try:
            _log_raw = await sr.r.get(f"session:{session_id}:skipped_log")
            _log = json.loads(_log_raw) if _log_raw else []
            _log.append({
                "question_id": question_id,
                "created_at": time.time(),
            })
            await sr.r.set(
                f"session:{session_id}:skipped_log",
                json.dumps(_log, ensure_ascii=False),
            )
        except Exception as e:
            print(f"[스킵 로그 저장 에러] {e}")

        current_question = None
        current_question_id = None
        parent_question_id = None
        follow_up_count = 0
        answer_buffer.clear()

        if non_presenting_started_at is not None:
            non_presenting_ms_total += time.time() * 1000 - non_presenting_started_at
            non_presenting_started_at = None

        await safe_set_tts_playing(False)

        try:
            await sr.set_state(SessionState.RUNNING)
            await safe_broadcast(make_session_state(SessionState.RUNNING))
        except Exception as e:
            print(f"[스킵 후 복귀 에러] {e}")

    async def resume_presentation():
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal follow_up_count
        nonlocal answer_buffer
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at
        nonlocal non_presenting_started_at
        nonlocal non_presenting_ms_total

        current_question = None
        current_question_id = None
        parent_question_id = None
        follow_up_count = 0

        answer_buffer.clear()
        answer_started = False
        answer_started_at = None
        last_answer_at = None

        if non_presenting_started_at is not None:
            non_presenting_ms_total += time.time() * 1000 - non_presenting_started_at
            non_presenting_started_at = None

        await cancel_answer_timers()
        await cancel_accept_timeout()

        await safe_set_tts_playing(False)
        await safe_broadcast({"type": "question_resolved"})

        try:
            await sr.set_state(SessionState.RUNNING)
            await safe_broadcast(make_session_state(SessionState.RUNNING))
        except Exception as e:
            print(f"[상태 복귀 에러] {e}")

    async def enter_answering_state():
        """
        답변 상태로 진입한다.
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
        nonlocal non_presenting_started_at

        await safe_set_tts_playing(True)

        if non_presenting_started_at is None:
            non_presenting_started_at = time.time() * 1000

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
        """
        발표 중 final transcript가 들어올 때마다 실행된다.

        수정 핵심:
        1. InterruptService에는 recent_transcript를 str로 전달
        2. QuestionService에는 recent_context를 list[str]로 전달
        3. 질문 생성 성공 후에만 cooldown 시작
        4. 답변 평가에도 recent_context를 list[str]로 전달
        """
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal follow_up_count
        nonlocal follow_up_history
        nonlocal answer_buffer
        nonlocal accept_timeout_task
        nonlocal last_llm_interrupt_check_at
        nonlocal last_llm_checked_transcript_len

        clean_text = text.strip()
        if not clean_text:
            return

        # 질문 청취(INTERRUPTED)/답변(ANSWERING) 중에 들어온 STT 조각은
        # 발표 발화가 아니므로 WPM/필러 분석 및 인터럽트 판단에서 제외한다.
        if await sr.get_tts_playing():
            return

        current_state = await sr.get_state()
        if _is_state(current_state, SessionState.ANSWERING) or _is_state(current_state, SessionState.INTERRUPTED):
            return

        try:
            analysis = await speech_analyzer.analyze(SpeechAnalysisInput(
                text=clean_text,
                start_ms=start_ms,
                end_ms=end_ms,
                is_speaking=True,
                is_interrupt=False,
                excluded_ms=int(non_presenting_ms_total),
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

            if await sr.get_tts_playing():
                return

            current_state = await sr.get_state()

            if _is_state(current_state, SessionState.ANSWERING):
                return

            if _is_state(current_state, SessionState.INTERRUPTED):
                return

            if current_question_id:
                return

            # 발표 transcript 저장은 여기서만 한다.
            await sr.push_transcript(clean_text)

            recent_transcript_raw = await sr.get_recent_transcript()

            # InterruptService용: 문자열
            recent_transcript = normalize_transcript(recent_transcript_raw)

            # QuestionService용: list[str]
            recent_context_list = normalize_transcript_list(recent_transcript_raw)

            now_for_llm_check = time.time()

            if now_for_llm_check - last_llm_interrupt_check_at < LLM_INTERRUPT_CHECK_INTERVAL_SEC:
                print("[LLM 인터럽트 판단 생략] 호출 간격 제한")
                return

            transcript_delta = len(recent_transcript) - last_llm_checked_transcript_len

            if transcript_delta < LLM_INTERRUPT_MIN_TRANSCRIPT_DELTA:
                print("[LLM 인터럽트 판단 생략] 최근 transcript 변화량 부족")
                return

            last_llm_interrupt_check_at = now_for_llm_check
            last_llm_checked_transcript_len = len(recent_transcript)

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
                    current_topic=None,
                    drift_score=0.0,
                    topic_shift_detected=False,
                    latest_utterance=clean_text,
                    recent_transcript=recent_transcript,
                    slide_context=None,
                    script_context=None,
                ),
                interrupt_enabled=True,
                cooldown_remaining_ms=int(cooldown_remaining),
                pressure_level="medium",
                presentation_type="academic",
                audience_type="professor",
                previous_questions=previous_questions,
            )

            decision = await interrupt_service.decide(interrupt_input)
            log_llm_interrupt_decision(decision)

            if not decision.should_interrupt:
                return

            try:
                question_result = await question_service.generate_question_ai(
                    QuestionGenerationInput(
                        current_topic=None,
                        recent_context=recent_context_list,
                        audience_type="professor",
                        presentation_type="academic",
                        pressure_level="medium",
                        previous_questions=previous_questions,
                    )
                )
            except Exception as e:
                print(f"[질문 생성 에러] {e}")
                return

            # 질문 생성이 성공한 뒤에만 cooldown 시작
            await sr.set_last_interrupt_at(time.time())

            previous_questions.append(question_result.question_text)

            current_question = question_result.question_text
            follow_up_count = 0
            follow_up_history = []
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
                    "interrupt_type": decision.interrupt_type,
                    "triggered_by": decision.triggered_by,
                    "confidence": getattr(decision, "confidence", None),
                    "is_follow_up": False,
                    "follow_up_count": 0,
                    "max_follow_ups": MAX_FOLLOW_UPS,
                    "created_at": time.time(),
                })

                await sr.r.set(
                    f"session:{session_id}:interrupt_log",
                    json.dumps(_log, ensure_ascii=False),
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
                "interrupt_reason": decision.reason,
                "interrupt_type": decision.interrupt_type,
                "triggered_by": decision.triggered_by,
                "confidence": getattr(decision, "confidence", None),
            })

            await cancel_accept_timeout()
            accept_timeout_task = asyncio.create_task(handle_question_accept_timeout(q_id))

        except Exception as e:
            print(f"[분석 파이프라인 에러] {e}")

    # ============================================================
    # 답변 수집
    # ============================================================

    async def append_answer_segment(text: str):
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at

        clean_text = text.strip()

        if not clean_text:
            return

        if not current_question or not current_question_id:
            print(f"[답변 조각 무시] 현재 질문 없음: {clean_text}")
            return

        if current_question and clean_text in current_question:
            print(f"[답변 필터] 질문 텍스트 포함 감지 → 무시: {clean_text[:30]}")
            return

        now = time.time()

        if not answer_started:
            answer_started = True
            answer_started_at = now

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

    # ============================================================
    # 답변 평가 + 꼬리질문 판단
    # ============================================================

    async def evaluate_and_maybe_follow_up_immediate():
        """
        답변 완료 버튼 클릭 시 타이머/침묵 대기 없이 즉시 평가
        """
        nonlocal current_question
        nonlocal current_question_id
        nonlocal parent_question_id
        nonlocal answer_buffer
        nonlocal follow_up_count
        nonlocal follow_up_history
        nonlocal answer_started
        nonlocal answer_started_at
        nonlocal last_answer_at
        nonlocal accept_timeout_task

        user_answer = " ".join(answer_buffer).strip()

        if not user_answer:
            print("[즉시 평가] 답변 없음 → 발표 복귀")
            await resume_presentation()
            return

        if not current_question or not current_question_id:
            await resume_presentation()
            return

        log_answer_received(current_question_id, current_question, user_answer)

        try:
            recent_transcript_raw = await sr.get_recent_transcript()
            recent_context_list = normalize_transcript_list(recent_transcript_raw)

            eval_result = await question_service.evaluate_answer_ai(
                AnswerEvaluationInput(
                    question_id=current_question_id,
                    parent_question_id=parent_question_id,
                    question_text=current_question,
                    user_answer=user_answer,
                    current_topic=None,
                    recent_context=recent_context_list,
                    pressure_level="medium",
                    is_follow_up=follow_up_count > 0,
                    follow_up_count=follow_up_count,
                    max_follow_ups=MAX_FOLLOW_UPS,
                    qa_history=list(follow_up_history),
                )
            )
        except Exception as e:
            print(f"[즉시 평가 에러] {e}")
            await resume_presentation()
            return

        follow_up_history.append({
            "question": current_question,
            "answer": user_answer,
        })

        log_answer_evaluation(
            current_question_id,
            current_question,
            user_answer,
            eval_result,
        )

        try:
            sb = get_supabase()
            sb.table("question_answers").insert({
                "session_id": session_id,
                "question_id": current_question_id,
                "parent_question_id": parent_question_id,
                "question_text": current_question,
                "answer_text": user_answer,
                "answer_score": eval_result.answer_score,
                "is_follow_up": follow_up_count > 0,
                "follow_up_count": follow_up_count,
            }).execute()
        except Exception as e:
            print(f"[question_answers 저장 에러] {e}")

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

        await cancel_accept_timeout()
        accept_timeout_task = asyncio.create_task(
            handle_question_accept_timeout(current_question_id)
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
                is_answer = msg.get("is_answer", False)

                if msg.get("is_final") and text:
                    ts = msg.get("timestamp_ms", int(time.time() * 1000))
                    current_state = await sr.get_state()

                    if is_answer or _is_state(current_state, SessionState.ANSWERING):
                        await append_answer_segment(text)
                    else:
                        await on_final_transcript(text, ts, ts)

                else:
                    try:
                        await stt.handle_partial(text)
                    except Exception as e:
                        print(f"[STT partial 처리 에러] {e}")

            elif msg_type == "vad_state":
                if not tts_playing:
                    await sr.set_user_speaking(msg["is_speaking"])

            elif msg_type == "accept_question":
                q_id = msg.get("question_id", current_question_id)
                print(f"[질문 수락] question_id={q_id}")

                await cancel_accept_timeout()

                if current_question and current_question_id:
                    await send_question_tts_or_fallback(
                        question_id=current_question_id,
                        question_text=current_question,
                        pressure_level="medium",
                        is_follow_up=follow_up_count > 0,
                        follow_up_count_value=follow_up_count,
                    )

            elif msg_type == "tts_finished":
                await safe_set_tts_playing(False)
                current_state = await sr.get_state()

                if (
                    _is_state(current_state, SessionState.INTERRUPTED)
                    or _is_state(current_state, SessionState.ANSWERING)
                ):
                    print(f"[TTS 종료] 답변하기 버튼 대기: question_id={current_question_id}")

                    await safe_broadcast({
                        "type": "waiting_for_answer",
                        "question_id": current_question_id,
                        "question_text": current_question,
                    })

                    if current_question_id:
                        await cancel_accept_timeout()
                        accept_timeout_task = asyncio.create_task(
                            handle_question_accept_timeout(current_question_id)
                        )

            elif msg_type == "answer_started":
                print(f"[답변 시작 신호] question_id={current_question_id}")

                await cancel_accept_timeout()
                await enter_answering_state()

            elif msg_type == "answer_finished":
                print(f"[답변 완료 신호] question_id={current_question_id}")

                current_state = await sr.get_state()

                if _is_state(current_state, SessionState.ANSWERING):
                    await cancel_answer_timers()
                    asyncio.create_task(evaluate_and_maybe_follow_up_immediate())

            elif msg_type == "interrupt_question":
                manual_question_text = msg.get("question_text", "")
                pressure_level = msg.get("pressure_level", "medium")

                if manual_question_text:
                    current_question = manual_question_text
                    follow_up_count = 0
                    follow_up_history = []
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
                await cancel_accept_timeout()
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
                await cancel_accept_timeout()
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
            await cancel_accept_timeout()
            await safe_close_stt("WebSocketDisconnect")
            await safe_set_tts_playing(False)

            try:
                await session_service.end_session(session_id)
            except Exception as e:
                print(f"[세션 자동 종료 에러] {e}")

    except Exception as e:
        print(f"[WS 에러] {e}")

        await cancel_answer_timers()
        await cancel_accept_timeout()
        await safe_close_stt("WS 에러 발생")
        await safe_set_tts_playing(False)

    finally:
        websocket_closed = True

        await cancel_answer_timers()
        await cancel_accept_timeout()

        try:
            await safe_set_tts_playing(False)
        except Exception as e:
            print(f"[WS 종료 처리] tts_playing 초기화 실패: {e}")

        await safe_close_stt("finally 정리")

        try:
            ws_manager.disconnect(session_id, websocket)
        except Exception as e:
            print(f"[WS disconnect 정리 에러] {e}")