"""Voz local: sessões de reconhecimento incremental e síntese.

Os testes "reais" rodam só se TITAN_TEST_VOICE_MODELS apontar para uma pasta com
'vosk/' (modelo pt) e 'piper/pt_BR-faber-medium.onnx'.
"""

import io
import json
import os
import socket
import wave
from pathlib import Path

import pytest

from tests.conftest import CSRF, build_client, create_user, login

MODELS = os.environ.get("TITAN_TEST_VOICE_MODELS")


class FakeRecognizer:
    def __init__(self):
        self.buf = b""

    def AcceptWaveform(self, pcm):
        self.buf += pcm
        return len(self.buf) >= 64000  # "fim de segmento" a cada ~2 s

    def Result(self):
        self.buf = b""
        return json.dumps({"text": "segmento"})

    def PartialResult(self):
        return json.dumps({"partial": f"parcial {len(self.buf)}"})

    def FinalResult(self):
        return json.dumps({"text": "final"})


@pytest.fixture
def fake_voice(settings, monkeypatch):
    from titan.voice import engines

    monkeypatch.setattr(engines.VoskSTT, "recognizer", lambda self: FakeRecognizer())
    create_user(settings)
    with build_client(settings) as c:
        login(c)
        yield c


def test_status_reports_unavailable_without_models(auth_client):
    st = auth_client.get("/api/v1/voice/status").json()
    by = {e["name"]: e for e in st["engines"]}
    assert by["vosk"]["available"] is False and by["vosk"]["local"] is True
    assert by["piper"]["available"] is False
    assert any("Web Speech" in n for n in st["notes"])


def test_unavailable_engines_fail_explicitly(auth_client):
    r = auth_client.post("/api/v1/voice/stt/sessions", headers=CSRF)
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_unavailable"
    r = auth_client.post("/api/v1/voice/speak", json={"text": "oi"}, headers=CSRF)
    assert r.status_code == 503


def test_incremental_session_partial_then_final(fake_voice):
    c = fake_voice
    sid = c.post("/api/v1/voice/stt/sessions", headers=CSRF).json()["session_id"]
    r = c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=b"\x00" * 32000,
               headers={**CSRF, "Content-Type": "application/octet-stream"})
    assert r.json() == {"text": "parcial 32000", "final": False, "confidence": None, "verdict": "ok"}
    r = c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=b"\x00" * 32000,
               headers={**CSRF, "Content-Type": "application/octet-stream"})
    assert r.json()["text"] == "segmento"
    r = c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF)
    assert r.json() == {"text": "segmento final", "final": True, "confidence": None, "verdict": "ok"}
    # Sessão encerrada: não pode ser reutilizada (evita enviar a mesma fala duas vezes).
    assert c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF).status_code == 404


def test_sessions_are_private_and_limited(settings, monkeypatch):
    from titan.voice import engines

    monkeypatch.setattr(engines.VoskSTT, "recognizer", lambda self: FakeRecognizer())
    create_user(settings, "alice")
    create_user(settings, "bob")
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        sid = a.post("/api/v1/voice/stt/sessions", headers=CSRF).json()["session_id"]
        assert b.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF).status_code == 404
        r = a.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=b"\x00" * (300 * 1024),
                   headers={**CSRF, "Content-Type": "application/octet-stream"})
        assert r.status_code == 413
        a.delete(f"/api/v1/voice/stt/sessions/{sid}", headers=CSRF)
        assert a.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF).status_code == 404


def test_voice_requires_auth_and_csrf(client):
    assert client.get("/api/v1/voice/status").status_code == 401
    assert client.post("/api/v1/voice/speak", json={"text": "x"}).status_code == 403


def test_no_audio_written_to_disk_or_logs(fake_voice, settings):
    c = fake_voice
    sid = c.post("/api/v1/voice/stt/sessions", headers=CSRF).json()["session_id"]
    marker = b"AUDIO-SECRETO-" * 100
    c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=marker,
           headers={**CSRF, "Content-Type": "application/octet-stream"})
    c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF)
    for f in Path(settings.data_dir).rglob("*"):
        if f.is_file():
            assert b"AUDIO-SECRETO" not in f.read_bytes(), f


@pytest.mark.skipif(not MODELS, reason="defina TITAN_TEST_VOICE_MODELS para testar Vosk/Piper reais")
def test_real_round_trip_piper_to_vosk(make_settings, monkeypatch):
    import numpy as np

    from titan.db.migrate import upgrade_head

    s = make_settings(voice_vosk_model_dir=Path(MODELS) / "vosk",
                      voice_piper_model=Path(MODELS) / "piper" / "pt_BR-faber-medium.onnx")
    upgrade_head(s.database_url)
    create_user(s)
    # Nenhuma conexão de rede durante a voz local.
    real_connect = socket.socket.connect
    attempts = []

    def guard(self, addr):
        if self.family in (socket.AF_INET, socket.AF_INET6) and addr[0] not in ("127.0.0.1", "::1"):
            attempts.append(addr)
            raise OSError("rede bloqueada no teste")
        return real_connect(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guard)
    with build_client(s) as c:
        login(c)
        r = c.post("/api/v1/voice/speak", json={"text": "Vamos organizar as tarefas de hoje."},
                   headers=CSRF)
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        with wave.open(io.BytesIO(r.content)) as wf:
            sr, pcm = wf.getframerate(), wf.readframes(wf.getnframes())
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        y = np.interp(np.arange(0, len(x), sr / 16000), np.arange(len(x)), x).astype(np.int16)
        sid = c.post("/api/v1/voice/stt/sessions", headers=CSRF).json()["session_id"]
        raw = y.tobytes()
        for i in range(0, len(raw), 16000):  # pedaços de 0,5 s, como o navegador
            c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=raw[i:i + 16000],
                   headers={**CSRF, "Content-Type": "application/octet-stream"})
        text = c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF).json()["text"]
    assert "tarefas" in text
    assert attempts == []


# --- biblioteca incompatível com o processador não derruba o servidor -----------

def test_library_that_crashes_is_probed_in_a_separate_process(auth_client, tmp_path, monkeypatch):
    """Simula o onnxruntime em CPU sem AVX: importar a biblioteca mata o processo (SIGILL)."""
    import sys

    from titan.voice import engines

    fake = tmp_path / "fakelibs" / "piper"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("import os, signal\nos.kill(os.getpid(), signal.SIGILL)\n")
    monkeypatch.syspath_prepend(str(tmp_path / "fakelibs"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "fakelibs"))
    monkeypatch.setattr(engines, "_PROBE_CACHE", {})

    st = auth_client.get("/api/v1/voice/status")
    assert st.status_code == 200  # este processo (o servidor) continua vivo
    piper = {e["name"]: e for e in st.json()["engines"]}["piper"]
    assert piper["available"] is False and "processador" in piper["detail"]
    r = auth_client.post("/api/v1/voice/speak", json={"text": "oi"}, headers=CSRF)
    assert r.status_code == 503 and "processador" in r.json()["error"]["message"]
    assert auth_client.get("/api/v1/system/status").status_code == 200


def test_probe_reports_missing_and_working_libraries(monkeypatch):
    from titan.voice import engines

    monkeypatch.setattr(engines, "_PROBE_CACHE", {})
    assert engines.probe_import("biblioteca_que_nao_existe_xyz") == (False, engines.NOT_INSTALLED)
    assert engines.probe_import("json") == (True, "")


# --- voz natural on-line (desligada por padrão) ----------------------------------

class _FakeCommunicate:
    calls: list = []

    def __init__(self, text, voice, *, connector=None, connect_timeout=None, receive_timeout=None):
        self.text, self.voice, self.connector = text, voice, connector
        _FakeCommunicate.calls.append(self)

    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"ID3fake-"}
        yield {"type": "audio", "data": b"mp3"}


@pytest.fixture
def online_voice(make_settings, monkeypatch):
    import sys
    import types

    from titan.db.migrate import upgrade_head
    from titan.voice import engines

    mod = types.ModuleType("edge_tts")
    mod.Communicate = _FakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    try:  # aiohttp vem com o edge-tts (extra opcional); sem ele, um substituto mínimo
        import aiohttp  # noqa: F401
    except ImportError:
        fake_http = types.ModuleType("aiohttp")
        fake_http.TCPConnector = lambda family=0: types.SimpleNamespace(_family=family)
        monkeypatch.setitem(sys.modules, "aiohttp", fake_http)
    real_probe = engines.probe_import
    monkeypatch.setattr(engines, "probe_import",
                        lambda m, timeout=60.0: (True, "") if m == "edge_tts" else real_probe(m, timeout))
    _FakeCommunicate.calls = []
    s = make_settings(voice_tts="edge", local_only=False, allow_external_voice=True)
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        yield c


def test_online_voice_speaks_mp3_and_is_marked_external(online_voice):
    c = online_voice
    st = c.get("/api/v1/voice/status").json()
    edge = {e["name"]: e for e in st["engines"]}["edge"]
    assert edge["available"] is True and edge["local"] is False
    assert "Antônio" in edge["detail"] and "Microsoft" in edge["detail"]
    assert any("sai do notebook" in n for n in st["notes"])
    r = c.post("/api/v1/voice/speak", json={"text": "Olá, Luiz."}, headers=CSRF)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3fake-mp3"
    call = _FakeCommunicate.calls[-1]
    assert call.voice == "pt-BR-AntonioNeural" and call.text == "Olá, Luiz."
    assert call.connector is not None and call.connector._family == socket.AF_INET  # IPv4 forçado


def test_online_voice_failure_is_explicit(online_voice, monkeypatch):
    async def broken(self):
        raise OSError("sem internet")
        yield  # pragma: no cover

    monkeypatch.setattr(_FakeCommunicate, "stream", broken)
    r = online_voice.post("/api/v1/voice/speak", json={"text": "oi"}, headers=CSRF)
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_unavailable"
    assert "não respondeu" in r.json()["error"]["message"]


def test_enable_online_voice_command(tmp_path, monkeypatch):
    import sys
    import types

    from titan import cli
    from titan.envfile import read_env
    from titan.voice import engines

    monkeypatch.setattr(engines, "probe_import", lambda m, timeout=60.0: (True, ""))
    monkeypatch.setitem(sys.modules, "edge_tts", types.ModuleType("edge_tts"))
    env = tmp_path / ".env"
    env.write_text("TITAN_AUTH_SECRET=abc\n")
    answers = iter(["antônio", "nao"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["enable-online-voice", "--env-file", str(env)]) == 1
    assert env.read_text() == "TITAN_AUTH_SECRET=abc\n"  # sem AUTORIZO nada muda
    answers = iter(["antônio", "autorizo"])
    assert cli.main(["enable-online-voice", "--env-file", str(env)]) == 0
    v = read_env(env)
    assert (v["TITAN_VOICE_TTS"], v["TITAN_VOICE_EDGE_VOICE"], v["TITAN_ALLOW_EXTERNAL_VOICE"],
            v["TITAN_LOCAL_ONLY"]) == ("edge", "pt-BR-AntonioNeural", "true", "false")
    assert cli.main(["disable-online-voice", "--env-file", str(env)]) == 0
    v = read_env(env)
    assert (v["TITAN_VOICE_TTS"], v["TITAN_ALLOW_EXTERNAL_VOICE"]) == ("piper", "false")


# --- veredito da transcrição (etapa 2 da voz; ver docs/voice-eval.md) -------------

def test_judge_transcript_rules():
    from titan.voice.engines import judge_transcript

    w = lambda *pairs: [{"word": a, "conf": c} for a, c in pairs]
    assert judge_transcript("o", w(("o", 0.99))).verdict == "noise"  # música virou "o" (nota alta!)
    assert judge_transcript("é hum", w(("é", 0.9), ("hum", 0.8))).verdict == "noise"
    assert judge_transcript("sim", w(("sim", 0.6))).verdict == "ok"  # palavra útil curta continua valendo
    t = judge_transcript("ter o maior", w(("ter", 0.39), ("o", 0.27), ("maior", 0.32)))
    assert t.verdict == "unclear" and round(t.confidence, 2) == 0.33
    assert judge_transcript("abre a lista", w(("abre", 0.9), ("a", 0.9), ("lista", 1.0))).verdict == "ok"
    assert judge_transcript("abre a lista", []).verdict == "ok"  # sem notas: não inventa veredito
    assert judge_transcript("", []).verdict == "ok"


class NoiseRecognizer(FakeRecognizer):
    def FinalResult(self):
        return json.dumps({"text": "o", "result": [{"word": "o", "conf": 0.99}]})


def test_finish_reports_verdict_and_confidence(settings, monkeypatch):
    from titan.voice import engines

    monkeypatch.setattr(engines.VoskSTT, "recognizer", lambda self: NoiseRecognizer())
    create_user(settings)
    with build_client(settings) as c:
        login(c)
        sid = c.post("/api/v1/voice/stt/sessions", headers=CSRF).json()["session_id"]
        r = c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF).json()
        assert r == {"text": "o", "final": True, "confidence": 0.99, "verdict": "noise"}
