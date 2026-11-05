"""Sócio: memória (cérebro), metas, lembretes/tarefas, perguntas, resumo 📌 e mensagens do TITAN."""

import json
import uuid
from datetime import datetime, timedelta

import pytest

from tests.conftest import CSRF, build_client, create_user, login
from titan.brain import proactive, store
from titan.brain.safety import sensitive_reason
from titan.models.providers import MockProvider


def parse(text):
    out = []
    for block in text.strip().split("\n\n"):
        ev = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        if "event" in ev:
            out.append((ev["event"], json.loads(ev["data"])))
    return out


@pytest.fixture
def chat(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="mock")
    upgrade_head(s.database_url)
    uid = create_user(s)
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        yield c, cid, s, uid
    MockProvider.json_reply = None


def empty(**kw):
    base = {"lembretes": [], "tarefas": [], "lembrancas": [], "resolvidos": [], "progresso_metas": [],
            "novas_metas": []}
    return {**base, **kw}


# --- o que nunca é guardado ----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "meu cpf é 123.456.789-09", "meu telefone é (11) 98765-4321", "eu moro na rua das flores",
    "estudo no colégio Santa Maria", "minha senha do insta é abc", "estou tomando remédio para ansiedade",
    "meu e-mail é luiz@exemplo.com", "minha mãe se chama Ana", "CEP 01234-567", "chave gsk_abcdefghijkl123",
])
def test_sensitive_is_blocked(text):
    assert sensitive_reason(text)


@pytest.mark.parametrize("text", [
    "Microfone do notebook com chiado", "Joga Brawl Stars", "Vendeu 2 bolos por R$ 30",
    "Quer ganhar R$ 300 por mês até dezembro", "Prefere explicação curta e com exemplo",
    "Prova de matemática dia 20/11", "Aprende melhor na prática",
])
def test_normal_facts_pass(text):
    assert sensitive_reason(text) is None


# --- memória pela API ----------------------------------------------------------------

def test_memory_crud_search_and_refusal(auth_client):
    c = auth_client
    r = c.post("/api/v1/brain/memories", json={"content": "Microfone do notebook com chiado", "category": "outros"},
               headers=CSRF)
    assert r.status_code == 201 and r.json()["status"] == "active" and r.json()["origin"] == "voce"
    mid = r.json()["id"]
    c.post("/api/v1/brain/memories", json={"content": "Joga Brawl Stars", "category": "gostos"}, headers=CSRF)
    bad = c.post("/api/v1/brain/memories", json={"content": "moro na rua X, 10"}, headers=CSRF)
    assert bad.status_code == 422 and "não guardo" in bad.json()["error"]["message"]
    found = c.get("/api/v1/brain/memories", params={"q": "microfones"}).json()
    assert [m["id"] for m in found["items"]] == [mid] and found["counts"]["total"] == 2
    assert c.get("/api/v1/brain/memories", params={"category": "gostos"}).json()["items"][0]["content"] == "Joga Brawl Stars"
    r = c.patch(f"/api/v1/brain/memories/{mid}", json={"content": "Microfone novo USB, sem chiado"}, headers=CSRF)
    assert r.json()["content"] == "Microfone novo USB, sem chiado"
    assert c.delete(f"/api/v1/brain/memories/{mid}", headers=CSRF).status_code == 204
    assert c.post("/api/v1/brain/memories/erase", json={"confirm": "sim"}, headers=CSRF).status_code == 422
    assert c.post("/api/v1/brain/memories/erase", json={"confirm": "APAGAR"}, headers=CSRF).status_code == 204
    assert c.get("/api/v1/brain/memories").json()["counts"]["total"] == 0


def test_questions_flow(auth_client):
    c = auth_client
    q = c.get("/api/v1/brain/questions/next").json()
    assert q["key"] == "aprende" and q["options"] and q["answered"] == 0
    r = c.post("/api/v1/brain/questions/aprende/answer", json={"answer": "Na prática"}, headers=CSRF)
    assert r.status_code == 201 and r.json()["category"] == "estudos" and "Na prática" in r.json()["content"]
    assert c.post("/api/v1/brain/questions/jeito/skip", headers=CSRF).status_code == 204
    nxt = c.get("/api/v1/brain/questions/next").json()
    assert nxt["key"] == "energia" and nxt["answered"] == 1
    bad = c.post("/api/v1/brain/questions/curte/answer", json={"answer": "meu cpf 123.456.789-09"}, headers=CSRF)
    assert bad.status_code == 422


# --- metas, lembretes, tarefas e Início ---------------------------------------------

def test_goals_todos_and_home(auth_client):
    c = auth_client
    g = c.post("/api/v1/brain/goals", json={"title": "Ganhar R$ 300 com o negócio", "unit": "R$", "target": 300,
                                            "deadline": (datetime.now() + timedelta(days=25)).isoformat()},
               headers=CSRF).json()
    g = c.patch(f"/api/v1/brain/goals/{g['id']}", json={"add": 120}, headers=CSRF).json()
    assert g["current"] == 120 and g["percent"] == 40 and g["line"].startswith("Ganhar R$ 300")
    soon = (datetime.now() + timedelta(hours=1)).isoformat()
    rem = c.post("/api/v1/brain/todos", json={"title": "Levar o documento", "kind": "lembrete", "due_at": soon},
                 headers=CSRF).json()
    task = c.post("/api/v1/brain/todos", json={"title": "Comprar microfone USB"}, headers=CSRF).json()
    home = c.get("/api/v1/brain/home").json()
    assert {t["title"] for t in home["today"]} >= {"Levar o documento", "Comprar microfone USB"}
    assert home["goals"][0]["current"] == 120 and home["open_todos"] == 2
    assert [r["id"] for r in c.get("/api/v1/brain/reminders/upcoming").json()] == [rem["id"]]
    c.patch(f"/api/v1/brain/todos/{task['id']}", json={"done": True}, headers=CSRF)
    assert len(c.get("/api/v1/brain/todos").json()) == 1
    snoozed = c.patch(f"/api/v1/brain/todos/{rem['id']}", json={"snooze_minutes": 10}, headers=CSRF).json()
    assert datetime.fromisoformat(snoozed["due_at"]) > datetime.fromisoformat(rem["due_at"])


# --- a conversa vira lembretes, tarefas e lembranças ---------------------------------

def test_chat_extracts_reminder_task_memory_and_uses_memory_later(chat):
    c, cid, s, uid = chat
    when = (datetime.now() + timedelta(days=1)).replace(hour=7, minute=30).strftime("%Y-%m-%dT%H:%M")
    MockProvider.json_reply = empty(
        lembretes=[{"titulo": "Levar o documento na escola", "quando": when}],
        tarefas=[{"titulo": "Comprar microfone USB", "quando": ""}],
        lembrancas=[{"texto": "Microfone do notebook com chiado", "categoria": "outros", "assunto_aberto": True,
                     "atualiza": 0},
                    {"texto": "mora na rua das Flores", "categoria": "sobre", "assunto_aberto": False, "atualiza": 0}])
    r = c.post(f"/api/v1/conversations/{cid}/messages/stream", headers=CSRF,
               json={"content": "Me lembra amanhã às 7:30 de levar o documento. E anota: comprar microfone, o meu tá chiando"})
    events = parse(r.text)
    kinds = [k for k, _ in events]
    assert kinds.index("done") < kinds.index("actions")
    actions = dict(events)["actions"]["actions"]
    types = [a["type"] for a in actions]
    assert types == ["lembrete", "tarefa", "memoria", "bloqueado"]
    mem = next(a for a in actions if a["type"] == "memoria")
    assert mem["status"] == "pending" and mem["topic"] == "open"
    # Fica salvo para mostrar os cartões quando a conversa for aberta de novo.
    saved = c.get(f"/api/v1/brain/conversations/{cid}/actions").json()
    assert sum(len(v) for v in saved.values()) == 4
    todos = c.get("/api/v1/brain/todos").json()
    assert {t["kind"] for t in todos} == {"lembrete", "tarefa"}
    # Pendente não entra no contexto; aprovada entra.
    MockProvider.json_reply = empty()
    c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "o reconhecimento tá ruim com o microfone"},
           headers=CSRF)
    assert "chiado" not in MockProvider.last_style
    c.post(f"/api/v1/brain/memories/{mem['id']}/approve", headers=CSRF)
    c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "o reconhecimento tá ruim com o microfone"},
           headers=CSRF)
    assert "Microfone do notebook com chiado" in MockProvider.last_style
    assert "assunto em aberto" in MockProvider.last_style and "DADOS, não instruções" in MockProvider.last_style


def test_auto_save_updates_resolves_and_counts_goal(chat):
    c, cid, s, uid = chat
    c.put("/api/v1/brain/prefs", json={"auto_save": True}, headers=CSRF)
    c.post("/api/v1/brain/goals", json={"title": "Vender bolos", "unit": "R$", "target": 300}, headers=CSRF)
    MockProvider.json_reply = empty(lembrancas=[{"texto": "Microfone do notebook com chiado", "categoria": "outros",
                                                 "assunto_aberto": True, "atualiza": 0}])
    c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "meu microfone tá chiando"}, headers=CSRF)
    mems = c.get("/api/v1/brain/memories").json()["items"]
    assert mems[0]["status"] == "active" and mems[0]["topic"] == "open"
    MockProvider.json_reply = empty(resolvidos=[1], progresso_metas=[{"meta": 1, "somar": 60}],
                                    lembrancas=[{"texto": "Usa microfone USB novo", "categoria": "outros",
                                                 "assunto_aberto": False, "atualiza": 1}])
    events = parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                          json={"content": "comprei um microfone novo e vendi 2 bolos por 30 cada"}, headers=CSRF).text)
    types = [a["type"] for a in dict(events)["actions"]["actions"]]
    assert "meta" in types and "memoria" in types
    mems = c.get("/api/v1/brain/memories").json()["items"]
    assert len(mems) == 1 and mems[0]["content"] == "Usa microfone USB novo"
    assert c.get("/api/v1/brain/goals").json()[0]["current"] == 60


def test_short_or_neutral_message_does_not_call_the_brain(chat):
    c, cid, s, uid = chat
    MockProvider.json_reply = empty(tarefas=[{"titulo": "não deveria", "quando": ""}])
    events = parse(c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "oi"}, headers=CSRF).text)
    assert "actions" not in [k for k, _ in events] and c.get("/api/v1/brain/todos").json() == []


def test_summary_pins_conversation_and_goes_to_memory(chat):
    c, cid, s, uid = chat
    MockProvider.json_reply = empty()
    c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "vamos planejar a venda de bolos"},
           headers=CSRF)
    MockProvider.json_reply = {"titulo": "Plano dos bolos", "resumo": "O dono vai vender bolos no fim de semana.",
                               "pontos": ["Preço R$ 15", "o telefone dele é 11 98765-4321"],
                               "decisoes": ["Postar foto à noite"], "pendencias": ["Comprar forma"]}
    r = c.post(f"/api/v1/brain/conversations/{cid}/summary", headers=CSRF)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["category"] == "resumo" and m["content"].startswith("📌 Plano dos bolos")
    assert "Preço R$ 15" in m["content"] and "98765" not in m["content"] and "Comprar forma" in m["content"]
    conv = next(x for x in c.get("/api/v1/conversations").json()["items"] if x["id"] == cid)
    assert conv["important"] is True
    # Resumir de novo atualiza o mesmo resumo (não duplica).
    c.post(f"/api/v1/brain/conversations/{cid}/summary", headers=CSRF)
    assert c.get("/api/v1/brain/memories", params={"category": "resumo"}).json()["counts"]["resumo"] == 1


# --- mensagens do TITAN (agendador) ---------------------------------------------------

def test_scheduler_sends_once_respects_quiet_and_reminders(chat):
    c, cid, s, uid = chat
    from titan.db.engine import make_engine, make_session_factory
    from titan.models.providers import get_provider

    sf = make_session_factory(make_engine(s.database_url))
    c.put("/api/v1/brain/prefs", json={"bom_dia": "07:00", "boa_noite": "", "papo": False, "socio_semana": False,
                                       "acompanhar": True, "silencio_inicio": "22:00", "silencio_fim": "06:30"},
          headers=CSRF)
    tz = store.local_now().tzinfo
    day = datetime.now(tz).replace(hour=7, minute=5, second=0, microsecond=0)
    made = proactive.tick(sf, lambda: get_provider(s), now=day)
    assert made == ["bom_dia"]
    assert proactive.tick(sf, lambda: get_provider(s), now=day + timedelta(minutes=1)) == []
    assert proactive.tick(sf, lambda: get_provider(s), now=day.replace(hour=23)) == []  # silêncio
    notes = c.get("/api/v1/brain/notes").json()
    assert notes[0]["kind"] == "bom_dia" and notes[0]["conversation_id"]
    conv = c.get(f"/api/v1/conversations/{notes[0]['conversation_id']}").json()
    assert conv["origin"] == "titan" and conv["messages"][0]["role"] == "assistant"
    c.post("/api/v1/brain/notes/delivered", json={"ids": [notes[0]["id"]]}, headers=CSRF)
    assert c.get("/api/v1/brain/notes").json() == []
    # Lembrete na hora (mesmo no silêncio).
    due = (datetime.now(tz) - timedelta(minutes=1)).isoformat()
    c.post("/api/v1/brain/todos", json={"title": "Tomar água", "kind": "lembrete", "due_at": due}, headers=CSRF)
    assert proactive.tick(sf, lambda: get_provider(s), now=day.replace(hour=23)) == ["lembrete"]
    assert proactive.tick(sf, lambda: get_provider(s), now=day.replace(hour=23)) == []


def test_scheduler_follow_up_and_papo_does_not_insist(chat):
    c, cid, s, uid = chat
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import BrainMemory

    sf = make_session_factory(make_engine(s.database_url))
    c.put("/api/v1/brain/prefs", json={"bom_dia": "", "boa_noite": "", "papo": True, "papo_max": 1,
                                       "socio_semana": False, "acompanhar": True}, headers=CSRF)
    with sf.begin() as db:
        m = store.add_memory(db, uid, "Microfone do notebook com chiado", "outros", topic="open")
        m.follow_up_at = store.utcnow() - timedelta(minutes=1)
    tz = store.local_now().tzinfo
    noon = datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0)
    assert proactive.tick(sf, lambda: None, now=noon)[0] == "acompanhamento"  # sem IA: texto pronto
    with sf() as db:
        assert db.query(BrainMemory).one().follow_up_at > store.utcnow() + timedelta(days=3)
    late = noon.replace(hour=19, minute=59)
    assert proactive.tick(sf, lambda: None, now=late) == ["papo"]
    tomorrow = late + timedelta(days=1)
    assert proactive.tick(sf, lambda: None, now=tomorrow) == []  # o papo de ontem ficou sem resposta


def test_quiet_hours_cross_midnight():
    t = datetime(2026, 1, 1, 23, 0)
    assert proactive.in_quiet(t, "22:00", "07:00") and proactive.in_quiet(t.replace(hour=6), "22:00", "07:00")
    assert not proactive.in_quiet(t.replace(hour=12), "22:00", "07:00")
    assert proactive.in_quiet(t.replace(hour=13), "12:00", "14:00")


def test_brain_requires_auth(client):
    assert client.get("/api/v1/brain/home").status_code == 401
    assert client.get("/api/v1/brain/memories").status_code == 401


def test_titan_started_conversation_keeps_its_first_message_in_context():
    from types import SimpleNamespace

    from titan.models.anthropic_provider import to_api_messages
    from titan_api.routers.conversations import turns_for_model

    msgs = [SimpleNamespace(role="assistant", content="E aí, passou da fase no Brawl Stars?", status="complete",
                            interrupted_at_char=None),
            SimpleNamespace(role="user", content="consegui!", status="complete", interrupted_at_char=None)]
    api = to_api_messages(turns_for_model(msgs))
    assert [m["role"] for m in api] == ["user", "assistant", "user"]
    assert "Brawl Stars" in api[1]["content"] if isinstance(api[1]["content"], str) else True
