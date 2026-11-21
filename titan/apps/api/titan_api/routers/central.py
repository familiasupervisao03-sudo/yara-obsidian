"""TITAN Central (tela da TV): resumo do dia, telemetria com alertas críticos, clima e
"mostra na tela".

Interligado com o TITAN e o TITAN Casa (mesma conta). Cada pessoa só vê o que é dela;
a telemetria do notebook (temperatura, processador...) só aparece para o dono do servidor.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from titan.brain import store
from titan.casa import service as casa
from titan.central import telemetry, weather
from titan.db.models import utcnow
from titan.policies.budget import BudgetGuard
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/central", tags=["central"], responses={401: {"model": ErrorResponse}})

_sampler = telemetry.Sampler()
_shown: dict[uuid.UUID, dict] = {}   # "mostra na tela": o último item de cada pessoa
_shown_lock = threading.Lock()


# --- modelos -----------------------------------------------------------------------------

class GoalBrief(BaseModel):
    id: uuid.UUID
    title: str
    unit: str
    current: float
    target: float
    pct: Optional[int]


class TodoBrief(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    due_at: Optional[datetime]
    done: bool


class DeviceBrief(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    icon: str
    room: str
    on: bool
    online: bool
    watts: Optional[float] = None


class EventBrief(BaseModel):
    id: int
    at: datetime
    source: str
    action: str
    ok: bool
    device: Optional[str]
    scene: Optional[str]


class CasaBrief(BaseModel):
    demo: bool
    devices: list[DeviceBrief]
    on: int
    last_event: Optional[EventBrief]


class ShowItem(BaseModel):
    id: uuid.UUID
    title: str
    text: str
    at: datetime


class Overview(BaseModel):
    greeting: str
    username: str
    now: datetime
    goals: list[GoalBrief]
    today: list[TodoBrief]
    casa: CasaBrief
    weather: Optional[dict]
    show: Optional[ShowItem]


class ShowIn(BaseModel):
    title: str = Field(default="", max_length=160)
    text: str = Field(min_length=1, max_length=6000)


# --- rotas -------------------------------------------------------------------------------

def _weather(ctx: AppContext) -> Optional[dict]:
    s = ctx.settings
    if s.local_only or s.central_lat is None or s.central_lon is None:
        return None
    try:
        return weather.current(s.central_lat, s.central_lon, s.central_city)
    except weather.WeatherError:
        return None


@router.get("/overview", response_model=Overview)
def overview(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
             ctx: AppContext = Depends(get_ctx)) -> Overview:
    now = store.local_now()
    greeting = "Bom dia" if 5 <= now.hour < 12 else "Boa tarde" if 12 <= now.hour < 18 else "Boa noite"
    goals = [GoalBrief(id=g.id, title=g.title, unit=g.unit, current=g.current, target=g.target,
                       pct=min(100, round(100 * g.current / g.target)) if g.target > 0 else None)
             for g in store.active_goals(db, cu.user.id)]
    today = [TodoBrief(id=t.id, title=t.title, kind=t.kind, due_at=t.due_at, done=t.done_at is not None)
             for t in store.today_todos(db, cu.user.id)]
    home = casa.home_for(db, cu.user.id, ctx.settings.casa_provider)
    ds = casa.devices(db, home, configured=True)
    names = {d.id: d.name for d in ds}
    scenes = {sc.id: sc.name for sc in casa.scenes(db, home)}
    ev = next(iter(casa.recent_events(db, home, 1)), None)
    last = (EventBrief(id=ev.id, at=ev.created_at, source=ev.source, action=ev.action, ok=ev.ok,
                       device=names.get(ev.device_id), scene=scenes.get(ev.scene_id)) if ev else None)
    devices = [DeviceBrief(id=d.id, name=d.name, kind=d.kind, icon=d.icon, room=d.room,
                           on=bool((d.state or {}).get("on")), online=d.online,
                           watts=(d.state or {}).get("watts")) for d in ds]
    with _shown_lock:
        shown = _shown.get(cu.user.id)
    return Overview(greeting=greeting, username=cu.user.username, now=now, goals=goals, today=today,
                    casa=CasaBrief(demo=ctx.settings.casa_provider == "demo", devices=devices,
                                   on=sum(1 for d in devices if d.on), last_event=last),
                    weather=_weather(ctx), show=ShowItem(**shown) if shown else None)


def _charger_plug(db: DBSession, cu: CurrentUser, ctx: AppContext) -> Optional[dict]:
    """A tomada do carregador do notebook (ícone "carregador" ou "notebook" no TITAN Casa)."""
    home = casa.home_for(db, cu.user.id, ctx.settings.casa_provider)
    plugs = [d for d in casa.devices(db, home, configured=True) if d.icon in ("charger", "laptop") and not d.parent_id]
    plugs.sort(key=lambda d: d.icon != "charger")
    if not plugs:
        return None
    d = plugs[0]
    return {"id": str(d.id), "name": d.name, "on": bool((d.state or {}).get("on")),
            "watts": (d.state or {}).get("watts")}


@router.get("/telemetry")
def telemetry_view(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
                   ctx: AppContext = Depends(get_ctx)) -> dict:
    # A máquina é do dono do servidor: outras contas não veem temperatura, processos etc.
    if cu.user.role != "owner":
        return {"available": False, "alerts": []}
    s = ctx.settings
    spend_pct = None
    if s.allow_paid_apis and s.daily_paid_budget_brl > 0:
        spent = BudgetGuard(s, ctx.session_factory).spent_today(db)
        spend_pct = round(100 * spent / s.daily_paid_budget_brl, 1)
    plug = _charger_plug(db, cu, ctx)
    charger_w = plug["watts"] if plug and plug["on"] and isinstance(plug["watts"], (int, float)) else None
    cur = _sampler.sample_if_due(spend_pct=spend_pct, charger_w=charger_w)
    hist = list(_sampler.history)
    return {"available": True, "now": telemetry.snapshot(cur),
            "history": {k: [getattr(h, k) for h in hist] for k in ("cpu", "temp", "mem")},
            "limits": {"temp": telemetry.TEMP_LIMIT, "cpu": telemetry.CPU_LIMIT},
            "alerts": telemetry.alerts(hist, _sampler.top_process, plug)}


@router.post("/show", response_model=ShowItem, status_code=201)
def show(body: ShowIn, cu: CurrentUser = Depends(current_user)) -> ShowItem:
    """"Mostra na tela": o celular (ou o chat) manda um conteúdo para a TV desta conta."""
    item = {"id": uuid.uuid4(), "title": body.title.strip() or "Do TITAN", "text": body.text.strip(), "at": utcnow()}
    with _shown_lock:
        _shown[cu.user.id] = item
    return ShowItem(**item)


@router.delete("/show", status_code=204)
def clear_show(cu: CurrentUser = Depends(current_user)) -> None:
    with _shown_lock:
        _shown.pop(cu.user.id, None)
