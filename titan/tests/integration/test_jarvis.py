"""Funções do Jarvis: clima (aviso de chuva), chegada/saída de casa e protocolos.

Sem internet (Open-Meteo falso) e com a casa de demonstração. Cada conta só vê e só mexe no que é seu.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import CSRF, build_client, create_user, login
from tests.integration.test_casa import setup_home

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)   # 13h no horário de Brasília


def forecast(rain_at_local_hour=14, prob=80):
    times, probs, temps, codes = [], [], [], []
    start = datetime(2026, 11, 21, 0, 0)
    for i in range(72):
        t = start + timedelta(hours=i)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        hit = t.day == 21 and t.hour == rain_at_local_hour
        probs.append(prob if hit else 5)
        temps.append(31.0 if 9 <= t.hour <= 16 else 25.0)
        codes.append(63 if hit else 2)
    return {
        "utc_offset_seconds": -10800, "timezone": "America/Fortaleza",
        "current": {"temperature_2m": 31.2, "weather_code": 2},
        "hourly": {"time": times, "precipitation_probability": probs, "temperature_2m": temps, "weather_code": codes},
        "daily": {"time": ["2026-11-21", "2026-11-22", "2026-11-23"], "weather_code": [63, 2, 0],
                  "temperature_2m_max": [33.0, 32.0, 31.0], "temperature_2m_min": [24.0, 24.5, 23.0],
                  "precipitation_probability_max": [80, 30, 0]},
    }


CITY = {"name": "Cidade Teste", "admin1": "Estado", "country": "Brasil", "lat": -3.7, "lon": -38.5}


def fake_fetch(url):
    if url.startswith("https://geocoding-api.open-meteo.com/"):
        return json.dumps({"results": [{"name": "Cidade Teste", "admin1": "Estado", "country": "Brasil",
                                        "latitude": -3.7, "longitude": -38.5}]})
    if url.startswith("https://api.open-meteo.com/"):
        return json.dumps(forecast())
    raise OSError("fora do ar")


def _sf(settings):
    from titan.db.engine import make_engine, make_session_factory

    engine = make_engine(settings.database_url)
    return engine, make_session_factory(engine)


def test_resumo_do_clima_e_chuva_em_breve():
    from titan.jarvis import weather

    s = weather.summary(forecast(), NOW, CITY, NOW.isoformat())
    assert s["now"] == {"temp": 31.2, "text": "Sol com nuvens", "emoji": "⛅"}
    assert s["source"] == "Open-Meteo" and s["days"][1]["weekday"] == "domingo"
    when, prob = weather.rain_soon(forecast(), NOW)
    assert (when.hour, prob) == (14, 80)
    assert s["tip"].startswith("🌧️ Chuva por volta das 14h00 (80%")
    assert weather.rain_soon(forecast(prob=40), NOW) is None, "chance baixa não vira aviso"
    ctx = weather.context_block(forecast(), CITY, "Titã, vai chover amanhã?", NOW, NOW.isoformat())
    assert "Open-Meteo" in ctx and "domingo 22/11" in ctx and "NUNCA invente" in ctx
    assert weather.context_block(forecast(), CITY, "liga o ventilador", NOW, None) == ""
    assert "não escolheu a cidade" in weather.context_block(None, None, "vai chover?", NOW, None)


def test_aviso_de_chuva_uma_vez_e_so_de_quem_escolheu_cidade(settings):
    from titan.db.models import TitanNote, User
    from titan.jarvis import service, state

    create_user(settings, "alice")
    create_user(settings, "bob")
    engine, sf = _sf(settings)
    with sf.begin() as db:
        alice = db.query(User).filter_by(username="alice").one().id
        state.save(db, alice, {"place": CITY})
    r = service.tick(settings, sf, fake_fetch, now=NOW)
    assert r == {"clima": 1, "chuva": 1}
    assert service.tick(settings, sf, fake_fetch, now=NOW + timedelta(minutes=5))["chuva"] == 0, "não repete"
    with sf() as db:
        notes = db.query(TitanNote).filter_by(kind="clima").all()
        assert len(notes) == 1 and notes[0].user_id == alice
        assert notes[0].title == "TITAN · Chuva em 1 hora, senhor"
        assert "80% de chance, segundo o Open-Meteo" in notes[0].body
    with sf.begin() as db:  # aviso desligado: nada
        state.save(db, alice, {"rain_alert": False, "rain_alerted": ""})
    assert service.tick(settings, sf, fake_fetch, now=NOW + timedelta(minutes=10))["chuva"] == 0
    engine.dispose()


def test_cidade_e_clima_pela_api_cada_conta_a_sua(settings):
    create_user(settings, "alice")
    create_user(settings, "bob")
    with build_client(settings) as a, build_client(settings) as b:
        a.app.state.ctx.jarvis_fetch = fake_fetch
        b.app.state.ctx.jarvis_fetch = fake_fetch
        login(a, "alice")
        login(b, "bob")
        assert a.get("/api/v1/jarvis/weather").json() == {"place": None}
        found = a.get("/api/v1/jarvis/places?q=Cidade").json()
        assert found[0]["name"] == "Cidade Teste"
        assert a.put("/api/v1/jarvis/place", json=found[0], headers=CSRF).json()["place"]["name"] == "Cidade Teste"
        w = a.get("/api/v1/jarvis/weather").json()
        assert w["place"]["name"] == "Cidade Teste" and w["now"]["temp"] == 31.2 and len(w["days"]) == 3
        assert b.get("/api/v1/jarvis/weather").json() == {"place": None}, "a cidade da alice não é do bob"
        assert b.get("/api/v1/jarvis/settings").json()["place"] is None


def test_chegada_e_saida(auth_client, settings):
    from titan.db.models import NewsStory, TitanNote, User
    from titan.jarvis import state

    c = auth_client
    devs = setup_home(c)
    vent, luz = devs["Ventilador"]["id"], devs["Luz do quarto"]["id"]
    c.post(f"/api/v1/casa/devices/{vent}/action", json={"do": "on"}, headers=CSRF)
    for other in ("Luz do quarto", "Notebook"):
        c.post(f"/api/v1/casa/devices/{devs[other]['id']}/action", json={"do": "off"}, headers=CSRF)
    # primeira vez: só aprende onde o celular está, sem mensagem
    assert c.post("/api/v1/jarvis/presence", json={"state": "home"}, headers=CSRF).json()["note"] == ""
    r = c.post("/api/v1/jarvis/presence", json={"state": "away"}, headers=CSRF).json()
    assert r["changed"] and "Ficaram ligados: " in r["note"] and "Ventilador" in r["note"] and "Luz" not in r["note"]
    assert c.post("/api/v1/jarvis/presence", json={"state": "away"}, headers=CSRF).json()["changed"] is False
    assert [d["name"] for d in c.get("/api/v1/jarvis/leave").json()] == ["Ventilador"]
    off = c.post("/api/v1/jarvis/leave/off", json={"device_ids": [vent]}, headers=CSRF).json()
    assert off == [{"name": "Ventilador", "ok": True, "detail": "desligado"}]
    assert c.get("/api/v1/jarvis/leave").json() == []
    # chegou: boas-vindas SEM ligar nada (o dono ainda não cadastrou o que ligar)
    r = c.post("/api/v1/jarvis/presence", json={"state": "home"}, headers=CSRF).json()
    assert r["ran"] == [] and r["note"] == "Bem-vindo de volta, senhor. Tudo tranquilo por aqui."
    assert c.get("/api/v1/jarvis/leave").json() == []
    # o dono cadastra "ligar ao chegar"
    c.put("/api/v1/jarvis/settings", json={"arrive_steps": [{"device_id": luz, "do": "on"}]}, headers=CSRF)
    c.post("/api/v1/jarvis/presence", json={"state": "away"}, headers=CSRF)
    r = c.post("/api/v1/jarvis/presence", json={"state": "home"}, headers=CSRF).json()
    assert r["ran"] == [{"name": "Luz do quarto", "ok": True, "detail": "acesa"}]
    assert r["note"].startswith("Bem-vindo de volta, senhor. Liguei: Luz do quarto.")
    engine, sf = _sf(settings)
    with sf() as db:
        kinds = [n.kind for n in db.query(TitanNote).all()]
        assert kinds.count("casa") == 3
    engine.dispose()


def test_ninguem_desliga_aparelho_de_outra_conta(settings):
    create_user(settings, "alice")
    create_user(settings, "bob")
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        vent = setup_home(a)["Ventilador"]["id"]
        a.post(f"/api/v1/casa/devices/{vent}/action", json={"do": "on"}, headers=CSRF)
        r = b.post("/api/v1/jarvis/leave/off", json={"device_ids": [vent]}, headers=CSRF).json()
        assert r[0]["ok"] is False and r[0]["name"] == "Aparelho removido"
        bad = b.put("/api/v1/jarvis/protocols/dormir", headers=CSRF,
                    json={"name": "Dormir", "steps": [{"device_id": vent, "do": "off"}], "quiet_until": "07:00"})
        assert bad.status_code == 200 and bad.json()["lines"] == ["Avisos de notícias → silenciar até 07:00"]
        run = b.post("/api/v1/jarvis/protocols/dormir/run", headers=CSRF).json()
        assert run["results"][0] == {"name": "Aparelho removido", "ok": False, "detail": "não está mais no TITAN Casa"}
        assert [d["on"] for d in a.get("/api/v1/jarvis/devices").json() if d["id"] == vent] == [True]
        assert b.get("/api/v1/jarvis/devices").json() == []


def test_protocolos_editar_executar_silenciar_e_lousa(auth_client, settings):
    c = auth_client
    devs = setup_home(c)
    vent, luz, tv = devs["Ventilador"]["id"], devs["Luz do quarto"]["id"], devs["TV"]["id"]
    ps = c.get("/api/v1/jarvis/protocols").json()
    assert [p["name"] for p in ps] == ["Dormir", "Festa", "Filme", "Acordar", "Lousa Limpa"]
    assert ps[1]["summary"] == "Nenhum aparelho escolhido ainda."
    lousa = next(p for p in ps if p["id"] == "lousa")
    assert lousa["special"] == "all_off" and len(lousa["lines"]) == 5
    p = c.put("/api/v1/jarvis/protocols/dormir", headers=CSRF, json={
        "name": "Dormir", "emoji": "🌙", "quiet_until": "07:00",
        "steps": [{"device_id": luz, "do": "off"}, {"device_id": vent, "do": "on"}]}).json()
    assert p["lines"] == ["Luz do quarto → desligar", "Ventilador → ligar", "Avisos de notícias → silenciar até 07:00"]
    r = c.post("/api/v1/jarvis/protocols/dormir/run", headers=CSRF).json()
    assert r["text"] == "Protocolo Dormir concluído. Boa noite, senhor."
    assert [x["ok"] for x in r["results"]] == [True, True, True]
    assert c.get("/api/v1/jarvis/settings").json()["quiet_until"]
    # com as notícias caladas, notícia importante não apita (fica só na aba)
    from titan.db.models import User
    from titan.jarvis import service

    engine, sf = _sf(settings)
    with sf() as db:
        uid = db.query(User).one().id
        assert service.news_quiet(db, uid, datetime.now(timezone.utc)) is True
    engine.dispose()
    # Lousa Limpa desliga tudo
    r = c.post("/api/v1/jarvis/protocols/lousa/run", headers=CSRF).json()
    assert all(x["ok"] for x in r["results"]) and len(r["results"]) == 5
    assert not any(d["on"] for d in c.get("/api/v1/jarvis/devices").json())
    # protocolo novo, editar, apagar; os que vêm com o TITAN não se apagam
    n = c.post("/api/v1/jarvis/protocols", headers=CSRF,
               json={"name": "Estudar", "emoji": "📚", "steps": [{"device_id": tv, "do": "off"}]})
    assert n.status_code == 201 and n.json()["custom"] is True
    assert c.post("/api/v1/jarvis/protocols", headers=CSRF, json={"name": "estudar"}).status_code == 422
    assert c.delete("/api/v1/jarvis/protocols/lousa", headers=CSRF).status_code == 422
    assert c.delete(f"/api/v1/jarvis/protocols/{n.json()['id']}", headers=CSRF).status_code == 204
    assert c.delete("/api/v1/jarvis/protocols/p-nao-existe", headers=CSRF).status_code == 404


def test_protocolo_pela_conversa_pergunta_antes_e_executa_no_sim(auth_client):
    from tests.integration.test_chat_stream import parse

    c = auth_client
    devs = setup_home(c)
    vent = devs["Ventilador"]["id"]
    c.post(f"/api/v1/casa/devices/{vent}/action", json={"do": "on"}, headers=CSRF)
    c.put("/api/v1/jarvis/protocols/dormir", headers=CSRF,
          json={"name": "Dormir", "steps": [{"device_id": vent, "do": "off"}], "quiet_until": ""})
    cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]

    def say(text):
        return dict(parse(c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": text},
                                 headers=CSRF).text))

    ev = say("Titã, protocolo dormir")
    assert ev["done"]["message"]["content"].startswith("Pois não, senhor. O Protocolo Dormir vai:\n• Ventilador → desligar")
    assert ev["actions"]["actions"][0]["type"] == "protocolo"
    assert [d["on"] for d in c.get("/api/v1/jarvis/devices").json() if d["id"] == vent] == [True], "ainda não executou"
    ev = say("sim")
    assert ev["done"]["message"]["content"] == "Protocolo Dormir concluído. Boa noite, senhor."
    assert ev["actions"]["actions"][0]["type"] == "protocolo_feito"
    assert [d["on"] for d in c.get("/api/v1/jarvis/devices").json() if d["id"] == vent] == [False]
    ev = say("protocolo foguete")
    assert ev["done"]["message"]["content"].startswith('Não encontrei o protocolo "foguete", senhor.')
    ev = say("protocolo festa")
    assert "ainda não tem aparelhos" in ev["done"]["message"]["content"]


@pytest.mark.parametrize("text", ["sim", "pode"])
def test_sim_sem_protocolo_pendente_nao_executa_nada(auth_client, text):
    from titan.jarvis import service

    assert service._YES.match(text)
    c = auth_client
    cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    r = c.post(f"/api/v1/conversations/{cid}/messages", json={"content": text}, headers=CSRF).json()
    assert r["reply"] is None or "Protocolo" not in r["reply"]["content"]
