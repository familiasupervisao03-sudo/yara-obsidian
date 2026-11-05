"""TITAN Casa: cadastro, comandos, cenas, voz, isolamento entre casas e conector Tuya."""

import hashlib
import hmac
import json
import uuid

import pytest

from tests.conftest import CSRF, TEST_PASSWORD, build_client, create_user, login
from titan.casa import providers, service


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import titan_api.routers.casa as r

    monkeypatch.setattr(r.time, "sleep", lambda s: None)
    service._recent.clear()
    r._providers.clear()


def setup_home(c):
    """Procura (demonstração) e cadastra os 5 aparelhos com nomes de verdade."""
    res = c.post("/api/v1/casa/devices/discover", headers=CSRF).json()
    assert res == {"found": 5, "new": 5}
    devs = {d["provider_name"]: d for d in c.get("/api/v1/casa/devices?all=1").json()}
    names = {"Smart Bulb": ("Luz do quarto", "light", "luz, luz do quarto"),
             "Smart Plug 1": ("Ventilador", "fan", "ventilador, ventinho"),
             "Smart Plug 2": ("Notebook", "laptop", "notebook, computador"),
             "IR Remote · TV": ("TV", "tv", "tv, televisão"),
             "IR Remote · AC": ("Ar-condicionado", "ac", "ar, ar-condicionado")}
    out = {}
    for pname, (name, icon, alias) in names.items():
        d = c.patch(f"/api/v1/casa/devices/{devs[pname]['id']}", headers=CSRF,
                    json={"name": name, "icon": icon, "aliases": alias, "configured": True}).json()
        out[name] = d
    return out


def test_discover_register_and_act(auth_client):
    c = auth_client
    st = c.get("/api/v1/casa/status").json()
    assert st["provider"] == "demo" and st["devices"] == 0 and st["linked"] is True
    c.post("/api/v1/casa/devices/discover", headers=CSRF)
    assert c.get("/api/v1/casa/devices").json() == []  # novos não aparecem no painel
    assert c.get("/api/v1/casa/status").json()["new"] == 5
    assert c.post("/api/v1/casa/devices/discover", headers=CSRF).json()["new"] == 0  # não duplica
    c.post("/api/v1/casa/devices/discover", headers=CSRF)
    all_ = c.get("/api/v1/casa/devices?all=1").json()
    plug = next(d for d in all_ if d["provider_name"] == "Smart Plug 1")
    d = c.patch(f"/api/v1/casa/devices/{plug['id']}", headers=CSRF,
                json={"name": "Ventilador", "icon": "fan", "kind": "fan", "aliases": "ventilador, ventinho ,",
                      "configured": True}).json()
    assert d["name"] == "Ventilador" and d["kind"] == "fan" and d["aliases"] == "ventilador, ventinho"
    assert len(c.get("/api/v1/casa/devices").json()) == 1
    r = c.post(f"/api/v1/casa/devices/{plug['id']}/action", json={"do": "toggle"}, headers=CSRF).json()
    assert r["state"]["on"] is False
    r = c.post(f"/api/v1/casa/devices/{plug['id']}/identify", headers=CSRF).json()
    assert r["state"]["on"] is False  # piscou e voltou como estava
    ev = c.get("/api/v1/casa/events").json()
    assert ev[0]["device"] == "Ventilador" and ev[0]["source"] == "toque" and len(ev) == 5
    assert c.patch(f"/api/v1/casa/devices/{plug['id']}", json={"icon": "bomba"}, headers=CSRF).status_code == 422
    tv = next(d for d in all_ if d["infrared"] and d["kind"] == "tv")
    assert c.post(f"/api/v1/casa/devices/{tv['id']}/identify", headers=CSRF).status_code == 422
    assert c.post(f"/api/v1/casa/devices/{plug['id']}/action", json={"do": "ac", "ac_temp": 20},
                  headers=CSRF).status_code == 422  # ventilador não é ar


def test_light_ac_and_tv_controls(auth_client):
    c = auth_client
    d = setup_home(c)
    luz, ar, tv = d["Luz do quarto"]["id"], d["Ar-condicionado"]["id"], d["TV"]["id"]
    assert c.post(f"/api/v1/casa/devices/{luz}/action", json={"do": "bright", "value": 30}, headers=CSRF).json()["state"]["bright"] == 30
    assert c.post(f"/api/v1/casa/devices/{luz}/action", json={"do": "white", "value": "frio"}, headers=CSRF).json()["state"]["white"] == "frio"
    st = c.post(f"/api/v1/casa/devices/{ar}/action", json={"do": "ac", "ac_temp": 22, "ac_mode": "secar", "ac_fan": 3},
                headers=CSRF).json()["state"]
    assert st == {"on": True, "ac_temp": 22, "ac_mode": "secar", "ac_fan": 3}
    assert c.post(f"/api/v1/casa/devices/{tv}/action", json={"do": "key", "value": "power"}, headers=CSRF).json()["state"]["on"] is True
    assert c.post(f"/api/v1/casa/devices/{tv}/action", json={"do": "key", "value": "rm -rf"}, headers=CSRF).status_code == 422


def test_scenes_crud_and_run(auth_client):
    c = auth_client
    d = setup_home(c)
    body = {"name": "Estudar", "phrases": "modo estudo, vou estudar", "reply": "Modo estudo ligado.",
            "actions": [{"device_id": d["Luz do quarto"]["id"], "action": "on"},
                        {"device_id": d["TV"]["id"], "action": "off"},
                        {"device_id": d["Ar-condicionado"]["id"], "action": "on", "ac_temp": 23}]}
    s = c.post("/api/v1/casa/scenes", json=body, headers=CSRF).json()
    assert s["name"] == "Estudar" and len(s["actions"]) == 3
    r = c.post(f"/api/v1/casa/scenes/{s['id']}/run", headers=CSRF).json()
    assert r["reply"] == "Modo estudo ligado." and r["kind"] == "scene" and len(r["undo"]) == 3
    devs = {x["name"]: x for x in c.get("/api/v1/casa/devices").json()}
    assert devs["Ar-condicionado"]["state"]["ac_temp"] == 23 and devs["TV"]["state"]["on"] is False
    body["name"] = "Estudo"
    assert c.put(f"/api/v1/casa/scenes/{s['id']}", json=body, headers=CSRF).json()["name"] == "Estudo"
    # Esquecer um aparelho tira ele das cenas.
    c.delete(f"/api/v1/casa/devices/{d['TV']['id']}", headers=CSRF)
    assert len(c.get("/api/v1/casa/scenes").json()[0]["actions"]) == 2
    assert c.delete(f"/api/v1/casa/scenes/{s['id']}", headers=CSRF).status_code == 204
    assert c.get("/api/v1/casa/scenes").json() == []


def test_voice_commands(auth_client):
    c = auth_client
    d = setup_home(c)
    c.post("/api/v1/casa/scenes", headers=CSRF, json={
        "name": "Sair", "phrases": "vou sair, saindo", "reply": "Tudo desligado. Até mais!",
        "actions": [{"device_id": x["id"], "action": "off"} for x in d.values()]})
    say = lambda t, **kw: c.post("/api/v1/casa/command", json={"text": t, **kw}, headers=CSRF).json()
    r = say("Ei Titã, desliga a luz do quarto")
    assert r["kind"] == "device" and r["reply"] == "Luz do quarto desligada." and r["device"]["state"]["on"] is False
    assert r["undo"][0]["action"] == {"do": "bright", "value": 70}
    assert say("liga o ventinho")["reply"] == "Ventilador ligado."
    assert say("põe o ar em 19")["reply"] == "Ar-condicionado em 19 graus."
    assert say("luz em 30%")["device"]["state"]["bright"] == 30
    assert say("aumenta o volume")["reply"] == "Aumentei o volume."
    assert say("como está o notebook?")["kind"] == "ask"
    assert say("liga")["kind"] == "which"
    assert say("qual a capital da França")["understood"] is False
    assert say("Ei Titã")["kind"] == "wake"
    assert say("desliga a luz antes de sair")["kind"] == "device"  # nome da cena no meio não roda a cena
    r = say("Titã, vou sair")
    assert r["kind"] == "scene" and r["reply"] == "Tudo desligado. Até mais!"
    assert c.get("/api/v1/casa/status").json()["on"] == 0
    assert say("liga a luz", require_wake=True)["kind"] == "ignored"  # escuta contínua: sem "Ei Titã", ignora
    assert say("ei titã liga a luz", require_wake=True)["kind"] == "device"
    assert say("liga tudo")["reply"] == "Liguei tudo."


def test_homes_are_isolated(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings()
    upgrade_head(s.database_url)
    create_user(s, "luiz")
    create_user(s, "outro")
    with build_client(s) as a, build_client(s) as b:
        login(a, "luiz")
        login(b, "outro")
        d = setup_home(a)
        luz = d["Luz do quarto"]["id"]
        assert b.get("/api/v1/casa/devices?all=1").json() == []
        assert b.post(f"/api/v1/casa/devices/{luz}/action", json={"do": "off"}, headers=CSRF).status_code == 404
        assert b.patch(f"/api/v1/casa/devices/{luz}", json={"name": "Hackeado"}, headers=CSRF).status_code == 404
        assert b.delete(f"/api/v1/casa/devices/{luz}", headers=CSRF).status_code == 404
        r = b.post("/api/v1/casa/scenes", headers=CSRF,
                   json={"name": "x", "actions": [{"device_id": luz, "action": "off"}]})
        assert r.status_code == 422
        assert b.post("/api/v1/casa/command", json={"text": "desliga a luz do quarto"}, headers=CSRF).json()["kind"] == "which"
        assert a.get(f"/api/v1/casa/devices").json()[0]["state"]["on"] is True  # nada mudou na casa do Luiz


def test_rate_limit(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(casa_max_commands_per_minute=5)
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        d = setup_home(c)
        luz = d["Luz do quarto"]["id"]
        codes = [c.post(f"/api/v1/casa/devices/{luz}/action", json={"do": "toggle"}, headers=CSRF).status_code
                 for _ in range(6)]
        assert codes == [200] * 5 + [429]


def test_casa_requires_auth(client):
    assert client.get("/api/v1/casa/devices").status_code == 401
    assert client.post("/api/v1/casa/command", json={"text": "liga"}, headers=CSRF).status_code == 401


# --- conector Tuya (sem rede: uma "Tuya" de mentira confere assinatura e comandos) ---

class FakeTuya:
    def __init__(self, uids=("uid-luiz",)):
        self.calls = []
        self.uids = uids

    def __call__(self, method, url, headers, body):
        path = url.split("openapi.tuyaus.com", 1)[1]
        self.calls.append((method, path, headers, json.loads(body) if body else None))
        # confere a assinatura como a Tuya faria
        token = headers.get("access_token", "")
        sts = "\n".join([method, hashlib.sha256(body.encode()).hexdigest(), "", path])
        expected = hmac.new(b"segredo", (headers["client_id"] + token + headers["t"] + headers["nonce"] + sts).encode(),
                            hashlib.sha256).hexdigest().upper()
        if headers["sign"] != expected:
            return {"success": False, "code": 1004, "msg": "sign invalid"}
        if path.startswith("/v1.0/token"):
            return {"success": True, "result": {"access_token": "tok123", "expire_time": 7200}}
        if path.startswith("/v1.0/iot-01/associated-users/devices"):
            devs = [{"id": "plug1", "name": "Smart Plug 1", "category": "cz", "online": True, "uid": self.uids[0],
                     "status": [{"code": "switch_1", "value": True}, {"code": "cur_power", "value": 380}]},
                    {"id": "bulb1", "name": "Smart Bulb", "category": "dj", "online": True, "uid": self.uids[-1],
                     "status": [{"code": "switch_led", "value": False}, {"code": "bright_value_v2", "value": 500},
                                {"code": "temp_value_v2", "value": 900}]},
                    {"id": "ir1", "name": "IR Hub", "category": "wnykq", "online": True, "uid": self.uids[0], "status": []}]
            return {"success": True, "result": {"devices": devs, "has_more": False}}
        if path == "/v2.0/infrareds/ir1/remotes":
            return {"success": True, "result": [{"remote_id": "rtv", "remote_name": "TV Samsung", "category_id": 2},
                                                {"remote_id": "rac", "remote_name": "Ar LG", "category_id": 5}]}
        if method == "POST":
            return {"success": True, "result": True}
        return {"success": False, "code": 404, "msg": "?"}


def test_tuya_lists_signs_and_sends_commands():
    fake = FakeTuya()
    p = providers.TuyaProvider("idteste", "segredo", "us", http=fake)
    found = {d.provider_id: d for d in p.list_devices(None)}
    assert set(found) == {"plug1", "bulb1", "rtv", "rac"}  # o hub IR vira TV e ar
    assert found["plug1"].kind == "plug" and found["plug1"].state == {"on": True, "watts": 38.0}
    assert found["bulb1"].state == {"on": False, "bright": 50, "white": "frio"}
    assert found["rac"].kind == "ac" and found["rac"].parent_id == "ir1" and found["rtv"].kind == "tv"

    class Dev:
        def __init__(self, r):
            self.provider_id, self.parent_id, self.kind, self.meta, self.state = r.provider_id, r.parent_id, r.kind, r.meta, r.state

    p.act(Dev(found["plug1"]), {"do": "off"})
    assert fake.calls[-1][1] == "/v1.0/devices/plug1/commands"
    assert fake.calls[-1][3] == {"commands": [{"code": "switch_1", "value": False}]}
    p.act(Dev(found["bulb1"]), {"do": "bright", "value": 30})
    assert fake.calls[-1][3]["commands"][1] == {"code": "bright_value_v2", "value": 300}
    st = p.act(Dev(found["rac"]), {"do": "ac", "on": True, "ac_temp": 22, "ac_mode": "frio", "ac_fan": 2})
    assert fake.calls[-1][1] == "/v2.0/infrareds/ir1/air-conditioners/rac/scenes/command"
    assert fake.calls[-1][3] == {"power": 1, "mode": 0, "temp": 22, "wind": 2} and st["ac_temp"] == 22
    p.act(Dev(found["rtv"]), {"do": "key", "value": "vol_up"})
    assert fake.calls[-1][3] == {"category_id": 2, "key": "Volume+"}
    # o token foi pedido uma vez só e reaproveitado
    assert sum(1 for c in fake.calls if c[1].startswith("/v1.0/token")) == 1


def test_tuya_refuses_mixing_two_accounts(make_settings, monkeypatch):
    from titan.db.migrate import upgrade_head
    import titan_api.routers.casa as r

    s = make_settings(casa_provider="tuya", local_only=False, tuya_access_id="idteste", tuya_access_secret="segredo")
    upgrade_head(s.database_url)
    create_user(s)
    fake = FakeTuya(uids=("uid-luiz", "uid-outra-pessoa"))
    monkeypatch.setattr(r, "provider_for", lambda settings: providers.TuyaProvider("idteste", "segredo", "us", http=fake))
    with build_client(s) as c:
        login(c)
        res = c.post("/api/v1/casa/devices/discover", headers=CSRF)
        assert res.status_code == 409 and "mais de uma conta" in res.json()["error"]["message"]
        assert c.get("/api/v1/casa/devices?all=1").json() == []
    fake.uids = ("uid-luiz",)
    r._providers.clear()
    with build_client(s) as c:
        login(c)
        assert c.post("/api/v1/casa/devices/discover", headers=CSRF).json()["found"] == 4
        assert c.get("/api/v1/casa/status").json()["linked"] is True


def test_tuya_requires_authorization_settings(make_settings):
    from titan.config.settings import ConfigurationError

    with pytest.raises((ConfigurationError, ValueError)):
        make_settings(casa_provider="tuya", tuya_access_id="x", tuya_access_secret="y")  # local_only=true
    with pytest.raises((ConfigurationError, ValueError)):
        make_settings(casa_provider="tuya", local_only=False)  # sem credenciais


def test_main_titan_chat_controls_the_house(auth_client):
    """Mesma mãe: no chat do TITAN, 'liga o ventilador' liga (sem IA); perguntas seguem para a IA."""
    from tests.integration.test_chat_stream import parse

    c = auth_client
    d = setup_home(c)
    cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    c.post(f"/api/v1/casa/devices/{d['Ventilador']['id']}/action", json={"do": "off"}, headers=CSRF)
    ev = dict(parse(c.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "liga o ventinho"},
                           headers=CSRF).text))
    assert ev["done"]["message"]["content"] == "Ventilador ligado." and ev["done"]["metrics"]["casa"] is True
    assert next(x for x in c.get("/api/v1/casa/devices").json() if x["name"] == "Ventilador")["state"]["on"] is True
    # pergunta sobre o assunto não é comando: vai para a IA (aqui, sem modelo → erro de IA, não ação)
    ev = dict(parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                           json={"content": "como eu ligo o ventilador mais rápido?"}, headers=CSRF).text))
    assert "error" in ev and ev["error"]["reason"] == "no_model"
    assert c.get("/api/v1/casa/events").json()[0]["source"] == "chat"
