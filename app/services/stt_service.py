# app/services/stt_service.py

import asyncio
import base64
import time

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

from app.core.config import settings
from app.core.redis_client import SessionRedis
from app.core.websocket_manager import ws_manager
from app.schemas.ws_message import make_final_transcript, make_partial_transcript


class STTAggregator:
    # 연속 실패가 이 횟수에 도달하면 재연결을 잠시 쉰다.
    # (Deepgram이 계속 죽어있는데 audio_chunk마다 재연결을 시도하면
    #  이벤트 루프가 바빠져서 프론트 WS까지 끊기는 사고로 이어질 수 있음)
    _MAX_CONSECUTIVE_FAILURES = 3
    _BASE_COOLDOWN_SEC = 5.0
    _MAX_COOLDOWN_SEC = 30.0

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.sr = SessionRedis(session_id)

        self._dg_connection = None
        self._segment_index = 0

        # close()가 호출되어 세션을 정리 중인지 여부
        self._closed = False

        # Deepgram 연결이 실제로 사용 가능한 상태인지 여부
        self._connected = False

        # start_deepgram 중복 실행 방지
        self._start_lock = asyncio.Lock()

        self._on_final_callback = None
        self._on_partial_callback = None

        # 재연결 서킷브레이커 상태
        self._consecutive_failures = 0
        self._next_retry_at = 0.0

    async def is_connected(self) -> bool:
        return bool(self._dg_connection and self._connected and not self._closed)

    def _in_cooldown(self) -> bool:
        return time.time() < self._next_retry_at

    def in_cooldown(self) -> bool:
        """재연결 서킷브레이커가 발동 중인지 (호출부에서 재시도 자체를 건너뛰기 위함)."""
        return self._in_cooldown()

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES:
            overflow = self._consecutive_failures - self._MAX_CONSECUTIVE_FAILURES
            backoff = min(self._MAX_COOLDOWN_SEC, self._BASE_COOLDOWN_SEC * (2 ** overflow))
            self._next_retry_at = time.time() + backoff
            print(f"[Deepgram] 연속 실패 {self._consecutive_failures}회 → {backoff:.0f}초간 재연결 보류")

    def _record_success(self):
        self._consecutive_failures = 0
        self._next_retry_at = 0.0

    async def ensure_connected(self):
        """
        Deepgram이 살아 있지 않으면 다시 연결한다.
        질문/답변 구간 동안 오디오가 끊겨 keepalive가 죽어도
        발표 재개 후 바로 복구할 수 있게 한다.
        """
        if await self.is_connected():
            return
        await self.start_deepgram()

    async def force_reconnect(self, reason: str = "force_reconnect"):
        """
        기존 연결을 정리한 뒤 새로 연결한다.
        발표 재개 직후 죽은 소켓을 붙잡고 있지 않도록 사용한다.
        """
        print(f"[Deepgram] 강제 재연결: {reason}")
        await self._finish_deepgram_connection(reason=reason, mark_closed=False)
        self._closed = False
        await self.start_deepgram()

    async def start_deepgram(self):
        """
        Deepgram live transcription 연결 시작.

        중요:
        - 여기서 기존 연결이 있으면 먼저 정리한다.
        - Deepgram Error 이벤트 안에서 직접 재귀적으로 start_deepgram() 하지 않는다.
        - 재연결은 session_ws.py가 다음 audio_chunk 수신 시 다시 start_deepgram()을 호출하는 방식으로 처리한다.
        """
        async with self._start_lock:
            if self._in_cooldown():
                remaining = self._next_retry_at - time.time()
                raise RuntimeError(f"Deepgram 재연결 쿨다운 중 ({remaining:.1f}초 남음)")

            # 재시작 허용
            self._closed = False

            # 혹시 기존 연결이 남아 있으면 먼저 정리
            await self._finish_deepgram_connection(reason="restart_before_start")

            try:
                client = DeepgramClient(
                    settings.deepgram_api_key,
                    config=DeepgramClientOptions(
                        options={
                            "keepalive": True,
                            # SDK의 send()는 기본적으로 실패해도 예외를 던지지 않고 False만
                            # 반환하며 자체 로거로만 에러를 찍는다 (문자열 "true"일 때만 예외를 던짐).
                            # 그 결과 audio_chunk 전송 실패도, SDK 내부 keepalive 전송 실패도
                            # 우리 쪽 try/except가 전혀 감지하지 못해 죽은 연결을 계속 쓰게 됐다.
                            "termination_exception_send": "true",
                        }
                    ),
                )

                options = LiveOptions(
                    model="nova-2",
                    language="ko",
                    punctuate=True,
                    interim_results=True,
                    utterance_end_ms=1000,
                )

                self._dg_connection = client.listen.asynclive.v("1")

                async def on_transcript(self_inner, result, **kwargs):
                    try:
                        if self._closed:
                            return

                        alt = result.channel.alternatives[0]
                        text = alt.transcript.strip()

                        if not text:
                            return

                        if not result.is_final:
                            await ws_manager.broadcast(
                                self.session_id,
                                make_partial_transcript(text),
                            )

                            if self._on_partial_callback:
                                try:
                                    now_ms = int(time.time() * 1000)
                                    await self._on_partial_callback(text, now_ms, now_ms)
                                except Exception as e:
                                    print(f"[STT partial 콜백 에러] {e}")

                            return

                        # final transcript 처리(LLM 인터럽트 판단~질문 생성~브로드캐스트)는
                        # 이 커넥션의 내부 태스크에 묶어두지 않는다.
                        # Deepgram 연결이 중간에 끊겨 conn.finish()가 호출되면 SDK가
                        # 이 콜백이 걸려 있던 태스크를 취소하는데, 하필 그 타이밍에
                        # 질문 생성/브로드캐스트가 진행 중이면 asyncio.CancelledError로
                        # 조용히 유실된다 (CancelledError는 Exception이 아니라서
                        # 아래 except로도 못 잡고, 로그도 안 남고 질문도 안 나감).
                        # 별도 태스크로 분리해서 커넥션 생명주기와 무관하게 끝까지 실행되게 한다.
                        asyncio.create_task(self._run_final_transcript(text, result))

                    except Exception as e:
                        print(f"[STT transcript 에러] {e}")

                async def on_error(self_inner, error, **kwargs):
                    """
                    Deepgram 연결 에러.

                    여기서 바로 start_deepgram() 재호출하면
                    기존 keepalive task와 새 연결이 겹칠 수 있으므로 하지 않는다.
                    대신 연결을 죽은 상태로 표시하고 정리한다.
                    session_ws.py가 다음 audio_chunk에서 다시 시작한다.
                    """
                    print(f"[Deepgram 에러] {error}")

                    self._connected = False

                    if not self._closed:
                        self._record_failure()
                        await self._finish_deepgram_connection(
                            reason="deepgram_error_event",
                            mark_closed=False,
                        )

                async def on_close(self_inner, close, **kwargs):
                    print(f"[Deepgram 연결 종료 이벤트] {close}")
                    self._connected = False

                    if not self._closed:
                        # 세션 종료 등으로 우리가 직접 닫은 게 아니라 Deepgram/네트워크 쪽에서
                        # 끊긴 경우(예: keepalive ping timeout 1011)만 실패로 집계한다.
                        self._record_failure()
                        await self._finish_deepgram_connection(
                            reason="deepgram_close_event",
                            mark_closed=False,
                        )

                self._dg_connection.on(
                    LiveTranscriptionEvents.Transcript,
                    on_transcript,
                )
                self._dg_connection.on(
                    LiveTranscriptionEvents.Error,
                    on_error,
                )

                # SDK 버전에 따라 Close 이벤트가 없을 수 있으므로 안전하게 처리
                try:
                    self._dg_connection.on(
                        LiveTranscriptionEvents.Close,
                        on_close,
                    )
                except Exception:
                    pass

                await self._dg_connection.start(options)
                self._connected = True
                self._record_success()

                print("[Deepgram] 연결 시작 완료")

            except Exception as e:
                self._connected = False
                self._dg_connection = None
                self._record_failure()
                print(f"[Deepgram 연결 실패] {e}")
                raise

    async def _on_final_transcript(self, text: str, result):
        segment_id = f"seg_{self.session_id}_{self._segment_index}"
        now_ms = int(time.time() * 1000)

        # result.start는 Deepgram 커넥션이 "시작된 시점" 기준 상대 타임스탬프라서,
        # 질문/답변 구간마다 재연결이 일어날 때마다 다시 0 근처로 리셋된다.
        # 세션 전체를 관통하는 절대 시각이 필요한 곳(대본 정렬, 발표 시간 계산)에
        # 그대로 쓰면 순서와 duration이 다 꼬인다 (silence_tracker.py가 이미 같은
        # 이유로 wall clock을 쓰는 것과 동일한 문제).
        # duration은 발화 길이 자체라 재연결과 무관하게 정확하므로 그대로 믿고,
        # 절대 위치(start/end)는 결과가 도착한 wall clock 시각을 기준으로 잡는다.
        duration_ms = int(result.duration * 1000) if hasattr(result, "duration") else 0
        end_ms = now_ms
        start_ms = max(0, end_ms - duration_ms)

        # scripts 저장은 session_ws.on_final_transcript()에서만 한다.
        # (답변/질문 구간 Deepgram 결과가 발표 대본에 섞이지 않도록 상태 검사 후 저장)
        self._segment_index += 1

        await ws_manager.broadcast(
            self.session_id,
            make_final_transcript(segment_id, text, start_ms, end_ms),
        )

        if self._on_final_callback:
            try:
                await self._on_final_callback(text, start_ms, end_ms)
            except Exception as e:
                print(f"[STT 콜백 에러] {e}")

    async def _run_final_transcript(self, text: str, result):
        """
        on_transcript가 asyncio.create_task로 띄우는 진입점.

        Deepgram 커넥션의 내부 태스크와 분리된 별도 태스크에서 실행되므로,
        처리 도중 커넥션이 끊겨 conn.finish()가 호출되더라도 이 태스크는
        취소되지 않고 LLM 인터럽트 판단~질문 생성~브로드캐스트까지 끝까지 진행된다.
        """
        try:
            await self._on_final_transcript(text, result)
        except Exception as e:
            print(f"[STT final transcript 처리 에러] {e}")

    async def send_audio(self, audio_base64: str):
        """
        프론트에서 받은 audio_base64를 Deepgram으로 전송.

        중요:
        - 전송 실패를 여기서 삼키지 않고 raise한다.
        - 그래야 session_ws.py가 safe_close_stt()로 정리하고
          다음 audio_chunk에서 Deepgram을 다시 시작할 수 있다.
        """
        if self._closed:
            raise RuntimeError("STT connection is closed")

        if not self._dg_connection or not self._connected:
            raise RuntimeError("Deepgram connection is not active")

        try:
            audio_bytes = base64.b64decode(audio_base64)
            await self._dg_connection.send(audio_bytes)

        except Exception as e:
            print(f"[오디오 전송 에러] {e}")

            self._connected = False
            self._record_failure()

            await self._finish_deepgram_connection(
                reason="send_audio_failed",
                mark_closed=False,
            )

            raise

    async def handle_partial(self, text: str):
        await self.sr.r.set(
            f"session:{self.session_id}:partial_text",
            text,
            ex=5,
        )

    async def _finish_deepgram_connection(
        self,
        reason: str = "",
        mark_closed: bool = False,
    ):
        """
        Deepgram 연결 정리.

        mark_closed=True:
        - 세션 종료/취소처럼 완전히 닫는 경우

        mark_closed=False:
        - Deepgram 연결만 죽은 상태로 만들고,
          이후 session_ws.py에서 다시 start_deepgram 가능하게 하는 경우
        """
        if mark_closed:
            self._closed = True

        conn = self._dg_connection
        self._dg_connection = None
        self._connected = False

        if conn:
            try:
                print(f"[Deepgram] 연결 정리 시도: {reason}")
                await conn.finish()
            except Exception as e:
                print(f"[Deepgram] 연결 정리 중 무시 가능한 에러: {e}")

    async def close(self):
        """
        세션 종료/취소/WebSocket 종료 시 호출.
        """
        self._closed = True

        await self._finish_deepgram_connection(
            reason="manual_close",
            mark_closed=True,
        )

    def set_on_final_transcript(self, callback):
        self._on_final_callback = callback

    def set_on_partial_transcript(self, callback):
        self._on_partial_callback = callback