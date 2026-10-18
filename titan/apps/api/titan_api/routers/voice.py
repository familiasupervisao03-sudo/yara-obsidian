"""Rotas de voz LOCAL: reconhecimento incremental (Vosk) e síntese (Piper).

O áudio chega como PCM 16 bits mono 16 kHz, é processado em memória e
descartado. Nada é gravado em disco nem em logs. Uma transcrição é apenas
texto do usuário: não autoriza nenhuma ação (aprovações continuam exigindo a
interface).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from titan.voice.engines import VoiceUnavailable
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/voice", tags=["voice"], responses={401: {"model": ErrorResponse}})

MAX_CHUNK_BYTES = 256 * 1024  # ~8 s de áudio por pedaço


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class EngineOut(BaseModel):
    name: str
    kind: str
    available: bool
    local: bool
    detail: str


class VoiceStatusOut(BaseModel):
    engines: list[EngineOut]
    sample_rate: int
    notes: list[str]


class SttSessionOut(BaseModel):
    session_id: str


class SttTextOut(BaseModel):
    text: str
    final: bool


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


@router.get("/status", response_model=VoiceStatusOut)
def voice_status(_: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return VoiceStatusOut(
        engines=[EngineOut(**e.__dict__) for e in ctx.voice.status()],
        sample_rate=16000,
        notes=[
            "Vosk e Piper rodam no notebook: áudio e texto não saem do computador.",
            "O reconhecimento de voz do navegador (Web Speech) envia o áudio ao "
            "fornecedor do navegador (ex.: Google) e só é usado se você ativar.",
            "No celular, o microfone só funciona em HTTPS (exigência do navegador).",
        ],
    )


@router.post("/stt/sessions", response_model=SttSessionOut, status_code=201,
             responses={503: {"model": ErrorResponse}})
def stt_open(cu: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    try:
        return SttSessionOut(session_id=ctx.voice.sessions.open(cu.user.id))
    except VoiceUnavailable as exc:
        return _err(503, "voice_unavailable", str(exc))


@router.post("/stt/sessions/{session_id}/audio", response_model=SttTextOut,
             responses={404: {"model": ErrorResponse}, 413: {"model": ErrorResponse}})
async def stt_audio(session_id: str, request: Request, cu: CurrentUser = Depends(current_user),
                    ctx: AppContext = Depends(get_ctx)):
    body = await request.body()
    if len(body) > MAX_CHUNK_BYTES:
        return _err(413, "too_large", "Pedaço de áudio grande demais.")
    from starlette.concurrency import run_in_threadpool

    try:
        text = await run_in_threadpool(ctx.voice.sessions.feed, session_id, cu.user.id, body)
    except KeyError:
        return _err(404, "not_found", "Sessão de reconhecimento expirada ou inexistente.")
    except VoiceUnavailable as exc:
        return _err(413, "too_large", str(exc))
    return SttTextOut(text=text, final=False)


@router.post("/stt/sessions/{session_id}/finish", response_model=SttTextOut,
             responses={404: {"model": ErrorResponse}})
def stt_finish(session_id: str, cu: CurrentUser = Depends(current_user),
               ctx: AppContext = Depends(get_ctx)):
    try:
        return SttTextOut(text=ctx.voice.sessions.finish(session_id, cu.user.id), final=True)
    except KeyError:
        return _err(404, "not_found", "Sessão de reconhecimento expirada ou inexistente.")


@router.delete("/stt/sessions/{session_id}", status_code=204)
def stt_cancel(session_id: str, cu: CurrentUser = Depends(current_user),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    ctx.voice.sessions.cancel(session_id, cu.user.id)
    return Response(status_code=204)


@router.post("/speak", responses={200: {"content": {"audio/wav": {}}},
                                  503: {"model": ErrorResponse}})
def speak(body: SpeakIn, _: CurrentUser = Depends(current_user),
          ctx: AppContext = Depends(get_ctx)):
    try:
        audio = ctx.voice.tts.synthesize(body.text)
    except VoiceUnavailable as exc:
        return _err(503, "voice_unavailable", str(exc))
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
