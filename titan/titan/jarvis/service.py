"""Chegada/saída de casa, protocolos (vários aparelhos de uma vez) e a rodada do clima.

Regras:
* tudo é da conta logada: aparelhos só da casa dela (conferidos pelo TITAN Casa a cada comando);
* protocolo só roda depois do "Executar" (ou "sim") do dono — a IA nunca aprova sozinha;
* ao sair, o TITAN só PERGUNTA; desligar é o dono que toca;
* resultado sempre verdadeiro: aparelho que não respondeu aparece como "não respondeu".
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.casa import service as casa
from titan.casa.providers import ProviderError
from titan.db.models import CasaDevice, NewsStory, NewsUserStory, TitanNote, Todo, User, utcnow
from titan.jarvis import state as jstate
from titan.jarvis import weather

log = logging.getLogger("titan.jarvis")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CONFIRM_WINDOW = timedelta(minutes=3)

DEFAULT_PROTOCOLS: list[dict] = [
    {"id": "dormir", "name": "Dormir", "emoji": "🌙", "steps": [], "quiet_until": "07:00", "special": "",
     "done": "Protocolo Dormir concluído. Boa noite, senhor."},
    {"id": "festa", "name": "Festa", "emoji": "🎉", "steps": [], "quiet_until": "", "special": "",
     "done": "Protocolo Festa concluído. Divirta-se, senhor."},
    {"id": "filme", "name": "Filme", "emoji": "🎬", "steps": [], "quiet_until": "", "special": "",
     "done": "Protocolo Filme concluído. Bom filme, senhor."},
    {"id": "acordar", "name": "Acordar", "emoji": "☀️", "steps": [], "quiet_until": "", "special": "",
     "done": "Protocolo Acordar concluído. Bom dia, senhor."},
    {"id": "lousa", "name": "Lousa Limpa", "emoji": "🧹", "steps": [], "quiet_until": "", "special": "all_off",
     "done": "Protocolo Lousa Limpa concluído. Tudo desligado, senhor."},
]
PROTO_KIND = "protocolos"
DO_LABEL = {"on": "ligar", "off": "desligar", "dim": "luz baixa"}


class JarvisError(ValueError):
    pass


def _local(now: datetime) -> datetime:
    from titan.brain.store import local_now

    return now.astimezone(local_now().tzinfo)


def _note(db: DBSession, user_id: uuid.UUID, kind: str, title: str, body: str, now: datetime) -> None:
    db.add(TitanNote(user_id=user_id, kind=kind, title=title[:120], body=body[:2000],
                     day=_local(now).strftime("%Y-%m-%d"), created_at=now))


def _home(db: DBSession, settings, user_id: uuid.UUID):
    home = casa.home_for(db, user_id, settings.casa_provider)
    if home.provider != settings.casa_provider:
        home.provider = settings.casa_provider
    return home


def devices(db: DBSession, settings, user_id: uuid.UUID) -> list[CasaDevice]:
    return casa.devices(db, _home(db, settings, user_id), True)


def _action_for(d: CasaDevice, do: str) -> dict:
    if d.kind == "ac":
        return {"do": "ac", "on": do != "off"}
    if do == "dim" and d.kind == "light":
        return {"do": "bright", "value": 10}
    return {"do": "off" if do == "off" else "on"}


def _run_steps(db: DBSession, settings, user_id: uuid.UUID, steps: list[dict], provider, source: str) -> list[dict]:
    home = _home(db, settings, user_id)
    results = []
    for s in steps:
        try:
            d = casa.owned_device(db, home, uuid.UUID(str(s["device_id"])))
        except (KeyError, ValueError):
            results.append({"name": "Aparelho removido", "ok": False, "detail": "não está mais no TITAN Casa"})
            continue
        try:
            casa.act(db, home, d, _action_for(d, s["do"]), provider, user_id=user_id, source=source,
                     limit=settings.casa_max_commands_per_minute)
            results.append({"name": d.name, "ok": True, "detail": _done_word(d, s["do"])})
        except (ProviderError, casa.CasaError) as exc:
            results.append({"name": d.name, "ok": False, "detail": f"não respondeu ({str(exc)[:80]})"})
    return results


def _done_word(d: CasaDevice, do: str) -> str:
    fem = casa.fem(d)
    if do == "dim":
        return "luz baixa"
    if d.kind == "light":
        return "acesa" if do == "on" else "apagada"
    return ("ligada" if fem else "ligado") if do == "on" else ("desligada" if fem else "desligado")


# --- clima: a rodada --------------------------------------------------------------------------

def _in_silence(db: DBSession, user_id: uuid.UUID, local: datetime) -> bool:
    from titan.brain import prefs as brain_prefs

    p = brain_prefs.get(db, user_id)
    a, b = p["silencio_inicio"], p["silencio_fim"]
    t = local.strftime("%H:%M")
    return (a <= t < b) if a <= b else (t >= a or t < b)


def weather_for(db: DBSession, user_id: uuid.UUID, now: datetime, fetch: Optional[Callable[[str], str]] = None) -> dict:
    """Clima da conta para a tela (busca de novo se tem mais de 30 min e há como buscar)."""
    st = jstate.get(db, user_id)
    place = st["place"]
    if not place:
        return {"place": None}
    if fetch is not None and weather.is_stale(st["weather_at"], now):
        st = refresh_one(db, user_id, fetch, now)
    if not st["weather"]:
        return {"place": place, "error": st["weather_error"] or "Previsão ainda não chegou."}
    out = weather.summary(st["weather"], now, place, st["weather_at"])
    if st["weather_error"]:
        out["error"] = st["weather_error"]
    return out


def refresh_one(db: DBSession, user_id: uuid.UUID, fetch: Callable[[str], str], now: datetime) -> dict:
    st = jstate.get(db, user_id)
    try:
        data = weather.fetch_forecast(fetch, st["place"])
        return jstate.save(db, user_id, {"weather": data, "weather_at": now.isoformat(), "weather_error": ""})
    except weather.WeatherError as exc:
        return jstate.save(db, user_id, {"weather_error": str(exc)})


def tick(settings, session_factory, fetch: Callable[[str], str], now: Optional[datetime] = None) -> dict:
    """Uma rodada (a cada minuto): atualiza o clima de quem escolheu cidade e avisa antes da chuva."""
    now = now or utcnow()
    report = {"clima": 0, "chuva": 0}
    with session_factory.begin() as db:
        for uid in list(db.scalars(select(User.id).where(User.is_active.is_(True)))):
            st = jstate.get(db, uid)
            if not st["place"]:
                continue
            if weather.is_stale(st["weather_at"], now):
                st = refresh_one(db, uid, fetch, now)
                report["clima"] += 1
            if not st["rain_alert"] or not st["weather"]:
                continue
            soon = weather.rain_soon(st["weather"], now)
            if not soon or st["rain_alerted"] == soon[0].isoformat():
                continue
            jstate.save(db, uid, {"rain_alerted": soon[0].isoformat()})
            if _in_silence(db, uid, _local(now)):
                continue
            mins = max(5, round((soon[0] - now).total_seconds() / 60 / 5) * 5)
            when = "em 1 hora" if 50 <= mins <= 70 else f"em {mins} minutos" if mins < 60 else \
                f"às {soon[0].strftime('%Hh%M')}"
            _note(db, uid, "clima", f"TITAN · Chuva {when}, senhor",
                  f"Começa por volta das {soon[0].strftime('%Hh%M')} ({soon[1]}% de chance, segundo o Open-Meteo). "
                  "Recolha a roupa do varal e feche as janelas.", now)
            report["chuva"] += 1
    return report


class JarvisScheduler:
    """Roda ``tick`` a cada minuto numa thread (só busca clima de quem escolheu a cidade)."""

    def __init__(self, settings, session_factory, every: float = 60.0) -> None:
        from titan.tools.web.net import Fetcher

        self.settings, self.session_factory, self.every = settings, session_factory, every
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fetcher = Fetcher(timeout=10.0, max_bytes=600_000, force_ipv4=settings.network_force_ipv4,
                                min_interval_per_host=1.0)

    def fetch(self, url: str) -> str:
        return self._fetcher.get(url, accept="application/json").text()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="titan-jarvis")
        self._thread.start()

    def _run(self) -> None:
        first = True
        while first or not self._stop.wait(self.every):
            first = False
            try:
                r = tick(self.settings, self.session_factory, self.fetch)
                if r["chuva"]:
                    log.info("Clima: %s", r)
            except Exception:
                log.exception("Falha na rodada do clima")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# --- silêncio das notícias (Protocolo Dormir) -------------------------------------------------

def news_quiet(db: DBSession, user_id: uuid.UUID, now: datetime) -> bool:
    until = jstate.get(db, user_id)["quiet_until"]
    if not until:
        return False
    try:
        return now < datetime.fromisoformat(until)
    except ValueError:
        return False


def _next_time(hhmm: str, now: datetime) -> datetime:
    local = _local(now)
    h, m = (int(x) for x in hhmm.split(":"))
    t = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= local:
        t += timedelta(days=1)
    return t.astimezone(timezone.utc)


# --- chegada e saída ----------------------------------------------------------------------------

def _when_hm(dt: datetime) -> str:
    return _local(dt).strftime("%Hh%M").replace("h00", "h")


def _since_summary(db: DBSession, user_id: uuid.UUID, since: datetime, now: datetime) -> list[str]:
    """O que aconteceu enquanto o dono estava fora (só números e títulos reais)."""
    lines = []
    news = db.scalar(select(func.count()).select_from(NewsStory).outerjoin(
        NewsUserStory, (NewsUserStory.story_id == NewsStory.id) & (NewsUserStory.user_id == user_id))
        .where(NewsStory.first_at >= since, NewsStory.is_checagem.is_(False),
               (NewsUserStory.read.is_(None)) | (NewsUserStory.read.is_(False)))) or 0
    if news:
        lines.append("1 notícia nova" if news == 1 else f"{news} notícias novas")
    end = _local(now).replace(hour=23, minute=59, second=59)
    for t in db.scalars(select(Todo).where(Todo.user_id == user_id, Todo.kind == "lembrete", Todo.done_at.is_(None),
                                           Todo.due_at >= now, Todo.due_at <= end).order_by(Todo.due_at).limit(2)):
        lines.append(f"Lembrete às {_when_hm(t.due_at)}: {t.title}")
    return lines


def report_presence(db: DBSession, settings, user_id: uuid.UUID, where: str, provider, now: Optional[datetime] = None) -> dict:
    """O app do celular avisou: chegou ("home") ou saiu ("away"). Só age quando muda."""
    now = now or utcnow()
    st = jstate.get(db, user_id)
    before = st["presence"]
    out: dict[str, Any] = {"presence": where, "changed": before != where, "ran": [], "note": ""}
    if before == where:
        return out
    patch: dict[str, Any] = {"presence": where, "presence_at": now.isoformat()}
    if where == "away":
        patch["left_at"] = now.isoformat()
    jstate.save(db, user_id, patch)
    if before == "":
        return out  # primeira vez que sabe: não dá boas-vindas nem pergunta nada
    if where == "home":
        if st["arrive_steps"]:
            out["ran"] = _run_steps(db, settings, user_id, st["arrive_steps"], provider, "chegada")
        if st["welcome"]:
            try:
                since = datetime.fromisoformat(st["left_at"]) if st["left_at"] else now - timedelta(hours=12)
            except ValueError:
                since = now - timedelta(hours=12)
            lines = _since_summary(db, user_id, since, now)
            body = "Bem-vindo de volta, senhor."
            ok = [r["name"] for r in out["ran"] if r["ok"]]
            bad = [r["name"] for r in out["ran"] if not r["ok"]]
            if ok:
                body += " Liguei: " + ", ".join(ok) + "."
            if bad:
                body += " Não responderam: " + ", ".join(bad) + "."
            body += (" Enquanto o senhor estava fora: " + "; ".join(lines) + ".") if lines else " Tudo tranquilo por aqui."
            _note(db, user_id, "casa", "TITAN · Bem-vindo de volta", body, now)
            out["note"] = body
    elif where == "away" and st["ask_leave"]:
        on = [d for d in devices(db, settings, user_id) if (d.state or {}).get("on")]
        if on:
            names = ", ".join(d.name for d in on)
            body = f"Ficaram ligados: {names}. Desligo tudo? Toque para escolher."
            _note(db, user_id, "casa", "TITAN · O senhor saiu de casa", body, now)
            out["note"] = body
    audit.record(db, "jarvis.presence", actor_type="user", actor_id=user_id, entity_type="presence",
                 data={"from": before, "to": where})
    return out


def left_on(db: DBSession, settings, user_id: uuid.UUID) -> list[CasaDevice]:
    return [d for d in devices(db, settings, user_id) if (d.state or {}).get("on")]


def turn_off(db: DBSession, settings, user_id: uuid.UUID, device_ids: list[str], provider) -> list[dict]:
    """O dono tocou em "Desligar tudo" (ou escolheu alguns)."""
    return _run_steps(db, settings, user_id, [{"device_id": i, "do": "off"} for i in device_ids], provider, "saida")


# --- protocolos ---------------------------------------------------------------------------------

def _proto_row(db: DBSession, user_id: uuid.UUID):
    from titan.db.models import MemoryItem

    return db.scalar(select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == PROTO_KIND))


def protocols(db: DBSession, user_id: uuid.UUID) -> list[dict]:
    import json

    row = _proto_row(db, user_id)
    stored = json.loads(row.content) if row else None
    if not stored:
        return [dict(p) for p in DEFAULT_PROTOCOLS]
    base = {p["id"]: p for p in DEFAULT_PROTOCOLS}
    out = []
    for p in stored:
        b = base.get(p.get("id"), {})
        out.append({**b, **p, "special": b.get("special", "")})
    return out


def _save_protocols(db: DBSession, user_id: uuid.UUID, items: list[dict]) -> None:
    import json

    from titan.db.models import MemoryItem

    content = json.dumps(items, ensure_ascii=False)
    row = _proto_row(db, user_id)
    if row is None:
        db.add(MemoryItem(user_id=user_id, kind=PROTO_KIND, content=content, source="usuário"))
    else:
        row.content, row.updated_at = content, utcnow()
    db.flush()


def get_protocol(db: DBSession, user_id: uuid.UUID, pid: str) -> dict:
    for p in protocols(db, user_id):
        if p["id"] == pid:
            return p
    raise KeyError(pid)


def save_protocol(db: DBSession, user_id: uuid.UUID, pid: Optional[str], name: str, emoji: str, steps: Any,
                  quiet_until: str) -> dict:
    name = " ".join((name or "").split())[:30]
    if not name:
        raise JarvisError("Dê um nome ao protocolo.")
    if quiet_until and not HHMM.match(quiet_until):
        raise JarvisError("Horário do silêncio deve ser HH:MM.")
    try:
        steps = jstate.clean_steps(steps)
    except jstate.StateError as exc:
        raise JarvisError(str(exc)) from exc
    items = protocols(db, user_id)
    if any(p["name"].lower() == name.lower() and p["id"] != pid for p in items):
        raise JarvisError("Já existe um protocolo com esse nome.")
    emoji = (emoji or "⚡")[:4]
    if pid is None:
        if len(items) >= 20:
            raise JarvisError("Limite de 20 protocolos.")
        p = {"id": "p-" + uuid.uuid4().hex[:8], "name": name, "emoji": emoji, "steps": steps,
             "quiet_until": quiet_until, "special": "", "done": f"Protocolo {name} concluído, senhor."}
        items.append(p)
    else:
        p = next((x for x in items if x["id"] == pid), None)
        if p is None:
            raise KeyError(pid)
        p.update(name=name, emoji=emoji, steps=[] if p.get("special") else steps, quiet_until=quiet_until)
        if p["id"] not in {d["id"] for d in DEFAULT_PROTOCOLS}:
            p["done"] = f"Protocolo {name} concluído, senhor."
    _save_protocols(db, user_id, items)
    return p


def delete_protocol(db: DBSession, user_id: uuid.UUID, pid: str) -> None:
    items = protocols(db, user_id)
    if pid in {d["id"] for d in DEFAULT_PROTOCOLS}:
        raise JarvisError("Os protocolos que vêm com o TITAN não podem ser apagados (dá para deixar sem aparelhos).")
    if not any(p["id"] == pid for p in items):
        raise KeyError(pid)
    _save_protocols(db, user_id, [p for p in items if p["id"] != pid])


def plan(db: DBSession, settings, user_id: uuid.UUID, p: dict) -> dict:
    """O que o protocolo vai fazer (mostrado ANTES de executar)."""
    home = _home(db, settings, user_id)
    if p.get("special") == "all_off":
        steps = [{"device_id": str(d.id), "do": "off"} for d in casa.devices(db, home, True)]
    else:
        steps = list(p.get("steps") or [])
    lines = []
    for s in steps:
        try:
            d = casa.owned_device(db, home, uuid.UUID(str(s["device_id"])))
            lines.append({"device_id": str(d.id), "name": d.name, "do": s["do"],
                          "label": f"{d.name} → {DO_LABEL.get(s['do'], s['do'])}"})
        except (KeyError, ValueError):
            continue
    if p.get("quiet_until"):
        lines.append({"device_id": "", "name": "Avisos de notícias", "do": "quiet",
                      "label": f"Avisos de notícias → silenciar até {p['quiet_until']}"})
    return {"steps": steps, "lines": lines}


def describe(lines: list[dict]) -> str:
    if not lines:
        return "Nenhum aparelho escolhido ainda."
    return ", ".join(x["label"].split(" → ")[1] + " " + x["name"].lower() if x["do"] != "quiet"
                     else f"silencia até {x['label'][-5:]}" for x in lines[:4]) + ("…" if len(lines) > 4 else "")


def run_protocol(db: DBSession, settings, user_id: uuid.UUID, pid: str, provider, now: Optional[datetime] = None,
                 via: str = "tela") -> dict:
    now = now or utcnow()
    p = get_protocol(db, user_id, pid)
    pl = plan(db, settings, user_id, p)
    results = _run_steps(db, settings, user_id, pl["steps"], provider, "protocolo")
    if p.get("quiet_until"):
        until = _next_time(p["quiet_until"], now)
        jstate.save(db, user_id, {"quiet_until": until.isoformat()})
        results.append({"name": "Avisos de notícias", "ok": True, "detail": f"até {p['quiet_until']}"})
    jstate.save(db, user_id, {"pending_protocol": None})
    audit.record(db, "jarvis.protocol", actor_type="user", actor_id=user_id, entity_type="protocol",
                 entity_id=pid, data={"via": via, "ok": sum(r["ok"] for r in results),
                                      "failed": sum(not r["ok"] for r in results)})
    bad = [r["name"] for r in results if not r["ok"]]
    text = p.get("done") or f"Protocolo {p['name']} concluído, senhor."
    if not results:
        text = f"O Protocolo {p['name']} ainda não tem aparelhos, senhor. Escolha em Início → Protocolos."
    elif bad:
        text += f" Não responderam: {', '.join(bad)}."
    return {"protocol": p, "results": results, "text": text}


# --- conversa e voz: "Titã, protocolo dormir" → "Posso executar?" → "sim" ----------------------

_ASK = re.compile(r"^(?:(?:ativa|ativar|aciona|acionar|executa|executar|roda|rodar|inicia|iniciar|liga|ligar)\s+)?"
                  r"(?:o\s+)?protocolo\s+(.+?)[\s.!?]*$")
_YES = re.compile(r"^(sim|pode|pode sim|executa|executar|confirma|confirmo|manda|vai|faz|pode executar|ok|claro)\b")
_NO = re.compile(r"^(nao|cancela|cancelar|deixa|esquece|para)\b")


def match_protocol(text: str, items: list[dict]) -> Optional[dict]:
    t, _ = casa.strip_wake(text)
    m = _ASK.match(t)
    if not m:
        return None
    want = casa.norm(m.group(1))
    for p in items:
        n = casa.norm(p["name"])
        if want == n or want == n.split()[0] or casa._close(n, want):
            return p
    return {"id": "", "name": m.group(1)}


def chat_reply(db: DBSession, settings, user_id: uuid.UUID, text: str, provider, now: Optional[datetime] = None
               ) -> Optional[tuple[str, Optional[dict]]]:
    """Resposta sem IA para pedido de protocolo (ou o "sim" depois dele). None se não é o caso."""
    now = now or utcnow()
    if len(text) > 120:
        return None
    st = jstate.get(db, user_id)
    pend = st["pending_protocol"]
    t, _ = casa.strip_wake(text)
    if pend:
        try:
            fresh = now - datetime.fromisoformat(pend["at"]) <= CONFIRM_WINDOW
        except (KeyError, ValueError):
            fresh = False
        if fresh and _YES.match(t):
            try:
                r = run_protocol(db, settings, user_id, pend["id"], provider, now, via="conversa")
            except KeyError:
                jstate.save(db, user_id, {"pending_protocol": None})
                return "Esse protocolo não existe mais, senhor.", None
            return r["text"], {"type": "protocolo_feito", "id": r["protocol"]["id"], "name": r["protocol"]["name"],
                               "emoji": r["protocol"].get("emoji", ""), "results": r["results"]}
        if fresh and _NO.match(t):
            jstate.save(db, user_id, {"pending_protocol": None})
            return "Cancelado, senhor. Não mexi em nada.", None
    p = match_protocol(text, protocols(db, user_id))
    if p is None:
        return None
    if not p["id"]:
        names = ", ".join(x["name"] for x in protocols(db, user_id))
        return f"Não encontrei o protocolo \"{p['name']}\", senhor. Os que existem: {names}.", None
    pl = plan(db, settings, user_id, p)
    if not pl["lines"]:
        return (f"O Protocolo {p['name']} ainda não tem aparelhos, senhor. Escolha quais em Início → Protocolos."), None
    jstate.save(db, user_id, {"pending_protocol": {"id": p["id"], "at": now.isoformat()}})
    bullets = "\n".join(f"• {x['label']}" for x in pl["lines"])
    reply = f"Pois não, senhor. O Protocolo {p['name']} vai:\n{bullets}\nPosso executar? (diga \"sim\" ou toque em Executar)"
    return reply, {"type": "protocolo", "id": p["id"], "name": p["name"], "emoji": p.get("emoji", ""),
                   "special": p.get("special", ""), "lines": [x["label"] for x in pl["lines"]]}
