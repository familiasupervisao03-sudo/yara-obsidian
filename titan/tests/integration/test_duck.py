"""Abaixar o som do notebook enquanto fala com o TITAN ("ducking") e devolver depois."""

from tests.conftest import CSRF, TEST_PASSWORD, build_client, create_user, login
from titan.voice import duck as duckmod
from titan.voice.duck import Ducker, parse_sink_inputs

SAMPLE = """Sink Input #41
\tDriver: protocol-native.c
\tCorked: no
\tMute: no
\tVolume: front-left: 65536 /  100% / 0.00 dB,   front-right: 52429 /  80% / -5.81 dB
\tProperties:
\t\tapplication.name = "Spotify"
\t\tapplication.process.id = "1000"

Sink Input #42
\tCorked: yes
\tVolume: front-left: 65536 /  100% / 0.00 dB,   front-right: 65536 /  100% / 0.00 dB
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.id = "2000"
"""


def test_parse_sink_inputs():
    a, b = parse_sink_inputs(SAMPLE)
    assert (a.index, a.corked, a.volumes, a.pid, a.app) == (41, False, [65536, 52429], 1000, "Spotify")
    assert b.corked is True and b.app == "Firefox"
    assert parse_sink_inputs("") == []


class FakePulse:
    """Servidor de som de mentira: guarda o volume de cada programa."""

    def __init__(self, inputs):
        self.inputs = inputs  # índice -> dict(corked, vol, pid, app)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["list", "sink-inputs"]:
            out = []
            for i, d in self.inputs.items():
                vols = ",   ".join(f"ch{n}: {v} / {round(v / 655.36)}% / 0 dB" for n, v in enumerate(d["vol"]))
                out.append(f"Sink Input #{i}\n\tCorked: {'yes' if d['corked'] else 'no'}\n\tVolume: {vols}\n"
                           f"\tProperties:\n\t\tapplication.name = \"{d['app']}\"\n"
                           f"\t\tapplication.process.id = \"{d['pid']}\"\n")
            return "\n".join(out)
        if args[0] == "set-sink-input-volume":
            self.inputs[int(args[1])]["vol"] = [int(v) for v in args[2:]]
        return ""


def test_duck_lowers_playing_and_restores(tmp_path):
    pulse = FakePulse({7: {"corked": False, "vol": [65536, 65536], "pid": 10, "app": "Spotify"},
                       8: {"corked": True, "vol": [65536], "pid": 11, "app": "Firefox"}})
    d = Ducker(20, tmp_path / "apps", run=pulse, proc=tmp_path)
    assert d.duck("pagina-1") == 1                      # só o que está tocando
    assert pulse.inputs[7]["vol"] == [13107, 13107]     # 20%
    assert pulse.inputs[8]["vol"] == [65536]            # pausado: não mexe
    # a voz do TITAN começa a tocar DEPOIS: renovar não pode abaixá-la
    pulse.inputs[9] = {"corked": False, "vol": [65536], "pid": 12, "app": "Firefox"}
    assert d.duck("pagina-1") == 0
    assert pulse.inputs[9]["vol"] == [65536]
    assert d.release("pagina-1") == 1
    assert pulse.inputs[7]["vol"] == [65536, 65536] and not d.active


def test_duck_respects_user_change_and_multiple_holders(tmp_path):
    pulse = FakePulse({7: {"corked": False, "vol": [50000], "pid": 10, "app": "VLC"}})
    d = Ducker(20, tmp_path / "apps", run=pulse, proc=tmp_path)
    d.duck("central-abc")
    d.duck("celular-xyz")
    assert d.release("central-abc") == 0               # o outro ainda está falando
    assert pulse.inputs[7]["vol"] == [10000]
    pulse.inputs[7]["vol"] = [30000]                    # você mexeu no volume no meio
    assert d.release("celular-xyz") == 0               # então fica como você pôs
    assert pulse.inputs[7]["vol"] == [30000]


def test_titan_app_sound_never_lowered(tmp_path):
    # app do TITAN aberto pelo ícone: pid 500; o som sai de um processo filho (pid 501)
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "central.pid").write_text("500")
    proc = tmp_path / "proc"
    for pid, ppid in ((501, 500), (500, 1), (10, 1)):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "stat").write_text(f"{pid} (x) S {ppid} 0 0")
    pulse = FakePulse({1: {"corked": False, "vol": [65536], "pid": 501, "app": "Firefox"},
                       2: {"corked": False, "vol": [65536], "pid": 10, "app": "Spotify"}})
    d = Ducker(20, apps, run=pulse, proc=proc)
    assert d.duck("central-xyz") == 1
    assert pulse.inputs[1]["vol"] == [65536] and pulse.inputs[2]["vol"] == [13107]


def test_volume_comes_back_alone_if_page_disappears(tmp_path, monkeypatch):
    monkeypatch.setattr(duckmod, "HOLD_S", 0.0)
    pulse = FakePulse({7: {"corked": False, "vol": [65536], "pid": 10, "app": "Spotify"}})
    d = Ducker(20, tmp_path / "apps", run=pulse, proc=tmp_path)
    d.duck("sumiu-123")
    d._timer.cancel()
    d._expire()                                          # o prazo acabou sem renovação
    assert pulse.inputs[7]["vol"] == [65536] and not d.active


def test_duck_route_owner_only(settings, monkeypatch):
    import titan_api.routers.voice as vr

    pulse = FakePulse({3: {"corked": False, "vol": [65536], "pid": 10, "app": "Spotify"}})
    monkeypatch.setattr(Ducker, "available", staticmethod(lambda: True))
    monkeypatch.setattr(vr, "_ducker", Ducker(20, settings.data_dir / "apps", run=pulse))
    create_user(settings)
    from titan.auth.service import AuthService
    from titan.db.engine import make_engine, make_session_factory

    engine = make_engine(settings.database_url)
    with make_session_factory(engine).begin() as db:
        AuthService.create_user(db, "visita", TEST_PASSWORD, role="member")
    engine.dispose()
    with build_client(settings) as owner, build_client(settings) as member:
        login(owner)
        login(member, "visita")
        r = member.post("/api/v1/voice/duck", json={"on": True, "holder": "visita-1"}, headers=CSRF).json()
        assert r == {"available": False, "active": False, "changed": 0}
        assert pulse.inputs[3]["vol"] == [65536]       # visita não mexe no som da máquina
        r = owner.post("/api/v1/voice/duck", json={"on": True, "holder": "dono-111"}, headers=CSRF).json()
        assert r == {"available": True, "active": True, "changed": 1}
        r = owner.post("/api/v1/voice/duck", json={"on": False, "holder": "dono-111"}, headers=CSRF).json()
        assert r["active"] is False and pulse.inputs[3]["vol"] == [65536]
        assert owner.post("/api/v1/voice/duck", json={"on": True, "holder": "x y"}, headers=CSRF).status_code == 422


def test_duck_route_without_pactl(auth_client, monkeypatch):
    monkeypatch.setattr(Ducker, "available", staticmethod(lambda: False))
    r = auth_client.post("/api/v1/voice/duck", json={"on": True, "holder": "abcdef"}, headers=CSRF).json()
    assert r == {"available": False, "active": False, "changed": 0}
