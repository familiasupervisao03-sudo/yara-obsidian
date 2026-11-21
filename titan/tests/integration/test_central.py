"""TITAN Central (tela da TV): resumo, telemetria e alertas críticos, clima, "mostra na tela"
e isolamento entre contas."""

import pytest

from tests.conftest import CSRF, TEST_PASSWORD, build_client, create_user, login
from titan.central import telemetry, weather
from titan.central.telemetry import Sample, Sampler, alerts


@pytest.fixture(autouse=True)
def _clean():
    import titan_api.routers.central as r

    r._shown.clear()
    r._sampler.history.clear()
    weather._cache.clear()


def fake_sys(tmp_path, *, cpu_line="cpu 100 0 100 800 0 0 0 0 0 0", temp_milli=55000, bat_temp=None):
    (tmp_path / "proc").mkdir(exist_ok=True)
    (tmp_path / "proc/stat").write_text(cpu_line + "\n")
    (tmp_path / "proc/meminfo").write_text("MemTotal: 4000000 kB\nMemAvailable: 1000000 kB\n")
    p = tmp_path / "proc/4242"
    p.mkdir(exist_ok=True)
    (p / "stat").write_text("4242 (firefox) S 1 1 1 0 -1 0 0 0 0 0 500 100 0 0 20 0 1 0")
    hw = tmp_path / "sys/class/hwmon/hwmon0"
    hw.mkdir(parents=True, exist_ok=True)
    (hw / "name").write_text("coretemp\n")
    (hw / "temp1_input").write_text(f"{temp_milli}\n")
    bat = tmp_path / "sys/class/power_supply/BAT0"
    bat.mkdir(parents=True, exist_ok=True)
    (bat / "capacity").write_text("80\n")
    (bat / "status").write_text("Charging\n")
    if bat_temp is not None:
        (bat / "temp").write_text(f"{bat_temp}\n")


def test_sampler_reads_linux(tmp_path):
    fake_sys(tmp_path)
    s = Sampler(str(tmp_path))
    first = s.sample(now=1)
    assert first.cpu is None and first.mem == 75.0 and first.temp == 55.0 and first.bat_pct == 80 and first.charging
    # 1000 ticks a mais, 200 ociosos → 80% de uso; o firefox foi quem mais usou
    fake_sys(tmp_path, cpu_line="cpu 500 0 500 1000 0 0 0 0 0 0")
    (tmp_path / "proc/4242/stat").write_text("4242 (firefox) S 1 1 1 0 -1 0 0 0 0 0 900 300 0 0 20 0 1 0")
    second = s.sample(now=20)
    assert second.cpu == 80.0 and s.top_process == "firefox"
    assert len(s.history) == 2


def test_sampler_without_sensors(tmp_path):
    (tmp_path / "proc").mkdir()
    s = Sampler(str(tmp_path)).sample()
    assert s.cpu is None and s.mem is None and s.temp is None and s.bat_temp is None


def hist(**series):
    n = max(len(v) for v in series.values())
    return [Sample(at=i, **{k: v[i] if i < len(v) else None for k, v in series.items()}) for i in range(n)]


def test_alerts_only_for_serious_things():
    # temperatura alta só num ponto: ainda não é alerta (pode ser pico)
    assert alerts(hist(temp=[60, 70, 90])) == []
    a = alerts(hist(temp=[60, 88, 91]))
    assert [x["key"] for x in a] == ["temp"] and a[0]["level"] == "crit" and a[0]["history"] == [60, 88, 91]
    # processador: precisa ficar ≥ 90% por 6 pontos seguidos
    assert alerts(hist(cpu=[95] * 5)) == []
    a = alerts(hist(cpu=[95] * 6), top_process="firefox")
    assert a[0]["key"] == "cpu" and "firefox" in a[0]["text"] and a[0]["culprit"] == "firefox"
    # gasto: 90% = atenção (laranja); 100% = crítico
    assert alerts(hist(spend_pct=[50, 92]))[0]["level"] == "warn"
    assert alerts(hist(spend_pct=[100]))[0]["level"] == "crit"
    # carregador puxando energia demais (pela tomada inteligente)
    plug = {"id": "x", "name": "Notebook", "on": True, "watts": 120}
    a = alerts(hist(charger_w=[40, 120]), charger_plug=plug)
    assert a[0]["key"] == "charger" and a[0]["plug"] == plug
    # bateria quente
    assert alerts(hist(bat_temp=[52]))[0]["key"] == "bat"
    # tudo normal
    assert alerts(hist(temp=[50, 52], cpu=[30, 40], spend_pct=[10, 20], charger_w=[40, 41])) == []


def test_weather_parse_and_cache():
    data = {"current": {"temperature_2m": 27.6, "relative_humidity_2m": 60, "weather_code": 61},
            "daily": {"temperature_2m_max": [31.2], "temperature_2m_min": [22.0], "precipitation_probability_max": [70]}}
    out = weather.parse(data, "Fortaleza")
    assert out == {"city": "Fortaleza", "temp": 28, "humidity": 60, "text": "Chuva fraca", "icon": "chuva",
                   "max": 31.2, "min": 22.0, "rain_chance": 70}

    class FakeClient:
        calls = 0

        def get(self, url, params):
            FakeClient.calls += 1

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return data
            return R()

    weather.current(-3.7, -38.5, "Fortaleza", client=FakeClient())
    weather.current(-3.7, -38.5, "Fortaleza", client=FakeClient())
    assert FakeClient.calls == 1  # 20 min em memória


def test_overview_has_the_day(auth_client):
    c = auth_client
    c.post("/api/v1/brain/goals", json={"title": "Juntar R$ 300", "unit": "R$", "target": 300}, headers=CSRF)
    gid = c.get("/api/v1/brain/goals").json()[0]["id"]
    c.patch(f"/api/v1/brain/goals/{gid}", json={"add": 150}, headers=CSRF)
    c.post("/api/v1/brain/todos", json={"title": "Estudar 1 hora"}, headers=CSRF)
    c.post("/api/v1/casa/devices/discover", headers=CSRF)
    plug = next(d for d in c.get("/api/v1/casa/devices?all=1").json() if d["provider_name"] == "Smart Plug 1")
    c.patch(f"/api/v1/casa/devices/{plug['id']}", json={"name": "Ventilador", "icon": "fan", "configured": True}, headers=CSRF)
    c.post(f"/api/v1/casa/devices/{plug['id']}/action", json={"do": "on"}, headers=CSRF)
    o = c.get("/api/v1/central/overview").json()
    assert o["goals"][0]["pct"] == 50 and o["today"][0]["title"] == "Estudar 1 hora"
    assert [d["name"] for d in o["casa"]["devices"]] == ["Ventilador"] and o["casa"]["on"] == 1
    assert o["casa"]["demo"] is True and o["casa"]["last_event"]["device"] == "Ventilador"
    assert o["weather"] is None  # sem cidade configurada
    assert o["show"] is None


def test_show_on_screen_and_isolation(settings):
    create_user(settings)
    create_user(settings, "outra", TEST_PASSWORD)
    with build_client(settings) as a, build_client(settings) as b:
        login(a)
        login(b, "outra")
        r = a.post("/api/v1/central/show", json={"title": "Arco-íris", "text": "A luz se separa nas cores."}, headers=CSRF)
        assert r.status_code == 201
        assert a.get("/api/v1/central/overview").json()["show"]["title"] == "Arco-íris"
        assert b.get("/api/v1/central/overview").json()["show"] is None  # a TV da outra conta não vê
        a.delete("/api/v1/central/show", headers=CSRF)
        assert a.get("/api/v1/central/overview").json()["show"] is None
        assert a.post("/api/v1/central/show", json={"text": ""}, headers=CSRF).status_code == 422


def test_telemetry_only_for_owner(settings, monkeypatch, tmp_path):
    import titan_api.routers.central as r
    from titan.auth.service import AuthService
    from titan.db.engine import make_engine, make_session_factory

    fake_sys(tmp_path, temp_milli=95000)
    monkeypatch.setattr(r, "_sampler", Sampler(str(tmp_path)))
    monkeypatch.setattr(telemetry, "SAMPLE_EVERY_S", 0)
    create_user(settings)
    engine = make_engine(settings.database_url)
    with make_session_factory(engine).begin() as db:
        AuthService.create_user(db, "visita", TEST_PASSWORD, role="member")
    engine.dispose()
    with build_client(settings) as owner, build_client(settings) as member:
        login(owner)
        login(member, "visita")
        t1 = owner.get("/api/v1/central/telemetry").json()
        assert t1["available"] is True and t1["now"]["temp"] == 95.0 and t1["alerts"] == []  # 1 ponto só
        t2 = owner.get("/api/v1/central/telemetry").json()
        assert [a["key"] for a in t2["alerts"]] == ["temp"]
        assert member.get("/api/v1/central/telemetry").json() == {"available": False, "alerts": []}


def test_central_needs_login(client):
    assert client.get("/api/v1/central/overview").status_code == 401
    assert client.get("/api/v1/central/telemetry").status_code == 401
    assert client.post("/api/v1/central/show", json={"text": "x"}, headers=CSRF).status_code == 401


def test_central_page_served(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>titan</html>")
    (dist / "central.html").write_text("<html>central</html>")
    s = settings.model_copy(update={"web_dist_dir": dist})
    with build_client(s) as c:
        assert "central" in c.get("/central").text
        assert "titan" in c.get("/").text


def test_settings_central_coords_validated(settings):
    from pydantic import ValidationError

    from titan.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="test", auth_secret="x" * 64, central_lat=200)
