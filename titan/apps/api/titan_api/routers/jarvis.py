"""Funções do Jarvis: clima, chegada/saída de casa e protocolos (cada conta mexe só no que é seu).

Os aparelhos são os do TITAN Casa da própria conta; cada comando é conferido lá (aparelho de
outra conta dá "não está mais no TITAN Casa", nunca é acionado).
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from starlette.concurrency import run_in_threadpool

from titan.audit import log as audit
from titan.casa.chat import shared_provider
from titan.db.models import utcnow
from titan.jarvis import service, weather
from titan.jarvis import state as jstate
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/jarvis", tags=["jarvis"], responses={401: {"model": ErrorResponse}})
NOT_FOUND = {404: {"model": ErrorResponse}}
_fetcher = None


def _err(code: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": kind, "message": message}}, status_code=code)


def _fetch(url: str) -> str:
    """Busca na internet (só Open-Meteo, endereços públicos conferidos)."""
    global _fetcher
    if _fetcher is None:
        from titan.tools.web.net import Fetcher

        _fetcher = Fetcher(timeout=8.0, max_bytes=600_000, min_interval_per_host=0.2)
    return _fetcher.get(url, accept="application/json").text()


def fetcher(ctx: AppContext):
    """Nos testes o servidor não acessa a internet (cada teste coloca um falso aqui)."""
    return getattr(ctx, "jarvis_fetch", None) or (None if ctx.settings.env.value == "test" else _fetch)


# --- ajustes -----------------------------------------------------------------------------------

class Place(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    admin1: str = Field(default="", max_length=80)
    country: str = Field(default="", max_length=60)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Step(BaseModel):
    device_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    do: Literal["on", "off", "dim"]


class SettingsOut(BaseModel):
    place: Optional[Place]
    rain_alert: bool
    welcome: bool
    ask_leave: bool
    arrive_steps: list[Step]
    presence: str
    presence_at: Optional[str]
    quiet_until: Optional[str]


class SettingsIn(BaseModel):
    rain_alert: Optional[bool] = None
    welcome: Optional[bool] = None
    ask_leave: Optional[bool] = None
    arrive_steps: Optional[list[Step]] = Field(default=None, max_length=30)


def _settings_out(st: dict) -> SettingsOut:
    return SettingsOut(place=st["place"], rain_alert=st["rain_alert"], welcome=st["welcome"],
                       ask_leave=st["ask_leave"], arrive_steps=st["arrive_steps"], presence=st["presence"],
                       presence_at=st["presence_at"], quiet_until=st["quiet_until"])


@router.get("/settings", response_model=SettingsOut)
def get_settings_(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return _settings_out(jstate.get(db, cu.user.id))


@router.put("/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    st = jstate.save(db, cu.user.id, patch)
    audit.record(db, "jarvis.settings", actor_type="user", actor_id=cu.user.id, entity_type="preferences",
                 data={k: v for k, v in patch.items() if k != "arrive_steps"} | (
                     {"arrive_steps": len(patch["arrive_steps"])} if "arrive_steps" in patch else {}))
    return _settings_out(st)


class DeviceOut(BaseModel):
    id: str
    name: str
    kind: str
    on: bool
    online: bool


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                 ctx: AppContext = Depends(get_ctx)):
    """Aparelhos cadastrados no TITAN Casa desta conta (para escolher nos protocolos)."""
    return [DeviceOut(id=str(d.id), name=d.name, kind=d.kind, on=bool((d.state or {}).get("on")), online=d.online)
            for d in service.devices(db, ctx.settings, cu.user.id)]


# --- clima -------------------------------------------------------------------------------------

@router.get("/places", response_model=list[Place], responses={503: {"model": ErrorResponse}})
async def places(q: str = Query(min_length=2, max_length=80), cu: CurrentUser = Depends(current_user),
                 ctx: AppContext = Depends(get_ctx)):
    fetch = fetcher(ctx)
    if fetch is None:
        return _err(503, "unavailable", "Sem acesso à internet para procurar a cidade.")
    try:
        return await run_in_threadpool(weather.geocode, fetch, q)
    except weather.WeatherError as exc:
        return _err(503, "unavailable", str(exc))


@router.put("/place", response_model=SettingsOut)
def put_place(body: Place, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    st = jstate.save(db, cu.user.id, {"place": body.model_dump(), "weather": None, "weather_at": None,
                                      "weather_error": "", "rain_alerted": ""})
    audit.record(db, "jarvis.place", actor_type="user", actor_id=cu.user.id, entity_type="preferences",
                 data={"set": True})
    return _settings_out(st)


@router.delete("/place", status_code=204)
def delete_place(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    jstate.save(db, cu.user.id, {"place": None, "weather": None, "weather_at": None, "weather_error": ""})
    return Response(status_code=204)


@router.get("/weather", response_model=dict)
def get_weather(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                ctx: AppContext = Depends(get_ctx)):
    """Clima da cidade escolhida (fonte: Open-Meteo). {"place": null} se ainda não escolheu."""
    return service.weather_for(db, cu.user.id, utcnow(), fetcher(ctx))


# --- chegada e saída ---------------------------------------------------------------------------

class PresenceIn(BaseModel):
    state: Literal["home", "away"]


class Result(BaseModel):
    name: str
    ok: bool
    detail: str


class PresenceOut(BaseModel):
    presence: str
    changed: bool
    ran: list[Result]
    note: str


@router.post("/presence", response_model=PresenceOut)
def presence(body: PresenceIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
             ctx: AppContext = Depends(get_ctx)):
    """O app do celular avisa: entrou no Wi-Fi de casa (alcança o notebook pela rede local) ou saiu."""
    return service.report_presence(db, ctx.settings, cu.user.id, body.state, shared_provider(ctx.settings))


@router.get("/leave", response_model=list[DeviceOut])
def leave(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    """O que ficou ligado (para a tela "Desligo tudo?")."""
    return [DeviceOut(id=str(d.id), name=d.name, kind=d.kind, on=True, online=d.online)
            for d in service.left_on(db, ctx.settings, cu.user.id)]


class OffIn(BaseModel):
    device_ids: list[str] = Field(max_length=50)


@router.post("/leave/off", response_model=list[Result])
def leave_off(body: OffIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
              ctx: AppContext = Depends(get_ctx)):
    return service.turn_off(db, ctx.settings, cu.user.id, body.device_ids, shared_provider(ctx.settings))


# --- protocolos --------------------------------------------------------------------------------

class ProtocolOut(BaseModel):
    id: str
    name: str
    emoji: str
    special: str
    quiet_until: str
    steps: list[Step]
    lines: list[str]
    summary: str
    custom: bool


class ProtocolIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    emoji: str = Field(default="⚡", max_length=4)
    steps: list[Step] = Field(default_factory=list, max_length=30)
    quiet_until: str = Field(default="", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")


def _proto_out(db: DBSession, ctx: AppContext, uid, p: dict) -> ProtocolOut:
    pl = service.plan(db, ctx.settings, uid, p)
    return ProtocolOut(id=p["id"], name=p["name"], emoji=p.get("emoji", ""), special=p.get("special", ""),
                       quiet_until=p.get("quiet_until", ""), steps=p.get("steps") or [],
                       lines=[x["label"] for x in pl["lines"]], summary=service.describe(pl["lines"]),
                       custom=p["id"] not in {d["id"] for d in service.DEFAULT_PROTOCOLS})


@router.get("/protocols", response_model=list[ProtocolOut])
def list_protocols(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                   ctx: AppContext = Depends(get_ctx)):
    return [_proto_out(db, ctx, cu.user.id, p) for p in service.protocols(db, cu.user.id)]


@router.post("/protocols", response_model=ProtocolOut, status_code=201, responses={422: {"model": ErrorResponse}})
def create_protocol(body: ProtocolIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                    ctx: AppContext = Depends(get_ctx)):
    try:
        p = service.save_protocol(db, cu.user.id, None, body.name, body.emoji,
                                  [s.model_dump() for s in body.steps], body.quiet_until)
    except service.JarvisError as exc:
        return _err(422, "validation_error", str(exc))
    return _proto_out(db, ctx, cu.user.id, p)


@router.put("/protocols/{pid}", response_model=ProtocolOut, responses={**NOT_FOUND, 422: {"model": ErrorResponse}})
def edit_protocol(pid: str, body: ProtocolIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                  ctx: AppContext = Depends(get_ctx)):
    try:
        p = service.save_protocol(db, cu.user.id, pid, body.name, body.emoji,
                                  [s.model_dump() for s in body.steps], body.quiet_until)
    except KeyError:
        raise HTTPException(404, "Protocolo não encontrado.")
    except service.JarvisError as exc:
        return _err(422, "validation_error", str(exc))
    return _proto_out(db, ctx, cu.user.id, p)


@router.delete("/protocols/{pid}", status_code=204, responses={**NOT_FOUND, 422: {"model": ErrorResponse}})
def remove_protocol(pid: str, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        service.delete_protocol(db, cu.user.id, pid)
    except KeyError:
        raise HTTPException(404, "Protocolo não encontrado.")
    except service.JarvisError as exc:
        return _err(422, "validation_error", str(exc))
    return Response(status_code=204)


class RunOut(BaseModel):
    text: str
    results: list[Result]


@router.post("/protocols/{pid}/run", response_model=RunOut, responses=NOT_FOUND)
def run_protocol(pid: str, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                 ctx: AppContext = Depends(get_ctx)):
    """O dono tocou em Executar (ou segurou o botão da Lousa Limpa)."""
    try:
        r = service.run_protocol(db, ctx.settings, cu.user.id, pid, shared_provider(ctx.settings))
    except KeyError:
        raise HTTPException(404, "Protocolo não encontrado.")
    return RunOut(text=r["text"], results=r["results"])
