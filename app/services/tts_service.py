import asyncio
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from app.core.config import settings

client = ElevenLabs(api_key=settings.elevenlabs_api_key)

VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam

PRESSURE_VOICE = {
    "low":    VoiceSettings(stability=0.7, similarity_boost=0.8),
    "medium": VoiceSettings(stability=0.5, similarity_boost=0.8),
    "high":   VoiceSettings(stability=0.3, similarity_boost=0.9),
}


async def text_to_speech_bytes(text: str, pressure_level: str = "medium") -> bytes:
    voice_settings = PRESSURE_VOICE.get(pressure_level, PRESSURE_VOICE["medium"])

    loop = asyncio.get_event_loop()

    def _generate():
        chunks = client.text_to_speech.convert(
            voice_id=VOICE_ID,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings=voice_settings,
        )
        return b"".join(chunks)

    audio_bytes = await loop.run_in_executor(None, _generate)
    return audio_bytes