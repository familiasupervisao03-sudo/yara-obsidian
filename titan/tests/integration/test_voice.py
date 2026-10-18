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
    assert r.json() == {"text": "parcial 32000", "final": False}
    r = c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", content=b"\x00" * 32000,
               headers={**CSRF, "Content-Type": "application/octet-stream"})
    assert r.json()["text"] == "segmento"
    r = c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", headers=CSRF)
    assert r.json() == {"text": "segmento final", "final": True}
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
