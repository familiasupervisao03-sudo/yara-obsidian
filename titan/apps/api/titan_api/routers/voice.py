"""Rotas de voz: reconhecimento incremental local (Vosk) e síntese (Piper local ou,
se autorizada, a voz natural on-line).

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

from titan.memory import preferences as user_prefs
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
    # Só no texto final: nota média (0..1) e o veredito — ok, noise (ruído: ignorar)
    # ou unclear (provavelmente mal entendido: pedir para repetir).
    confidence: Optional[float] = None
    verdict: str = "ok"
    # Correções do seu dicionário aplicadas ao texto (a tela avisa; nada é trocado sem aviso).
    corrections: list[str] = []
    # Quem ouviu (groq, xai ou vosk) e um aviso quando o on-line falhou e o Vosk assumiu.
    engine: Optional[str] = None
    note: str = ""


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


@router.get("/status", response_model=VoiceStatusOut)
def voice_status(_: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return VoiceStatusOut(
        engines=[EngineOut(**e.__dict__) for e in ctx.voice.status()],
        sample_rate=16000,
        notes=[
            f"O reconhecimento é on-line ({ctx.voice.cloud_stt.label}): o áudio de cada fala sai do "
            f"notebook. Se a {ctx.voice.cloud_stt.company} falhar, o Vosk local assume."
            if ctx.voice.cloud_stt is not None else
            "O reconhecimento (Vosk) roda no notebook: o áudio da sua fala não sai do computador.",
            "A voz do TITAN é on-line (Microsoft): o texto das respostas sai do notebook."
            if ctx.voice.tts.name == "edge" else
            "A voz do TITAN (Piper) roda no notebook: o texto não sai do computador.",
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
             responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def stt_finish(session_id: str, cu: CurrentUser = Depends(current_user),
                     ctx: AppContext = Depends(get_ctx)):
    from starlette.concurrency import run_in_threadpool

    try:
        # Pode chamar a Groq (rede): fora do laço de eventos.
        t = await run_in_threadpool(ctx.voice.sessions.finish, session_id, cu.user.id)
    except KeyError:
        return _err(404, "not_found", "Sessão de reconhecimento expirada ou inexistente.")
    except VoiceUnavailable as exc:
        return _err(503, "voice_unavailable", str(exc))
    with ctx.session_factory() as db:
        corrections = user_prefs.get(db, cu.user.id)["corrections"]
    text, applied = user_prefs.apply_corrections(t.text, corrections) if t.verdict != "noise" else (t.text, [])
    return SttTextOut(text=text, final=True, confidence=t.confidence, verdict=t.verdict,
                      corrections=applied, engine=t.engine, note=t.note)


@router.delete("/stt/sessions/{session_id}", status_code=204)
def stt_cancel(session_id: str, cu: CurrentUser = Depends(current_user),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    ctx.voice.sessions.cancel(session_id, cu.user.id)
    return Response(status_code=204)


@router.post("/speak", responses={200: {"content": {"audio/wav": {}, "audio/mpeg": {}}},
                                  503: {"model": ErrorResponse}})
def speak(body: SpeakIn, cu: CurrentUser = Depends(current_user),
          ctx: AppContext = Depends(get_ctx)):
    with ctx.session_factory() as db:
        rate = user_prefs.get(db, cu.user.id)["voice_rate"]
    try:
        audio = ctx.voice.tts.synthesize(body.text, rate=rate)
    except VoiceUnavailable as exc:
        return _err(503, "voice_unavailable", str(exc))
    return Response(audio, media_type=ctx.voice.tts.media_type, headers={"Cache-Control": "no-store"})


# --- abaixar o som do notebook enquanto fala ("ducking") ---------------------------------

_ducker = None


def _get_ducker(ctx: AppContext):
    global _ducker
    from titan.voice.duck import Ducker

    if _ducker is None:
        _ducker = Ducker(ctx.settings.audio_duck_level, ctx.settings.data_dir / "apps")
    return _ducker


class DuckIn(BaseModel):
    on: bool
    holder: str = Field(min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class DuckOut(BaseModel):
    available: bool
    active: bool
    changed: int = 0


@router.post("/duck", response_model=DuckOut)
def duck(body: DuckIn, cu: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)) -> DuckOut:
    """Abaixa (on=true) ou devolve (on=false) o som dos outros programas do notebook.

    Só o dono do servidor mexe no som da máquina. Renovar a cada ~10 s enquanto durar;
    sem renovação, o volume volta sozinho em ~30 s.
    """
    from titan.voice.duck import Ducker

    s = ctx.settings
    if cu.user.role != "owner" or not s.audio_duck or not Ducker.available():
        return DuckOut(available=False, active=False)
    d = _get_ducker(ctx)
    try:
        n = d.duck(body.holder) if body.on else d.release(body.holder)
    except Exception:  # servidor de som fora do ar: a voz continua normal
        return DuckOut(available=False, active=False)
    return DuckOut(available=True, active=d.active, changed=n)
