"""Mecanismos de voz opcionais.

* Reconhecimento de fala: Vosk (local, modelo pequeno de português, ~52 MB).
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

    def synthesize(self, text: str) -> bytes:
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
                self._voice.synthesize_wav(text, wf)
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

    def synthesize(self, text: str) -> bytes:
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
            com = edge_tts.Communicate(text, self.voice, connector=connector,
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


@dataclass
class SttSession:
    id: str
    user_id: uuid.UUID
    recognizer: Any
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    bytes_received: int = 0
    finals: list[str] = field(default_factory=list)  # segmentos já finalizados pelo Vosk
    words: list[dict] = field(default_factory=list)  # palavras com nota (SetWords)


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

    def __init__(self, engine: VoskSTT, max_seconds: int) -> None:
        self.engine = engine
        self.max_bytes = max_seconds * SAMPLE_RATE * 2
        self._sessions: dict[str, SttSession] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [s.id for s in self._sessions.values() if now - s.touched > self.IDLE_TIMEOUT]:
            self._sessions.pop(sid, None)

    def open(self, user_id: uuid.UUID) -> str:
        with self._lock:
            self._expire()
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise VoiceUnavailable("Muitas sessões de reconhecimento simultâneas.")
        rec = self.engine.recognizer()
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = SttSession(sid, user_id, rec)
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
        result = json.loads(s.recognizer.FinalResult())
        last = result.get("text", "").strip()
        words = [*s.words, *result.get("result", [])]
        return judge_transcript(" ".join([*s.finals, last]).strip(), words)

    def cancel(self, sid: str, user_id: uuid.UUID) -> None:
        with self._lock:
            s = self._sessions.get(sid)
            if s is not None and s.user_id == user_id:
                self._sessions.pop(sid, None)


class VoiceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stt = VoskSTT(settings)
        self.tts: PiperTTS | EdgeTTS = EdgeTTS(settings) if settings.voice_tts == "edge" \
            else PiperTTS(settings)
        self.sessions = SttSessions(self.stt, settings.voice_max_utterance_seconds)

    def status(self) -> list[EngineStatus]:
        return [self.stt.status(), self.tts.status()]
