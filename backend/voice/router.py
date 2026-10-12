"""
voice/router.py — FastAPI router for voice endpoints.

Endpoints:
  POST /voice/transcribe  — accepts audio file → Groq Whisper → transcribed text + intent
  POST /voice/respond     — TTS is handled client-side via Web Speech API;
                            this endpoint simply echoes the text back (no-op for
                            backend) but is kept for completeness / future ElevenLabs.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from voice.transcribe import transcribe_audio
from voice.intent import classify_intent

router = APIRouter(prefix="/voice", tags=["voice"])

# ── Response models ───────────────────────────────────────────────────────────


class TranscribeResponse(BaseModel):
    text: str
    intent: str          # ask_question | explain_symbol | generate_fix | generate_docs
    target: str          # extracted symbol / module name
    confidence: float


class RespondRequest(BaseModel):
    text: str            # response text that the frontend will speak via TTS


class RespondResponse(BaseModel):
    text: str
    tts_provider: str    # "browser_speech_synthesis" or "elevenlabs"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/transcribe", response_model=TranscribeResponse, summary="Transcribe audio → text + intent")
async def transcribe_endpoint(
    audio: UploadFile = File(..., description="Audio file (webm/wav/mp4/ogg) recorded from the browser"),
):
    """
    Accepts an audio file, sends it to Groq Whisper (whisper-large-v3-turbo),
    classifies the intent, and returns the transcribed text with routing metadata.
    """
    if not audio.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        text = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not text:
        raise HTTPException(status_code=422, detail="Transcription returned empty text; is the audio audible?")

    result = classify_intent(text)

    return TranscribeResponse(
        text=result.raw_text,
        intent=result.intent,
        target=result.target,
        confidence=result.confidence,
    )


@router.post("/respond", response_model=RespondResponse, summary="TTS response (browser-side)")
async def respond_endpoint(body: RespondRequest):
    """
    TTS is handled client-side via the browser's Web Speech API (SpeechSynthesis)
    to avoid extra API costs.  This endpoint is a lightweight pass-through that
    confirms the text and signals the TTS provider to the frontend.

    To switch to ElevenLabs in the future, implement the audio synthesis here
    and return a binary audio stream instead.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    return RespondResponse(
        text=body.text,
        tts_provider="browser_speech_synthesis",
    )
