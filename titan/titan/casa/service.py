"""TITAN Casa: casa do usuário, aparelhos, comandos, cenas e frases de voz.

Isolamento entre contas (pensado para muitas casas):
* tudo pertence a uma casa (``CasaHome``) e o usuário precisa ser membro dela;
* o app só manda o NOSSO id do aparelho; o id do provedor vem do banco, depois de
  conferir que o aparelho é daquela casa — não dá para mandar comando a um aparelho
  de outra conta, nem adivinhando ids;
* limite de comandos por minuto por casa e registro de cada comando (CasaEvent).
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from titan.casa.providers import ProviderError
from titan.db.models import CasaDevice, CasaEvent, CasaHome, CasaMember, CasaScene, utcnow

ICONS = ("light", "plug", "fan", "laptop", "tv", "ac", "lamp", "speaker", "game", "charger", "heater", "router")
DEFAULT_ICON = {"light": "light", "plug": "plug", "fan": "fan", "tv": "tv", "ac": "ac", "other": "plug"}
DEFAULT_NAME = {"light": "Luz", "plug": "Tomada", "fan": "Ventilador", "tv": "TV", "ac": "Ar-condicionado", "other": "Aparelho"}
DEFAULT_ALIASES = {"light": "luz, lâmpada", "tv": "tv, televisão", "ac": "ar, ar-condicionado, ar condicionado",
                   "fan": "ventilador", "plug": "", "other": ""}
AC_MODES = ("frio", "ventilar", "secar", "auto", "quente")
WHITES = ("quente", "neutro", "frio")
TV_KEYS = ("power", "vol_up", "vol_down", "ch_up", "ch_down", "mute", "ok", "up", "down", "left", "right", "back",
           "home", "input")


class CasaError(Exception):
    pass


class RateLimited(CasaError):
    pass


# --- casa e membros -----------------------------------------------------------------

def home_for(db: DBSession, user_id: uuid.UUID, provider: str) -> CasaHome:
    """A casa do usuário (criada na primeira vez). Hoje: uma casa por dono."""
    home = db.scalar(select(CasaHome).join(CasaMember, CasaMember.home_id == CasaHome.id)
                     .where(CasaMember.user_id == user_id).order_by(CasaMember.created_at).limit(1))
    if home is None:
        home = CasaHome(owner_id=user_id, name="Minha casa", provider=provider)
        db.add(home)
        db.flush()
        db.add(CasaMember(home_id=home.id, user_id=user_id, role="owner"))
        db.flush()
    return home


def owned_device(db: DBSession, home: CasaHome, device_id: uuid.UUID) -> CasaDevice:
    d = db.get(CasaDevice, device_id)
    if d is None or d.home_id != home.id or d.provider != home.provider:
        raise KeyError(device_id)
    return d


def owned_scene(db: DBSession, home: CasaHome, scene_id: uuid.UUID) -> CasaScene:
    s = db.get(CasaScene, scene_id)
    if s is None or s.home_id != home.id:
        raise KeyError(scene_id)
    return s


def devices(db: DBSession, home: CasaHome, configured: Optional[bool] = None) -> list[CasaDevice]:
    stmt = select(CasaDevice).where(CasaDevice.home_id == home.id, CasaDevice.provider == home.provider)
    if configured is not None:
        stmt = stmt.where(CasaDevice.configured.is_(configured))
    return list(db.scalars(stmt.order_by(CasaDevice.position, CasaDevice.created_at)))


def scenes(db: DBSession, home: CasaHome) -> list[CasaScene]:
    return list(db.scalars(select(CasaScene).where(CasaScene.home_id == home.id)
                           .order_by(CasaScene.position, CasaScene.created_at)))


# --- procurar aparelhos ----------------------------------------------------------------

def suggested_name(provider_name: str, kind: str) -> str:
    """Nome que você deu no app (ex.: "ventilador") vira o nome sugerido; nome de fábrica
    (ex.: "LED BULB W5K", "Smart Plug 1") fica com o nome padrão ("Luz", "Tomada")."""
    n = " ".join((provider_name or "").split())
    generic = (not n or (n.upper() == n and any(c.isdigit() for c in n))
               or norm(n).startswith(("smart ", "wifi ", "wi-fi ", "led bulb", "ir remote", "air conditioner")))
    if generic:
        return DEFAULT_NAME.get(kind, "Aparelho")
    return n[0].upper() + n[1:]


def discover(db: DBSession, home: CasaHome, provider) -> dict:
    """Busca na conta do provedor. Novos entram como NÃO cadastrados (o usuário dá nome)."""
    remote = provider.list_devices(home.provider_uid)
    if provider.name == "tuya":
        uids = {r.meta.get("uid") for r in remote if r.meta.get("uid")}
        if not home.provider_uid:
            if len(uids) > 1:
                # Várias contas ligadas ao mesmo projeto: nunca misturar aparelhos de pessoas diferentes.
                raise CasaError("Há mais de uma conta Tuya ligada a este projeto. Por segurança, ligue só a "
                                "sua conta (ou configure TITAN_TUYA_UID) e procure de novo.")
            if uids:
                home.provider_uid = uids.pop()  # trava a casa nesta conta Tuya
        remote = [r for r in remote if not r.meta.get("uid") or r.meta.get("uid") == home.provider_uid]
    # nunca o mesmo aparelho duas vezes (se repetir, fica o que veio com o aparelhinho IR)
    unique: dict[str, Any] = {}
    for r in remote:  # mantém a ordem da conta
        if r.provider_id not in unique or (r.parent_id and not unique[r.provider_id].parent_id):
            unique[r.provider_id] = r
    remote = list(unique.values())
    known = {d.provider_id: d for d in devices(db, home)}
    new = 0
    pos = len(known)
    for r in remote:
        d = known.get(r.provider_id)
        if d is None:
            name = suggested_name(r.name, r.kind)
            aliases = DEFAULT_ALIASES.get(r.kind, "")
            if name.lower() not in [a.strip() for a in aliases.split(",")]:
                aliases = ", ".join(x for x in (name.lower(), aliases) if x)
            d = CasaDevice(home_id=home.id, provider=provider.name, provider_id=r.provider_id, parent_id=r.parent_id,
                           provider_name=r.name[:120], category=r.category[:32], kind=r.kind,
                           name=name[:60], icon=DEFAULT_ICON.get(r.kind, "plug"),
                           aliases=aliases[:300], configured=False, online=r.online,
                           state=r.state, meta=r.meta, position=pos)
            db.add(d)
            pos += 1
            new += 1
        else:
            d.online, d.provider_name, d.parent_id = r.online, r.name[:120], r.parent_id
            if r.state and d.kind not in ("tv", "ac"):  # IR não informa estado: mantém o nosso
                d.state = {**(d.state or {}), **r.state}
            d.meta = {**(d.meta or {}), **r.meta}
            d.updated_at = utcnow()
    db.flush()
    return {"found": len(remote), "new": new}


# --- comandos ------------------------------------------------------------------------

_recent: dict[uuid.UUID, deque] = defaultdict(deque)
_rl_lock = threading.Lock()


def _check_rate(home_id: uuid.UUID, limit: int) -> None:
    now = time.monotonic()
    with _rl_lock:
        q = _recent[home_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            raise RateLimited("Muitos comandos em pouco tempo. Espere alguns segundos.")
        q.append(now)


def validate_action(d: CasaDevice, action: dict) -> dict:
    a = action.get("do")
    if a in ("on", "off", "toggle"):
        if a == "toggle":
            a = "off" if (d.state or {}).get("on") else "on"
        return {"do": a}
    if a == "bright" and d.kind == "light":
        return {"do": "bright", "value": max(1, min(100, int(action.get("value", 100))))}
    if a == "white" and d.kind == "light" and action.get("value") in WHITES:
        return {"do": "white", "value": action["value"]}
    if a == "ac" and d.kind == "ac":
        out: dict[str, Any] = {"do": "ac", "on": bool(action.get("on", True))}
        if "ac_temp" in action:
            out["ac_temp"] = max(16, min(30, int(action["ac_temp"])))
        if action.get("ac_mode") in AC_MODES:
            out["ac_mode"] = action["ac_mode"]
        if "ac_fan" in action:
            out["ac_fan"] = max(0, min(3, int(action["ac_fan"])))
        return out
    if a == "key" and d.kind in ("tv", "other") and action.get("value") in TV_KEYS:
        return {"do": "key", "value": action["value"]}
    raise CasaError("Esse aparelho não aceita esse comando.")


def act(db: DBSession, home: CasaHome, d: CasaDevice, action: dict, provider, *, user_id: Optional[uuid.UUID],
        source: str, limit: int, scene_id: Optional[uuid.UUID] = None) -> dict:
    _check_rate(home.id, limit)
    clean = validate_action(d, action)
    label = clean["do"] + (f":{clean['value']}" if "value" in clean else "")
    try:
        new_state = provider.act(d, clean)
    except ProviderError as exc:
        db.add(CasaEvent(home_id=home.id, user_id=user_id, device_id=d.id, scene_id=scene_id, source=source,
                         action=label[:40], ok=False, detail=str(exc)[:300]))
        db.flush()
        raise
    d.state, d.updated_at = new_state, utcnow()
    db.add(CasaEvent(home_id=home.id, user_id=user_id, device_id=d.id, scene_id=scene_id, source=source,
                     action=label[:40], ok=True, detail=""))
    db.flush()
    return new_state


def run_scene(db: DBSession, home: CasaHome, sc: CasaScene, provider, *, user_id, source: str, limit: int) -> dict:
    done, failed = [], []
    for step in sc.actions or []:
        try:
            d = owned_device(db, home, uuid.UUID(str(step.get("device_id"))))
        except (KeyError, ValueError):
            continue
        what = step.get("action")
        if what == "dim" and d.kind == "light":
            action = {"do": "bright", "value": 10}
        elif what == "on" and d.kind == "ac" and step.get("ac_temp"):
            action = {"do": "ac", "on": True, "ac_temp": step["ac_temp"]}
        elif what in ("on", "off"):
            action = {"do": what} if d.kind != "ac" else {"do": "ac", "on": what == "on"}
        else:
            continue
        try:
            act(db, home, d, action, provider, user_id=user_id, source=source, limit=limit, scene_id=sc.id)
            done.append(d.name)
        except (ProviderError, CasaError) as exc:
            failed.append(f"{d.name}: {exc}")
    return {"done": done, "failed": failed}


def recent_events(db: DBSession, home: CasaHome, limit: int = 30) -> list[CasaEvent]:
    return list(db.scalars(select(CasaEvent).where(CasaEvent.home_id == home.id)
                           .order_by(CasaEvent.created_at.desc(), CasaEvent.id.desc()).limit(limit)))


def counts(db: DBSession, home: CasaHome) -> dict:
    ds = devices(db, home)
    return {"devices": sum(1 for d in ds if d.configured), "new": sum(1 for d in ds if not d.configured),
            "on": sum(1 for d in ds if d.configured and (d.state or {}).get("on")),
            "scenes": db.scalar(select(func.count()).select_from(CasaScene).where(CasaScene.home_id == home.id)) or 0}


# --- voz: entender a frase ----------------------------------------------------------

def norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%-]", " ", t)).strip()


WAKE = re.compile(r"^(?:(?:ei|hey|oi|ok|e ai|eae)\s+)?(?:tita|titan|tita n|titao|tita)\b[\s,]*")
ON = re.compile(r"\b(liga|ligar|acende|acender|ativa|ativar|aciona)\b")
OFF = re.compile(r"\b(desliga|desligar|apaga|apagar|desativa|desativar)\b")


def strip_wake(text: str) -> tuple[str, bool]:
    t = norm(text)
    m = WAKE.match(t)
    return (t[m.end():].strip(), True) if m else (t, False)


def _aliases(d: CasaDevice) -> list[str]:
    al = [d.name] + [a for a in (d.aliases or "").split(",")]
    return sorted({norm(a) for a in al if norm(a)}, key=len, reverse=True)


def find_device(text: str, ds: list[CasaDevice]) -> Optional[CasaDevice]:
    best, size = None, 0
    for d in ds:
        for a in _aliases(d):
            if re.search(rf"(^| ){re.escape(a)}( |$)", text) and len(a) > size:
                best, size = d, len(a)
    return best


def understand(text: str, ds: list[CasaDevice], scs: list[CasaScene]) -> dict:
    """Frase → intenção. Só aparelhos cadastrados. Não executa nada."""
    t, _ = strip_wake(text)
    if not t:
        return {"type": "wake"}
    for s in scs:
        if t == norm(s.name) or t == norm(f"modo {s.name}"):
            return {"type": "scene", "scene": s}
        for p in [norm(x) for x in (s.phrases or "").split(",")]:
            if p and re.search(rf"(^| ){re.escape(p)}( |$)", t):
                return {"type": "scene", "scene": s}
    if re.search(r"\b(liga|acende) tudo\b", t):
        return {"type": "all", "on": True}
    if re.search(r"\b(desliga|apaga) tudo\b", t):
        return {"type": "all", "on": False}
    d = find_device(t, ds)
    num = re.search(r"\b(\d{1,3})\b", t)
    if d and d.kind == "ac" and num and re.search(r"\b(poe|coloca|bota|deixa|muda|em|para|pra)\b", t):
        return {"type": "act", "device": d, "action": {"do": "ac", "on": True, "ac_temp": int(num.group(1))}}
    if d and d.kind == "light" and num and re.search(r"(%|por cento|brilho|\bem\b)", t):
        return {"type": "act", "device": d, "action": {"do": "bright", "value": int(num.group(1))}}
    if d and d.kind == "light":
        for w in WHITES:
            if re.search(rf"\b(branco|luz) {w}\b|\b{w}\b.*\bluz\b", t):
                return {"type": "act", "device": d, "action": {"do": "white", "value": w}}
    vol = re.search(r"\b(aumenta|sobe|abaixa|diminui|baixa)\b.*\bvolume\b", t)
    if vol:
        tv = d if d and d.kind == "tv" else next((x for x in ds if x.kind == "tv"), None)
        if tv:
            up = vol.group(1) in ("aumenta", "sobe")
            return {"type": "act", "device": tv, "action": {"do": "key", "value": "vol_up" if up else "vol_down"}}
    if re.search(r"\b(proximo|sobe|muda o) canal\b", t):
        tv = next((x for x in ds if x.kind == "tv"), None)
        if tv:
            return {"type": "act", "device": tv, "action": {"do": "key", "value": "ch_up"}}
    if d and OFF.search(t):
        return {"type": "act", "device": d, "action": {"do": "off"} if d.kind != "ac" else {"do": "ac", "on": False}}
    if d and ON.search(t):
        return {"type": "act", "device": d, "action": {"do": "on"} if d.kind != "ac" else {"do": "ac", "on": True}}
    if d and re.search(r"\b(como|esta|ta|tá)\b", t):
        return {"type": "ask", "device": d}
    if ON.search(t) or OFF.search(t):
        return {"type": "which"}
    return {"type": "none"}


def fem(d: CasaDevice) -> bool:
    n = norm(d.name)
    return d.kind in ("light", "tv") or n.startswith(("luz", "tv", "lampada", "tomada", "luminaria", "geladeira", "cafeteira"))


def state_word(d: CasaDevice) -> str:
    on = (d.state or {}).get("on")
    return ("ligada" if on else "desligada") if fem(d) else ("ligado" if on else "desligado")


def reply_for(intent: dict, d: Optional[CasaDevice]) -> str:
    a = intent.get("action", {})
    if a.get("do") == "ac" and a.get("on") and "ac_temp" in a:
        return f"{d.name} em {a['ac_temp']} graus."
    if a.get("do") == "bright":
        return f"{d.name} em {a['value']} por cento."
    if a.get("do") == "white":
        return f"{d.name} em branco {a['value']}."
    if a.get("do") == "key":
        return {"vol_up": "Aumentei o volume.", "vol_down": "Abaixei o volume.", "ch_up": "Próximo canal."}.get(a["value"], "Feito.")
    return f"{d.name} {state_word(d)}."
