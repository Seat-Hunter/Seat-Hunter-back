import json
import base64
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import ws_manager
from app.core.redis_client import SessionRedis
from app.services.stt_service import STTAggregator
from app.services.session_service import SessionService
from app.services.tts_service import text_to_speech_bytes
from app.schemas.ws_message import make_session_state
from app.schemas.session import SessionState

router = APIRouter()
session_service = SessionService()


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)
    sr = SessionRedis(session_id)
    stt = STTAggregator(session_id)
    await stt.start_deepgram()

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
                    await stt.handle_partial(msg["text"])

            elif msg_type == "vad_state":
                if not tts_playing:
                    await sr.set_user_speaking(msg["is_speaking"])

            elif msg_type == "tts_finished":
                await sr.set_tts_playing(False)
                current_state = await sr.get_state()
                if current_state == SessionState.INTERRUPTED:
                    await sr.set_state(SessionState.RUNNING)
                    await ws_manager.broadcast(
                        session_id, make_session_state(SessionState.RUNNING)
                    )

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
        # WebSocket 끊김 시 세션 자동 종료
        current_state = await sr.get_state()
        if current_state not in [SessionState.FINISHED, None]:
            print(f"[WS 끊김] 세션 {session_id} 자동 종료")
            await session_service.end_session(session_id)
    except Exception as e:
        print(f"[WS 에러] {e}")
    finally:
        await stt.close()
        ws_manager.disconnect(session_id, websocket)