"""Mecanismos de voz opcionais.

* Reconhecimento de fala: Vosk (local, modelo pequeno de português, ~52 MB) ou, se o
  usuário autorizar, o reconhecimento on-line da Groq (Whisper) ou da xAI (Grok) — nesse caso o ÁUDIO da fala sai do
  notebook (só ao terminar cada fala; o Vosk continua mostrando o texto parcial e
  assume sozinho se a Groq falhar).
* Síntese de voz: Piper (local, voz pt_BR, ~63 MB) ou, se o usuário autorizar,
  a voz natural on-line da Microsoft (edge-tts) — nesse caso o TEXTO das
  respostas sai do notebook.

Cada biblioteca é testada primeiro num processo separado (``probe_import``):
bibliotecas nativas compiladas para processadores mais novos (ex.: que exigem
AVX) derrubam o processo com "instrução ilegal", e isso não pode derrubar o
servidor. Os mecanismos são carregados sob demanda, uma única vez, e ficam
indisponíveis (com motivo explícito) se algo faltar.
Áudio é processado em memória e nunca gravado em disco ou em logs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import signal
import subprocess
import sys
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from titan.config.settings import Settings

log = logging.getLogger("titan.voice")

SAMPLE_RATE = 16_000  # PCM 16 bits mono enviado pelo navegador


class VoiceUnavailable(Exception):
    pass


NOT_INSTALLED = "not_installed"
_PROBE_CACHE: dict[str, tuple[bool, str]] = {}
_PROBE_LOCK = threading.Lock()


def probe_import(module: str, timeout: float = 60.0) -> tuple[bool, str]:
    """Testa ``import module`` num processo separado (resultado guardado).

    Retorna (ok, motivo). O motivo é ``NOT_INSTALLED`` quando a biblioteca não existe.
    """
    with _PROBE_LOCK:
        if module not in _PROBE_CACHE:
            _PROBE_CACHE[module] = _run_probe(module, timeout)
        return _PROBE_CACHE[module]


def _run_probe(module: str, timeout: float) -> tuple[bool, str]:
    if importlib.util.find_spec(module) is None:
        return False, NOT_INSTALLED
    try:
        proc = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"A biblioteca '{module}' demorou demais para carregar."
    if proc.returncode == 0:
        return True, ""
    if proc.returncode == -signal.SIGILL:
        log.warning("Biblioteca %s incompatível com este processador (SIGILL)", module)
        return False, (f"O processador deste computador não suporta a biblioteca '{module}' "
                       "(instrução ilegal: ela exige instruções mais novas, como AVX). "
                       "O TITAN continua funcionando; só este mecanismo de voz fica desligado.")
    if proc.returncode < 0:
        return False, f"A biblioteca '{module}' encerrou o processo de teste (sinal {-proc.returncode})."
    last = proc.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["erro desconhecido"]
    return False, f"A biblioteca '{module}' não pôde ser carregada: {last[0][:200]}"


@dataclass
class EngineStatus:
    name: str
    kind: str  # stt | tts
    available: bool
    local: bool
    detail: str


class VoskSTT:
    name = "vosk"

    def __init__(self, settings: Settings) -> None:
        self.model_dir = Path(settings.voice_vosk_model_dir).expanduser()
        self._model: Any = None
        self._lock = threading.Lock()

    def status(self) -> EngineStatus:
        ok, why = probe_import("vosk")
        if not ok:
            return EngineStatus(self.name, "stt", False, True,
                                "Biblioteca 'vosk' não instalada (sh scripts/install_voice_local.sh)."
                                if why == NOT_INSTALLED else why)
        # Modelos pequenos têm final.mdl na raiz; os grandes, em am/.
        if not any((self.model_dir / p).is_file() for p in ("final.mdl", "am/final.mdl")):
            return EngineStatus(self.name, "stt", False, True,
                                f"Modelo de português não encontrado em {self.model_dir}.")
        return EngineStatus(self.name, "stt", True, True,
                            "Reconhecimento local (Vosk, português). O áudio não sai do notebook.")

    def recognizer(self) -> Any:
        st = self.status()
        if not st.available:
            raise VoiceUnavailable(st.detail)
        with self._lock:
            if self._model is None:
                from vosk import Model, SetLogLevel

                SetLogLevel(-1)
                started = time.monotonic()
                self._model = Model(str(self.model_dir))
                log.info("Vosk carregado em %.1fs", time.monotonic() - started)
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(self._model, SAMPLE_RATE)
        rec.SetWords(True)  # nota de confiança por palavra
        return rec


class PiperTTS:
    name = "piper"
    media_type = "audio/wav"

    def __init__(self, settings: Settings) -> None:
        self.model_path = Path(settings.voice_piper_model).expanduser()
        self._voice: Any = None
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()  # uma síntese por vez (CPU modesta)

    def status(self) -> EngineStatus:
        ok, why = probe_import("piper")
        if not ok:
            return EngineStatus(self.name, "tts", False, True,
                                "Biblioteca 'piper-tts' não instalada (sh scripts/install_voice_local.sh)."
                                if why == NOT_INSTALLED else why)
        if not self.model_path.is_file():
            return EngineStatus(self.name, "tts", False, True,
                                f"Voz pt_BR não encontrada em {self.model_path}.")
        return EngineStatus(self.name, "tts", True, True,
                            "Voz local (Piper, pt_BR). O texto não sai do notebook.")

    def synthesize(self, text: str, rate: int = 0) -> bytes:
        """``rate``: % da velocidade normal (-30 a 30), das preferências do usuário."""
        st = self.status()
        if not st.available:
            raise VoiceUnavailable(st.detail)
        with self._lock:
            if self._voice is None:
                from piper import PiperVoice

                started = time.monotonic()
                self._voice = PiperVoice.load(str(self.model_path))
                log.info("Piper carregado em %.1fs", time.monotonic() - started)
        buf = io.BytesIO()
        with self._synth_lock, wave.open(buf, "wb") as wf:
            if hasattr(self._voice, "synthesize_wav"):
                kwargs = {}
                if rate:
                    from piper import SynthesisConfig

                    kwargs["syn_config"] = SynthesisConfig(length_scale=1 / (1 + rate / 100))
                self._voice.synthesize_wav(text, wf, **kwargs)
            else:  # API antiga do piper-tts
                self._voice.synthesize(text, wf)
        return buf.getvalue()


EDGE_VOICE_LABEL = {"pt-BR-AntonioNeural": "Antônio", "pt-BR-FranciscaNeural": "Francisca",
                    "pt-BR-ThalitaMultilingualNeural": "Thalita"}


class EdgeTTS:
    """Voz natural ON-LINE (Microsoft, via edge-tts). O texto sai do notebook.

    Só é usada com TITAN_VOICE_TTS=edge e TITAN_ALLOW_EXTERNAL_VOICE=true. É um
    serviço gratuito da Microsoft sem garantia: pode mudar ou parar sem aviso.
    """

    name = "edge"
    media_type = "audio/mpeg"
    TIMEOUT_SECONDS = 30

    def __init__(self, settings: Settings) -> None:
        self.voice = settings.voice_edge_voice
        self.force_ipv4 = settings.network_force_ipv4

    def status(self) -> EngineStatus:
        ok, why = probe_import("edge_tts")
        if not ok:
            return EngineStatus(self.name, "tts", False, False,
                                "Biblioteca 'edge-tts' não instalada (sh scripts/enable_online_voice.sh)."
                                if why == NOT_INSTALLED else why)
        label = EDGE_VOICE_LABEL.get(self.voice, self.voice)
        return EngineStatus(self.name, "tts", True, False,
                            f"Voz natural on-line ({label}, Microsoft). O texto das respostas é "
                            "enviado à Microsoft para virar áudio.")

    def synthesize(self, text: str, rate: int = 0) -> bytes:
        """``rate``: % da velocidade normal (-30 a 30), das preferências do usuário."""
        st = self.status()
        if not st.available:
            raise VoiceUnavailable(st.detail)
        import asyncio
        import socket

        import aiohttp
        import edge_tts

        async def run() -> bytes:
            # IPv4 forçado: em redes com IPv6 quebrado a conexão ficaria esperando.
            connector = aiohttp.TCPConnector(family=socket.AF_INET) if self.force_ipv4 else None
            com = edge_tts.Communicate(text, self.voice, rate=f"{rate:+d}%", connector=connector,
                                       connect_timeout=10, receive_timeout=20)
            chunks = [c["data"] async for c in com.stream() if c["type"] == "audio"]
            return b"".join(chunks)

        try:
            audio = asyncio.run(asyncio.wait_for(run(), timeout=self.TIMEOUT_SECONDS))
        except Exception as exc:  # rede, serviço fora do ar ou resposta inesperada
            log.warning("Voz on-line falhou: %s", type(exc).__name__)
            raise VoiceUnavailable("A voz on-line não respondeu (sem internet ou serviço "
                                   "indisponível). Tente de novo ou escolha outra voz.") from exc
        if not audio:
            raise VoiceUnavailable("A voz on-line não devolveu áudio.")
        return audio


class GroqSTT:
    """Reconhecimento ON-LINE (Whisper na Groq). O áudio da fala sai do notebook.

    Só é usado com TITAN_VOICE_STT=groq, TITAN_ALLOW_EXTERNAL_VOICE=true e GROQ_API_KEY.
    Cada fala é enviada uma vez, ao terminar, como WAV em memória (nada vai para o disco).
    """

    name = "groq"
    company = "Groq"
    label = "Whisper, Groq"
    URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    TIMEOUT_SECONDS = 20
    MIN_BILLED_SECONDS = 10  # a Groq cobra no mínimo 10 s por pedido
    # Frases que o Whisper costuma "inventar" com silêncio ou ruído.
    HALLUCINATIONS = ("legendas pela comunidade", "amara.org", "obrigado por assistir",
                      "inscreva-se no canal", "legenda adriana zanotto", "transcrição por")

    def __init__(self, settings: Settings, post: Any = None) -> None:
        self.key, self.model = self._credentials(settings)
        self.max_seconds_day = settings.voice_cloud_max_minutes_day * 60
        self.force_ipv4 = settings.network_force_ipv4
        self._post = post  # injeção para testes
        self._lock = threading.Lock()
        self._day = ""
        self._used = 0.0

    def _credentials(self, settings: Settings) -> tuple[str, str]:
        return settings.groq_api_key.get_secret_value().strip(), settings.voice_groq_model

    def _form(self, hint: str = "") -> dict:
        form = {"model": self.model, "language": "pt", "temperature": "0",
                "response_format": "verbose_json"}
        if hint:
            # "dica" do Whisper: palavras que devem aparecer (nomes dos aparelhos, "Titã"...).
            # Melhora muito o acerto de nomes próprios. Só texto, nada pessoal além disso.
            form["prompt"] = hint[:600]
        return form

    def _parse(self, data: dict) -> tuple[str, list[float], Optional[float]]:
        """Devolve (texto, probabilidades de 'não é fala' por trecho, confiança)."""
        import math

        segs = [x for x in data.get("segments") or [] if isinstance(x, dict)]
        logprobs = [float(x["avg_logprob"]) for x in segs if "avg_logprob" in x]
        conf = round(math.exp(sum(logprobs) / len(logprobs)), 3) if logprobs else None
        return str(data.get("text", "")), [float(x.get("no_speech_prob", 0)) for x in segs], conf

    def status(self) -> EngineStatus:
        if not self.key:
            return EngineStatus(self.name, "stt", False, False, f"Chave da {self.company} não configurada.")
        return EngineStatus(self.name, "stt", True, False,
                            f"Reconhecimento on-line ({self.label}). O áudio de cada fala é enviado "
                            f"à {self.company}. Hoje: {self.used_today() / 60:.0f} de "
                            f"{self.max_seconds_day // 60} min.")

    def used_today(self) -> float:
        with self._lock:
            return self._used if self._day == time.strftime("%Y-%m-%d") else 0.0

    def _reserve(self, seconds: float) -> None:
        billed = max(seconds, self.MIN_BILLED_SECONDS, 1.0)
        with self._lock:
            today = time.strftime("%Y-%m-%d")
            if self._day != today:
                self._day, self._used = today, 0.0
            if self._used + billed > self.max_seconds_day:
                raise VoiceUnavailable(f"Limite diário de minutos da {self.company} atingido; usando o Vosk.")
            self._used += billed

    def _send(self, wav: bytes, hint: str = "") -> dict:
        if self._post is not None:
            return self._post(wav) if not hint else self._post(wav, hint)
        import httpx

        transport = httpx.HTTPTransport(local_address="0.0.0.0") if self.force_ipv4 else None
        with httpx.Client(timeout=self.TIMEOUT_SECONDS, transport=transport) as client:
            r = client.post(self.URL, headers={"Authorization": f"Bearer {self.key}"},
                            # httpx põe os campos antes do arquivo (a xAI exige o arquivo por último).
                            data=self._form(hint), files={"file": ("fala.wav", wav, "audio/wav")})
        if r.status_code == 429:
            raise VoiceUnavailable(f"Limite da {self.company} atingido por agora; usando o Vosk.")
        if r.status_code in (401, 403):
            raise VoiceUnavailable(f"A {self.company} recusou a chave; usando o Vosk.")
        if r.status_code != 200:
            detail = ""
            try:
                detail = str(r.json().get("error", {}).get("message", ""))[:160]
            except Exception:
                pass
            raise VoiceUnavailable(f"A {self.company} respondeu {r.status_code}"
                                   + (f" ({detail})" if detail else "") + "; usando o Vosk.")
        return r.json()

    def transcribe(self, pcm: bytes, hint: str = "") -> Transcript:
        seconds = len(pcm) / (SAMPLE_RATE * 2)
        self._reserve(seconds)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        try:
            data = self._send(buf.getvalue(), hint) if hint else self._send(buf.getvalue())
        except VoiceUnavailable:
            raise
        except Exception as exc:  # rede, tempo esgotado, resposta inesperada
            log.warning("%s falhou: %s: %s", self.company, type(exc).__name__, str(exc)[:200])
            raise VoiceUnavailable(f"A {self.company} não respondeu (sem internet?); usando o Vosk.") from exc
        raw, no_speech, conf = self._parse(data if isinstance(data, dict) else {})
        text = " ".join(raw.split())
        low = text.lower()
        if not text or (no_speech and min(no_speech) > 0.6) or any(h in low for h in self.HALLUCINATIONS):
            return Transcript("", None, "noise", self.name)
        return Transcript(text, conf, judge_transcript(text, []).verdict, self.name)


class XaiSTT(GroqSTT):
    """Reconhecimento ON-LINE da xAI (Grok Speech to Text). O áudio da fala sai do notebook."""

    name = "xai"
    company = "xAI"
    label = "Grok, xAI"
    URL = "https://api.x.ai/v1/stt"
    MIN_BILLED_SECONDS = 0

    def _credentials(self, settings: Settings) -> tuple[str, str]:
        return settings.xai_api_key.get_secret_value().strip(), settings.voice_xai_model

    def _form(self, hint: str = "") -> dict:  # a xAI não aceita dica de vocabulário
        return {"model": self.model, "language": "pt", "format": "true"}

    def _parse(self, data: dict) -> tuple[str, list[float], Optional[float]]:
        return str(data.get("text", "")), [], None


def speech_level(pcm: bytes) -> float:
    """Volume médio (RMS) do PCM 16 bits; serve para não enviar silêncio à Groq."""
    from array import array

    a = array("h")
    a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder == "big":
        a.byteswap()
    if not a:
        return 0.0
    step = max(1, len(a) // 40_000)
    sample = a[::step]
    return (sum(x * x for x in sample) / len(sample)) ** 0.5


MIN_SPEECH_SECONDS = 0.4
MIN_SPEECH_LEVEL = 80.0


@dataclass
class SttSession:
    id: str
    user_id: uuid.UUID
    recognizer: Any  # Vosk (texto parcial e reserva); None se o Vosk não estiver instalado
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    bytes_received: int = 0
    finals: list[str] = field(default_factory=list)  # segmentos já finalizados pelo Vosk
    words: list[dict] = field(default_factory=list)  # palavras com nota (SetWords)
    pcm: Optional[bytearray] = None  # áudio guardado em memória só se a Groq estiver ligada
    hint: str = ""  # dica de vocabulário para o reconhecimento on-line (nomes dos aparelhos...)
    local_live: bool = True  # Vosk ouvindo junto (texto parcial)? Desligado poupa o processador


# Avaliação da transcrição (scripts/voice_eval): a nota do Vosk NÃO separa ruído de fala
# (música virou "o" com nota 0,99), mas resultados só com palavras vazias são ruído
# típico, e nota média baixa aparece quando duas pessoas falam ao mesmo tempo.
FILLER_WORDS = {"o", "a", "os", "as", "e", "é", "um", "uma", "ah", "eh", "hum", "hm", "ã", "ó"}
UNCLEAR_CONFIDENCE = 0.5


@dataclass
class Transcript:
    text: str
    confidence: Optional[float]  # média das notas por palavra (None se indisponível)
    verdict: str  # ok | noise (ignorar em silêncio) | unclear (pedir para repetir)
    engine: str = "vosk"
    note: str = ""  # aviso para a tela (ex.: a Groq falhou e o Vosk assumiu)


def judge_transcript(text: str, words: list[dict]) -> Transcript:
    tokens = text.split()
    confs = [float(w["conf"]) for w in words if "conf" in w]
    conf = sum(confs) / len(confs) if confs else None
    if tokens and len(tokens) <= 2 and all(t.lower() in FILLER_WORDS for t in tokens):
        return Transcript(text, conf, "noise")
    if tokens and conf is not None and conf < UNCLEAR_CONFIDENCE:
        return Transcript(text, conf, "unclear")
    return Transcript(text, conf, "ok")


class SttSessions:
    """Reconhecimento incremental: o áudio chega em pedaços enquanto a pessoa fala."""

    MAX_SESSIONS = 2
    IDLE_TIMEOUT = 30.0

    def __init__(self, engine: VoskSTT, max_seconds: int, cloud: Optional["GroqSTT"] = None,
                 local_partials: bool = False) -> None:
        self.engine = engine
        self.cloud = cloud
        # Com a Groq ligada, o Vosk só serviria para o texto parcial e de reserva. Rodar o Vosk em
        # cada pedaço de áudio pesa muito num notebook fraco: por padrão ele só entra se a Groq falhar.
        self.local_partials = local_partials
        self.max_bytes = max_seconds * SAMPLE_RATE * 2
        self._sessions: dict[str, SttSession] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [s.id for s in self._sessions.values() if now - s.touched > self.IDLE_TIMEOUT]:
            self._sessions.pop(sid, None)

    def open(self, user_id: uuid.UUID, hint: str = "") -> str:
        with self._lock:
            self._expire()
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise VoiceUnavailable("Muitas sessões de reconhecimento simultâneas.")
        if self.cloud is None:
            rec = self.engine.recognizer()
        else:
            try:
                rec = self.engine.recognizer()
            except VoiceUnavailable:
                rec = None  # sem Vosk: só a Groq (sem texto parcial nem reserva)
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = SttSession(sid, user_id, rec,
                                             pcm=bytearray() if self.cloud is not None else None,
                                             hint=hint, local_live=self.cloud is None or self.local_partials)
        return sid

    def _get(self, sid: str, user_id: uuid.UUID) -> SttSession:
        with self._lock:
            self._expire()
            s = self._sessions.get(sid)
        if s is None or s.user_id != user_id:
            raise KeyError(sid)
        return s

    def feed(self, sid: str, user_id: uuid.UUID, pcm: bytes) -> str:
        s = self._get(sid, user_id)
        if len(pcm) % 2:
            pcm = pcm[:-1]
        s.bytes_received += len(pcm)
        if s.bytes_received > self.max_bytes:
            self.cancel(sid, user_id)
            raise VoiceUnavailable("Fala longa demais para um único turno.")
        s.touched = time.monotonic()
        if s.pcm is not None:
            s.pcm.extend(pcm)
        if s.recognizer is None or not s.local_live:
            return ""
        if s.recognizer.AcceptWaveform(pcm):
            result = json.loads(s.recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                s.finals.append(text)
                s.words.extend(result.get("result", []))
            return " ".join(s.finals)
        partial = json.loads(s.recognizer.PartialResult()).get("partial", "").strip()
        return " ".join([*s.finals, partial]).strip()

    def finish(self, sid: str, user_id: uuid.UUID) -> Transcript:
        s = self._get(sid, user_id)
        with self._lock:
            self._sessions.pop(sid, None)
        pcm = bytes(s.pcm) if s.pcm is not None else b""
        s.pcm = None

        def local_result() -> Optional[Transcript]:
            if s.recognizer is None:
                return None
            if not s.local_live and pcm:  # o Vosk não ouviu ao vivo: ouve tudo agora (só na reserva)
                step = SAMPLE_RATE * 2  # 1 s por vez
                for i in range(0, len(pcm), step):
                    if s.recognizer.AcceptWaveform(pcm[i:i + step]):
                        res = json.loads(s.recognizer.Result())
                        if res.get("text", "").strip():
                            s.finals.append(res["text"].strip())
                            s.words.extend(res.get("result", []))
            result = json.loads(s.recognizer.FinalResult())
            last = result.get("text", "").strip()
            return judge_transcript(" ".join([*s.finals, last]).strip(), [*s.words, *result.get("result", [])])

        if self.cloud is not None:
            if len(pcm) < MIN_SPEECH_SECONDS * SAMPLE_RATE * 2 or speech_level(pcm) < MIN_SPEECH_LEVEL:
                return Transcript("", None, "noise", self.cloud.name)  # silêncio: nada é enviado
            try:
                return self.cloud.transcribe(pcm, s.hint)
            except VoiceUnavailable as exc:
                log.warning("Reconhecimento on-line falhou, usando o Vosk: %s", exc)
                local = local_result()
                if local is None:
                    raise
                local.note = str(exc)
                return local
        local = local_result()
        return local if local is not None else Transcript("", None, "noise")

    def cancel(self, sid: str, user_id: uuid.UUID) -> None:
        with self._lock:
            s = self._sessions.get(sid)
            if s is not None and s.user_id == user_id:
                self._sessions.pop(sid, None)


class VoiceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stt = VoskSTT(settings)
        cloud = {"groq": GroqSTT, "xai": XaiSTT}.get(settings.voice_stt)
        self.cloud_stt: Optional[GroqSTT] = cloud(settings) if cloud else None
        self.tts: PiperTTS | EdgeTTS = EdgeTTS(settings) if settings.voice_tts == "edge" \
            else PiperTTS(settings)
        self.sessions = SttSessions(self.stt, settings.voice_max_utterance_seconds, self.cloud_stt,
                                    settings.voice_local_partials)

    def status(self) -> list[EngineStatus]:
        stt = [self.cloud_stt.status()] if self.cloud_stt is not None else []
        return [*stt, self.stt.status(), self.tts.status()]
