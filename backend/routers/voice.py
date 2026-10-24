"""
Voice API Router
Provides endpoints for Multi-Layer Voice Synthesis (ElevenLabs Flash v2.5 + edge-tts fallback + browser fallback)
and engine status. Includes SHA-256 disk caching to protect free-tier credits.
"""

from fastapi import APIRouter, Response, status
from backend.schemas import VoiceSpeakRequest, VoiceStatusResponse
from backend.services.elevenlabs_service import synthesize_speech, get_voice_status

router = APIRouter(tags=["Multi-Layer Voice & Text-to-Speech"])


@router.post(
    "/api/voice/speak",
    summary="Synthesize Spoken Audio (Layer 1 Cache -> Layer 2 ElevenLabs / edge-tts -> Layer 3 Browser)",
    description="Synthesizes text into high-quality natural voice with SHA-256 caching and edge-tts quota protection.",
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "Streamed MP3 audio bytes"
        },
        204: {
            "description": "Signal to client to speak via Layer 3 Browser TTS"
        }
    }
)
@router.post(
    "/api/v1/voice/speak",
    include_in_schema=False
)
async def api_voice_speak(payload: VoiceSpeakRequest):
    """
    POST /api/voice/speak
    Takes natural text and returns streaming audio/mpeg bytes.
    Serves from SHA-256 disk cache instantly when available.
    Automatically falls back to edge-tts if ElevenLabs is unavailable or quota is exceeded.
    Returns 204 if browser TTS fallback is requested.
    """
    audio_bytes, was_cached, provider = await synthesize_speech(
        text=payload.text,
        voice_id=payload.voice_id
    )

    if provider == "browser" or not audio_bytes:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "X-Audio-Provider": "browser",
                "X-Audio-Cache": "BYPASS"
            }
        )

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "X-Audio-Cache": "HIT" if was_cached else "MISS",
            "X-Audio-Provider": provider,
            "X-Audio-Fallback": "true" if provider == "edge-tts" else "false",
            "Cache-Control": "public, max-age=86400"
        }
    )


@router.get(
    "/api/voice/status",
    response_model=VoiceStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Multi-Layer Voice Engine Status",
    description="Returns current configuration status, active provider, model ID, and cached phrases count."
)
@router.get(
    "/api/v1/voice/status",
    response_model=VoiceStatusResponse,
    include_in_schema=False
)
def api_voice_status():
    """
    GET /api/voice/status
    Verifies voice provider configuration and reports cache/fallback status.
    """
    return get_voice_status()
