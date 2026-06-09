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
from app.core.supabase_client import get_supabase
from app.schemas.ws_message import make_final_transcript, make_partial_transcript


class STTAggregator:
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

    async def start_deepgram(self):
        """
        Deepgram live transcription 연결 시작.

        중요:
        - 여기서 기존 연결이 있으면 먼저 정리한다.
        - Deepgram Error 이벤트 안에서 직접 재귀적으로 start_deepgram() 하지 않는다.
        - 재연결은 session_ws.py가 다음 audio_chunk 수신 시 다시 start_deepgram()을 호출하는 방식으로 처리한다.
        """
        async with self._start_lock:
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

                        await self._on_final_transcript(text, result)

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
                        await self._finish_deepgram_connection(
                            reason="deepgram_error_event",
                            mark_closed=False,
                        )

                async def on_close(self_inner, close, **kwargs):
                    print(f"[Deepgram 연결 종료 이벤트] {close}")
                    self._connected = False

                    if not self._closed:
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

                print("[Deepgram] 연결 시작 완료")

            except Exception as e:
                self._connected = False
                self._dg_connection = None
                print(f"[Deepgram 연결 실패] {e}")
                raise

    async def _on_final_transcript(self, text: str, result):
        segment_id = f"seg_{self.session_id}_{self._segment_index}"
        now_ms = int(time.time() * 1000)

        start_ms = int(result.start * 1000) if hasattr(result, "start") else now_ms
        duration_ms = int(result.duration * 1000) if hasattr(result, "duration") else 0
        end_ms = start_ms + duration_ms

        # 중요:
        # transcript 저장은 session_ws.py의 on_final_transcript()에서만 한다.
        # 여기서도 push_transcript를 하면 같은 발화가 Redis에 중복 저장될 수 있다.
        #
        # await self.sr.push_transcript(text)

        # Supabase scripts 테이블 저장은 유지
        try:
            sb = get_supabase()
            sb.table("scripts").insert({
                "session_id": self.session_id,
                "transcript": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "segment_index": self._segment_index,
            }).execute()
        except Exception as e:
            print(f"[scripts 저장 에러] {e}")

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