"""Lembrete na hora, sem IA, no chat do TITAN (mesma regra da Central e da Casa)."""

from datetime import datetime

from tests.conftest import CSRF
from titan.brain.quick import parse_reminder, when_text


def test_parse_reminder_phrases():
    now = datetime(2026, 11, 7, 10, 0).astimezone()
    cases = [
        ("Cria um lembrete pra me avisar de tirar o bolo às 2:30 da tarde", "Tirar o bolo", (7, 14, 30)),
        ("me lembra de ligar pra minha mãe às 14h30", "Ligar minha mãe", (7, 14, 30)),
        ("Ei Titã, me avisa às duas e meia da tarde de buscar o pão", "Buscar o pão", (7, 14, 30)),
        ("lembrete amanhã às 7 horas levar o documento na escola", "Levar o documento na escola", (8, 7, 0)),
        ("me lembra daqui a 10 minutos de desligar o forno", "Desligar o forno", (7, 10, 10)),
        ("me avisa em meia hora de tomar remédio", "Tomar remédio", (7, 10, 30)),
        ("cria um alarme pra meio dia almoçar", "Almoçar", (7, 12, 0)),
        ("me lembra às 9 de comprar o microfone", "Comprar o microfone", (7, 21, 0)),
        ("me lembra às 7 da manhã de acordar cedo", "Acordar cedo", (8, 7, 0)),
    ]
    for text, title, (d, h, m) in cases:
        got = parse_reminder(text, now)
        assert got is not None, text
        assert got[0] == title, (text, got[0])
        assert (got[1].day, got[1].hour, got[1].minute) == (d, h, m), (text, got[1])
    assert parse_reminder("liga o ventilador", now) is None
    assert parse_reminder("me lembra de comprar pão", now) is None   # sem hora: vai para a IA
    # vários pedidos numa mensagem: a IA separa tudo (lembrete + tarefa + memória)
    assert parse_reminder("Me lembra amanhã às 7:30 de levar o documento. E anota: comprar microfone", now) is None
    assert when_text(datetime(2026, 11, 8, 7, 0).astimezone(), now) == "amanhã às 07:00"


def test_chat_creates_reminder_without_ai(auth_client):
    """Sem modelo configurado: o lembrete é criado mesmo assim, e aparece em próximos lembretes."""
    from tests.integration.test_chat_stream import parse

    c = auth_client
    cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    ev = dict(parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                           json={"content": "me lembra daqui a 2 minutos de testar o TITAN"}, headers=CSRF).text))
    assert ev["done"]["message"]["content"].startswith("Lembrete criado: Testar o TITAN, hoje às")
    assert ev["done"]["metrics"]["lembrete"] is True
    ups = c.get("/api/v1/brain/reminders/upcoming").json()
    assert [u["title"] for u in ups] == ["Testar o TITAN"]
    # também pela rota sem streaming (usada pela Central/Casa quando precisa)
    r = c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "me avisa às 8 da noite de estudar"},
               headers=CSRF).json()
    assert r["reply"]["content"].startswith("Lembrete criado: Estudar") and r["model"]["available"] is True
    assert len(c.get("/api/v1/brain/reminders/upcoming").json()) == 2
