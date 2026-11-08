"""TITAN Casa (automação): aparelhos, cadastro, comandos, cenas, voz e registro.

Toda rota resolve a casa do usuário logado e só enxerga o que é dela.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.casa import service as casa
from titan.casa.providers import ProviderError, provider_for
from titan.db.models import CasaDevice, CasaHome, CasaScene, utcnow
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/casa", tags=["casa"], responses={401: {"model": ErrorResponse}})
NOT_FOUND = {404: {"model": ErrorResponse}}
_providers: dict[tuple, Any] = {}


def _provider(ctx: AppContext):
    s = ctx.settings
    key = (s.casa_provider, s.tuya_access_id, s.tuya_region)
    if key not in _providers:
        _providers[key] = provider_for(s)
    return _providers[key]


def _home(db: DBSession, cu: CurrentUser, ctx: AppContext) -> CasaHome:
    home = casa.home_for(db, cu.user.id, ctx.settings.casa_provider)
    if home.provider != ctx.settings.casa_provider:  # trocou de demonstração para Tuya (ou o contrário)
        home.provider = ctx.settings.casa_provider
        db.flush()
    return home


def _err(code: int, kind: str, msg: str) -> JSONResponse:
    return JSONResponse({"error": {"code": kind, "message": msg}}, status_code=code)


def _limit(ctx: AppContext) -> int:
    return ctx.settings.casa_max_commands_per_minute


# --- modelos -------------------------------------------------------------------------

class DeviceOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    icon: str
    room: str
    aliases: str
    configured: bool
    online: bool
    state: dict
    provider_name: str
    infrared: bool


def device_out(d: CasaDevice) -> DeviceOut:
    return DeviceOut(id=d.id, kind=d.kind, name=d.name, icon=d.icon, room=d.room, aliases=d.aliases,
                     configured=d.configured, online=d.online, state=d.state or {}, provider_name=d.provider_name,
                     infrared=bool(d.parent_id))


class SceneAction(BaseModel):
    device_id: uuid.UUID
    action: Literal["on", "off", "dim"]
    ac_temp: Optional[int] = Field(default=None, ge=16, le=30)


class SceneIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phrases: str = Field(default="", max_length=300)
    reply: str = Field(default="", max_length=300)
    actions: list[SceneAction] = Field(default_factory=list, max_length=40)


class SceneOut(SceneIn):
    id: uuid.UUID


def scene_out(s: CasaScene) -> SceneOut:
    acts = []
    for a in s.actions or []:
        try:
            acts.append(SceneAction(**a))
        except Exception:
            continue
    return SceneOut(id=s.id, name=s.name, phrases=s.phrases, reply=s.reply, actions=acts)


class StatusOut(BaseModel):
    provider: str
    cloud: bool
    linked: bool
    home: str
    devices: int
    new: int
    on: int
    scenes: int


class ActionIn(BaseModel):
    do: Literal["on", "off", "toggle", "bright", "white", "ac", "key"]
    value: Optional[Any] = None
    on: Optional[bool] = None
    ac_temp: Optional[int] = Field(default=None, ge=16, le=30)
    ac_mode: Optional[str] = Field(default=None, max_length=10)
    ac_fan: Optional[int] = Field(default=None, ge=0, le=3)


class DevicePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    icon: Optional[str] = Field(default=None, max_length=16)
    room: Optional[str] = Field(default=None, min_length=1, max_length=40)
    aliases: Optional[str] = Field(default=None, max_length=300)
    configured: Optional[bool] = None
    kind: Optional[Literal["plug", "fan"]] = None  # tomada com ventilador pode virar "ventilador"
    position: Optional[int] = Field(default=None, ge=0, le=10_000)


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    source: Literal["voz", "texto", "chat"] = "voz"
    require_wake: bool = False


class UndoStep(BaseModel):
    device_id: uuid.UUID
    action: dict


class CommandOut(BaseModel):
    understood: bool
    kind: str
    reply: str
    device: Optional[DeviceOut] = None
    scene: Optional[str] = None
    failed: list[str] = []
    undo: list[UndoStep] = []


class EventOut(BaseModel):
    at: datetime
    source: str
    action: str
    ok: bool
    detail: str
    device: Optional[str]
    scene: Optional[str]


# --- status e aparelhos ----------------------------------------------------------------

@router.get("/status", response_model=StatusOut)
def get_status(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
               ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    p = _provider(ctx)
    return StatusOut(provider=p.name, cloud=p.cloud, linked=(p.name == "demo" or bool(home.provider_uid)),
                     home=home.name, **casa.counts(db, home))


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(all: bool = False, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                 ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    return [device_out(d) for d in casa.devices(db, home, None if all else True)]


@router.post("/devices/discover", responses={502: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def discover(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    try:
        res = casa.discover(db, home, _provider(ctx))
    except ProviderError as exc:
        return _err(502, "provider_error", str(exc))
    except casa.CasaError as exc:
        return _err(409, "multiple_accounts", str(exc))
    audit.record(db, "casa.discover", actor_type="user", actor_id=cu.user.id, entity_type="casa_home",
                 entity_id=str(home.id), data=res)
    return res


@router.patch("/devices/{device_id}", response_model=DeviceOut, responses={**NOT_FOUND, 422: {"model": ErrorResponse}})
def edit_device(device_id: uuid.UUID, body: DevicePatch, cu: CurrentUser = Depends(current_user),
                db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    try:
        d = casa.owned_device(db, home, device_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aparelho não encontrado.")
    if body.name is not None:
        d.name = " ".join(body.name.split())[:60]
    if body.icon is not None:
        if body.icon not in casa.ICONS:
            return _err(422, "validation_error", "Ícone desconhecido.")
        d.icon = body.icon
    if body.room is not None:
        d.room = " ".join(body.room.split())[:40]
    if body.aliases is not None:
        d.aliases = ", ".join(a.strip() for a in body.aliases.split(",") if a.strip())[:300]
    if body.kind is not None and d.kind in ("plug", "fan"):
        d.kind = body.kind
    if body.position is not None:
        d.position = body.position
    if body.configured is not None:
        d.configured = body.configured
    d.updated_at = utcnow()
    db.flush()
    return device_out(d)


@router.delete("/devices/{device_id}", status_code=204, responses=NOT_FOUND)
def forget_device(device_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                  ctx: AppContext = Depends(get_ctx)) -> Response:
    """Esquece o aparelho no TITAN (na Tuya ele continua). Volta como NOVO se procurar de novo."""
    home = _home(db, cu, ctx)
    try:
        d = casa.owned_device(db, home, device_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aparelho não encontrado.")
    for sc in casa.scenes(db, home):
        sc.actions = [a for a in (sc.actions or []) if str(a.get("device_id")) != str(d.id)]
    db.delete(d)
    return Response(status_code=204)


def _do(db, home, d, action: dict, ctx, cu, source: str):
    try:
        return casa.act(db, home, d, action, _provider(ctx), user_id=cu.user.id, source=source, limit=_limit(ctx))
    except casa.RateLimited as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    except casa.CasaError as exc:
        raise HTTPException(422, str(exc))
    except ProviderError as exc:
        db.commit()  # guarda o registro da falha
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/devices/{device_id}/action", response_model=DeviceOut,
             responses={**NOT_FOUND, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def device_action(device_id: uuid.UUID, body: ActionIn, cu: CurrentUser = Depends(current_user),
                  db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    try:
        d = casa.owned_device(db, home, device_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aparelho não encontrado.")
    _do(db, home, d, body.model_dump(exclude_none=True), ctx, cu, "toque")
    return device_out(d)


@router.post("/devices/{device_id}/identify", response_model=DeviceOut, responses=NOT_FOUND)
def identify(device_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
             ctx: AppContext = Depends(get_ctx)):
    """'Qual é esse?': pisca (desliga/liga) 2 vezes e volta ao estado de antes."""
    home = _home(db, cu, ctx)
    try:
        d = casa.owned_device(db, home, device_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aparelho não encontrado.")
    if d.parent_id:
        raise HTTPException(422,
                            "Controles infravermelhos não piscam: use o LIGAR para ver qual aparelho responde.")
    was_on = bool((d.state or {}).get("on"))
    seq = ["off", "on", "off", "on"] if was_on else ["on", "off", "on", "off"]
    for i, step in enumerate(seq):
        _do(db, home, d, {"do": step}, ctx, cu, "toque")
        db.commit()
        if i < len(seq) - 1:
            time.sleep(0.7)
    return device_out(d)


# --- cenas ---------------------------------------------------------------------------

def _scene_actions(db, home, body: SceneIn) -> list[dict]:
    out = []
    for a in body.actions:
        try:
            casa.owned_device(db, home, a.device_id)  # só aparelhos desta casa
        except KeyError:
            raise HTTPException(422, "Cena com aparelho que não é desta casa.")
        out.append({"device_id": str(a.device_id), "action": a.action} | ({"ac_temp": a.ac_temp} if a.ac_temp else {}))
    return out


@router.get("/scenes", response_model=list[SceneOut])
def list_scenes(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    return [scene_out(s) for s in casa.scenes(db, _home(db, cu, ctx))]


@router.post("/scenes", response_model=SceneOut, status_code=201, responses={422: {"model": ErrorResponse}})
def create_scene(body: SceneIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                 ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    if len(casa.scenes(db, home)) >= 50:
        return _err(422, "too_many", "Limite de 50 cenas por casa.")
    s = CasaScene(home_id=home.id, name=" ".join(body.name.split()), phrases=body.phrases.strip(),
                  reply=body.reply.strip(), actions=_scene_actions(db, home, body), position=len(casa.scenes(db, home)))
    db.add(s)
    db.flush()
    return scene_out(s)


@router.put("/scenes/{scene_id}", response_model=SceneOut, responses=NOT_FOUND)
def update_scene(scene_id: uuid.UUID, body: SceneIn, cu: CurrentUser = Depends(current_user),
                 db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    try:
        s = casa.owned_scene(db, home, scene_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cena não encontrada.")
    s.name, s.phrases, s.reply = " ".join(body.name.split()), body.phrases.strip(), body.reply.strip()
    s.actions, s.updated_at = _scene_actions(db, home, body), utcnow()
    db.flush()
    return scene_out(s)


@router.delete("/scenes/{scene_id}", status_code=204, responses=NOT_FOUND)
def delete_scene(scene_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                 ctx: AppContext = Depends(get_ctx)) -> Response:
    home = _home(db, cu, ctx)
    try:
        db.delete(casa.owned_scene(db, home, scene_id))
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cena não encontrada.")
    return Response(status_code=204)


def _undo_for(d: CasaDevice) -> dict:
    st = dict(d.state or {})
    if d.kind == "ac":
        return {"do": "ac", "on": bool(st.get("on")), **{k: st[k] for k in ("ac_temp", "ac_mode", "ac_fan") if k in st}}
    if d.kind == "light" and st.get("on") and "bright" in st:
        return {"do": "bright", "value": st["bright"]}
    return {"do": "on" if st.get("on") else "off"}


@router.post("/scenes/{scene_id}/run", response_model=CommandOut, responses=NOT_FOUND)
def run_scene(scene_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
              ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    try:
        s = casa.owned_scene(db, home, scene_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cena não encontrada.")
    return _run_scene(db, home, s, ctx, cu, "cena")


def _run_scene(db, home, s, ctx, cu, source) -> CommandOut:
    before = []
    for a in s.actions or []:
        try:
            d = casa.owned_device(db, home, uuid.UUID(str(a.get("device_id"))))
            before.append(UndoStep(device_id=d.id, action=_undo_for(d)))
        except (KeyError, ValueError):
            continue
    try:
        res = casa.run_scene(db, home, s, _provider(ctx), user_id=cu.user.id, source=source, limit=_limit(ctx))
    except casa.RateLimited as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    reply = s.reply or f"Cena {s.name} pronta."
    if res["failed"]:
        reply += f" Não consegui: {', '.join(f.split(':')[0] for f in res['failed'])}."
    return CommandOut(understood=True, kind="scene", reply=reply, scene=s.name, failed=res["failed"], undo=before)


# --- voz / texto ---------------------------------------------------------------------

@router.post("/command", response_model=CommandOut, responses={429: {"model": ErrorResponse}})
def command(body: CommandIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
            ctx: AppContext = Depends(get_ctx)):
    """Frase falada ou digitada → ação. Com require_wake, só age se começar com 'Ei, Titã'."""
    home = _home(db, cu, ctx)
    _, woke = casa.strip_wake(body.text)
    if body.require_wake and not woke:
        return CommandOut(understood=False, kind="ignored", reply="")
    ds = casa.devices(db, home, True)
    intent = casa.understand(body.text, ds, casa.scenes(db, home))
    t = intent["type"]
    src = "voz" if body.source == "voz" else body.source
    if t == "wake":
        return CommandOut(understood=True, kind="wake", reply="Pois não?")
    if t == "scene":
        return _run_scene(db, home, intent["scene"], ctx, cu, src)
    if t == "all":
        undo, failed = [], []
        for d in ds:
            undo.append(UndoStep(device_id=d.id, action=_undo_for(d)))
            try:
                casa.act(db, home, d, {"do": "on" if intent["on"] else "off"} if d.kind != "ac"
                         else {"do": "ac", "on": intent["on"]}, _provider(ctx), user_id=cu.user.id, source=src,
                         limit=_limit(ctx))
            except casa.RateLimited as exc:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
            except (ProviderError, casa.CasaError) as exc:
                failed.append(f"{d.name}: {exc}")
        reply = ("Liguei tudo." if intent["on"] else "Desliguei tudo.") + \
                (f" Não consegui: {', '.join(f.split(':')[0] for f in failed)}." if failed else "")
        return CommandOut(understood=True, kind="all", reply=reply, failed=failed, undo=undo)
    if t == "act":
        d = intent["device"]
        undo = [UndoStep(device_id=d.id, action=_undo_for(d))]
        try:
            casa.act(db, home, d, intent["action"], _provider(ctx), user_id=cu.user.id, source=src, limit=_limit(ctx))
        except casa.RateLimited as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
        except (ProviderError, casa.CasaError) as exc:
            db.commit()
            return CommandOut(understood=True, kind="error", reply=f"Não consegui: {exc}", device=device_out(d))
        return CommandOut(understood=True, kind="device", reply=casa.reply_for(intent, d), device=device_out(d), undo=undo)
    if t == "ask":
        d = intent["device"]
        return CommandOut(understood=True, kind="ask", reply=f"{d.name} está {casa.state_word(d)}.", device=device_out(d))
    if t == "which":
        names = ", ".join(d.name for d in ds) or "nenhum ainda (cadastre em Ajustes)"
        return CommandOut(understood=False, kind="which", reply=f"Qual aparelho? Tenho: {names}.")
    return CommandOut(understood=False, kind="none",
                      reply="Não entendi. Tenta: “liga a luz do quarto” ou o nome de uma cena.")


@router.get("/events", response_model=list[EventOut])
def events(limit: int = 30, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
           ctx: AppContext = Depends(get_ctx)):
    home = _home(db, cu, ctx)
    names = {d.id: d.name for d in casa.devices(db, home)}
    scs = {s.id: s.name for s in casa.scenes(db, home)}
    return [EventOut(at=e.created_at, source=e.source, action=e.action, ok=e.ok, detail=e.detail,
                     device=names.get(e.device_id), scene=scs.get(e.scene_id))
            for e in casa.recent_events(db, home, max(1, min(100, limit)))]
