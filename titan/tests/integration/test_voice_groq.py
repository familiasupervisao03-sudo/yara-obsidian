"""Reconhecimento on-line pela Groq: autorização, envio só ao terminar, reserva no Vosk."""

import json
import math
import struct
import uuid

import pytest

from titan.voice import engines

GROQ = dict(voice_stt="groq", local_only=False, allow_external_voice=True, groq_api_key="gsk_teste")


class FakeRec:
    def AcceptWaveform(self, pcm):
        return False

    def PartialResult(self):
        return json.dumps({"partial": "parcial vosk"})

    def FinalResult(self):
        return json.dumps({"text": "texto do vosk"})


def speech(seconds=1.5, amp=3000):
    n = int(16000 * seconds)
    return struct.pack(f"<{n}h", *(int(amp * math.sin(i / 8)) for i in range(n)))


def groq_reply(text="Olá TITAN, qual é a previsão do tempo?", no_speech=0.01):
    return {"text": text, "segments": [{"avg_logprob": -0.1, "no_speech_prob": no_speech}]}


def make(make_settings, monkeypatch, post, vosk=True, **kw):
    s = make_settings(**{**GROQ, **kw})
    if vosk:
        monkeypatch.setattr(engines.VoskSTT, "recognizer", lambda self: FakeRec())
    else:
        def missing(self):
            raise engines.VoiceUnavailable("sem vosk")
        monkeypatch.setattr(engines.VoskSTT, "recognizer", missing)
    svc = engines.VoiceService(s)
    svc.cloud_stt._post = post
    return svc


def run(svc, pcm):
    uid = uuid.uuid4()
    sid = svc.sessions.open(uid)
    partial = svc.sessions.feed(sid, uid, pcm)
    return partial, svc.sessions.finish(sid, uid)


def test_groq_requires_explicit_authorization(make_settings):
    from titan.config.settings import ConfigurationError

    with pytest.raises((ConfigurationError, ValueError)) as e:
        make_settings(voice_stt="groq", groq_api_key="gsk_x")
    assert "Groq" in str(e.value)
    with pytest.raises((ConfigurationError, ValueError)):
        make_settings(voice_stt="groq", local_only=False, allow_external_voice=True)  # sem chave
    assert make_settings(**GROQ).public_view()["groq_api_key_configured"] is True
    assert "gsk_teste" not in json.dumps(make_settings(**GROQ).public_view(), default=str)


def test_groq_transcribes_once_at_the_end_without_live_vosk(make_settings, monkeypatch):
    sent = []
    svc = make(make_settings, monkeypatch, lambda wav: sent.append(wav) or groq_reply())
    partial, t = run(svc, speech())
    assert partial == ""  # com a Groq, o Vosk não roda ao vivo (poupa o processador do notebook)
    assert t.engine == "groq" and t.verdict == "ok" and t.text.startswith("Olá TITAN")
    assert len(sent) == 1 and sent[0][:4] == b"RIFF"
    assert svc.cloud_stt.used_today() == 10  # mínimo cobrado por fala
    assert svc.status()[0].name == "groq"


def test_silence_is_not_sent(make_settings, monkeypatch):
    svc = make(make_settings, monkeypatch, lambda wav: pytest.fail("não deveria enviar silêncio"))
    assert run(svc, speech(amp=0))[1].verdict == "noise"
    assert run(svc, speech(seconds=0.2))[1].verdict == "noise"


def test_whisper_hallucination_on_noise_is_ignored(make_settings, monkeypatch):
    svc = make(make_settings, monkeypatch, lambda wav: groq_reply("Legendas pela comunidade Amara.org"))
    assert run(svc, speech())[1].verdict == "noise"
    svc = make(make_settings, monkeypatch, lambda wav: groq_reply("bla", no_speech=0.9))
    assert run(svc, speech())[1].verdict == "noise"


def test_falls_back_to_vosk_when_groq_fails(make_settings, monkeypatch):
    def boom(wav):
        raise OSError("sem internet")

    svc = make(make_settings, monkeypatch, boom)
    t = run(svc, speech())[1]
    assert t.engine == "vosk" and t.text == "texto do vosk"


def test_daily_cap_falls_back_to_vosk(make_settings, monkeypatch):
    svc = make(make_settings, monkeypatch, lambda wav: groq_reply(), voice_cloud_max_minutes_day=1)
    engines_used = [run(svc, speech())[1].engine for _ in range(8)]
    assert engines_used[:6] == ["groq"] * 6 and engines_used[6:] == ["vosk", "vosk"]


def test_works_without_vosk_and_reports_failure(make_settings, monkeypatch):
    svc = make(make_settings, monkeypatch, lambda wav: groq_reply("Bom dia"), vosk=False)
    partial, t = run(svc, speech())
    assert partial == "" and t.text == "Bom dia"

    def boom(wav):
        raise engines.VoiceUnavailable("A Groq respondeu 500; usando o Vosk.")

    svc = make(make_settings, monkeypatch, boom, vosk=False)
    with pytest.raises(engines.VoiceUnavailable):
        run(svc, speech())


def test_real_http_request_shape(make_settings, monkeypatch):
    """Sem rede: confere o pedido montado para a API da Groq."""
    httpx = pytest.importorskip("httpx")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, json=groq_reply("Funcionou"))

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    svc = make(make_settings, monkeypatch, None, network_force_ipv4=False)
    t = run(svc, speech())[1]
    assert t.text == "Funcionou"
    assert seen["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer gsk_teste"
    assert b"whisper-large-v3-turbo" in seen["body"] and b'name="language"' in seen["body"]


def test_cli_enable_and_disable(tmp_path, monkeypatch):
    from titan import cli

    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\nTITAN_VOICE_TTS=edge\n")
    answers = iter(["60", "AUTORIZO"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "gsk_abc")
    assert cli.main(["enable-groq-stt", "--env-file", str(env)]) == 0
    text = env.read_text()
    assert "TITAN_VOICE_STT=groq" in text and "GROQ_API_KEY=gsk_abc" in text
    assert "TITAN_ALLOW_EXTERNAL_VOICE=true" in text and "TITAN_LOCAL_ONLY=false" in text
    assert cli.main(["disable-groq-stt", "--env-file", str(env)]) == 0
    text = env.read_text()
    assert "TITAN_VOICE_STT=vosk" in text and "GROQ_API_KEY" not in text
    assert "TITAN_ALLOW_EXTERNAL_VOICE=true" in text  # a voz on-line (edge) continua autorizada


XAI = dict(voice_stt="xai", local_only=False, allow_external_voice=True, xai_api_key="xai-teste")


def test_xai_requires_its_own_key(make_settings):
    from titan.config.settings import ConfigurationError

    with pytest.raises((ConfigurationError, ValueError)) as e:
        make_settings(voice_stt="xai", local_only=False, allow_external_voice=True, groq_api_key="gsk_x")
    assert "XAI_API_KEY" in str(e.value)
    assert make_settings(**XAI).public_view()["xai_api_key_configured"] is True


def test_xai_request_shape_and_fallback(make_settings, monkeypatch):
    httpx = pytest.importorskip("httpx")
    seen = {}
    status = {"code": 200}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(status["code"], json={"text": "Abre a aula de física", "language": "pt",
                                                    "duration": 1.5, "words": []})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    s = make_settings(**XAI, network_force_ipv4=False)
    monkeypatch.setattr(engines.VoskSTT, "recognizer", lambda self: FakeRec())
    svc = engines.VoiceService(s)
    assert svc.status()[0].name == "xai"
    t = run(svc, speech())[1]
    assert t.engine == "xai" and t.text == "Abre a aula de física"
    assert seen["url"] == "https://api.x.ai/v1/stt" and seen["auth"] == "Bearer xai-teste"
    body = seen["body"]
    assert b"grok-voice-transcribe-2.0" in body and b'name="language"' in body
    assert body.index(b'name="file"') > body.index(b'name="model"')  # arquivo por último
    status["code"] = 401
    t = run(svc, speech())[1]
    assert t.engine == "vosk" and t.text == "texto do vosk"


def test_cli_enable_and_disable_xai(tmp_path, monkeypatch):
    from titan import cli

    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\n")
    answers = iter(["30", "AUTORIZO"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "xai-abc")
    assert cli.main(["enable-xai-stt", "--env-file", str(env)]) == 0
    text = env.read_text()
    assert "TITAN_VOICE_STT=xai" in text and "XAI_API_KEY=xai-abc" in text
    assert "TITAN_VOICE_CLOUD_MAX_MINUTES_DAY=30" in text
    assert cli.main(["disable-xai-stt", "--env-file", str(env)]) == 0
    text = env.read_text()
    assert "TITAN_VOICE_STT=vosk" in text and "XAI_API_KEY" not in text
    assert "TITAN_ALLOW_EXTERNAL_VOICE=false" in text


def test_fallback_explains_itself(make_settings, monkeypatch):
    def boom(wav):
        raise engines.VoiceUnavailable("A Groq respondeu 400 (formato inválido); usando o Vosk.")

    svc = make(make_settings, monkeypatch, boom)
    t = run(svc, speech())[1]
    assert t.engine == "vosk" and "400" in t.note


def test_cli_testar_voz_with_file(tmp_path, monkeypatch, capsys):
    import wave

    from titan import cli
    from titan.config.settings import get_settings

    wav = tmp_path / "fala.wav"
    with wave.open(str(wav), "wb") as w:  # 44,1 kHz estéreo: o comando converte
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        mono = speech(seconds=1.0)
        n = len(mono) // 2
        samples = struct.unpack(f"<{n}h", mono)
        w.writeframes(struct.pack(f"<{n * 2}h", *(x for v in samples for x in (v, v))))
    for k, v in {"TITAN_ENV": "test", "TITAN_VOICE_STT": "groq", "TITAN_LOCAL_ONLY": "false",
                 "TITAN_ALLOW_EXTERNAL_VOICE": "true", "GROQ_API_KEY": "gsk_t",
                 "TITAN_AUTH_SECRET": "x" * 64}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    sent = []
    monkeypatch.setattr(engines.GroqSTT, "_send", lambda self, data: sent.append(data) or groq_reply("Capital da Austrália"))
    try:
        assert cli.main(["testar-voz", "--arquivo", str(wav)]) == 0
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert "Groq:" in out and "Capital da Austrália" in out
    with wave.open(__import__("io").BytesIO(sent[0])) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and abs(w.getnframes() - 16000 * 16000 // 44100) <= 2


def test_vocabulary_hint_goes_to_groq_and_live_vosk_optional(make_settings, monkeypatch):
    """A dica (nomes dos aparelhos) vai junto do áudio; Vosk ao vivo só se pedir."""
    got = []
    svc = make(make_settings, monkeypatch, lambda wav, hint="": got.append(hint) or groq_reply())
    uid = uuid.uuid4()
    sid = svc.sessions.open(uid, "Ei, Titã. Liga o Nootebook.")
    svc.sessions.feed(sid, uid, speech())
    svc.sessions.finish(sid, uid)
    assert got == ["Ei, Titã. Liga o Nootebook."]
    assert "prompt" in svc.cloud_stt._form("x") and "prompt" not in svc.cloud_stt._form()
    svc = make(make_settings, monkeypatch, lambda wav: groq_reply(), voice_local_partials=True)
    assert run(svc, speech())[0] == "parcial vosk"


def test_vosk_hears_everything_when_groq_fails_without_live(make_settings, monkeypatch):
    """Sem Vosk ao vivo, se a Groq falhar o Vosk ouve a fala inteira no final (reserva)."""
    def boom(wav):
        raise OSError("sem internet")

    svc = make(make_settings, monkeypatch, boom)
    partial, t = run(svc, speech())
    assert partial == "" and t.engine == "vosk" and t.text == "texto do vosk" and "Groq" in t.note
