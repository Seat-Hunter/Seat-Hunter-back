import asyncio
import base64
import time
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from app.core.config import settings
from app.core.redis_client import SessionRedis
from app.core.websocket_manager import ws_manager
from app.schemas.ws_message import make_final_transcript
from app.repositories import speech_repository


class STTAggregator:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.sr = SessionRedis(session_id)
        self._dg_connection = None
        self._segment_index = 0
        self._closed = False

    async def start_deepgram(self):
        try:
            client = DeepgramClient(settings.deepgram_api_key)
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
                    alt = result.channel.alternatives[0]
                    text = alt.transcript.strip()
                    if not text or not result.is_final:
                        return
                    await self._on_final_transcript(text, result)
                except Exception as e:
                    print(f"[STT transcript 에러] {e}")

            async def on_error(self_inner, error, **kwargs):
                print(f"[Deepgram 에러] {error}")
                if not self._closed:
                    await asyncio.sleep(2)
                    await self.start_deepgram()

            self._dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
            self._dg_connection.on(LiveTranscriptionEvents.Error, on_error)
            await self._dg_connection.start(options)

        except Exception as e:
            print(f"[Deepgram 연결 실패] {e}")

    async def _on_final_transcript(self, text: str, result):
        segment_id = f"seg_{self.session_id}_{self._segment_index}"
        now_ms = int(time.time() * 1000)
        start_ms = int(result.start * 1000) if hasattr(result, "start") else now_ms
        duration_ms = int(result.duration * 1000) if hasattr(result, "duration") else 0
        end_ms = start_ms + duration_ms

        await self.sr.push_transcript(text)
        try:
            await speech_repository.insert_segment(
                session_id=self.session_id,
                segment_id=segment_id,
                segment_index=self._segment_index,
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        except Exception as e:
            print(f"[DB 저장 에러] {e}")

        self._segment_index += 1
        await ws_manager.broadcast(
            self.session_id,
            make_final_transcript(segment_id, text, start_ms, end_ms)
        )

    async def send_audio(self, audio_base64: str):
        if self._dg_connection and not self._closed:
            try:
                await self._dg_connection.send(base64.b64decode(audio_base64))
            except Exception as e:
                print(f"[오디오 전송 에러] {e}")

    async def handle_partial(self, text: str):
        await self.sr.r.set(f"session:{self.session_id}:partial_text", text, ex=5)

    async def close(self):
        self._closed = True
        if self._dg_connection:
            try:
                await self._dg_connection.finish()
            except Exception:
                pass