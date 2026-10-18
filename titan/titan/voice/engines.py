"""Mecanismos de voz LOCAIS e opcionais (rodam no notebook; nada sai do computador).

* Reconhecimento de fala: Vosk (modelo pequeno de português, ~52 MB).
* Síntese de voz: Piper (voz pt_BR, ~63 MB).

Os dois são carregados sob demanda, uma única vez, e ficam indisponíveis (com
motivo explícito) se a biblioteca ou o modelo não estiverem instalados.
Áudio é processado em memória e nunca gravado em disco ou em logs.
"""

from __future__ import annotations

import io
import json
import logging
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
        try:
            import vosk  # noqa: F401
        except ImportError:
            return EngineStatus(self.name, "stt", False, True,
                                "Biblioteca 'vosk' não instalada (sh scripts/install_voice_local.sh).")
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

        return KaldiRecognizer(self._model, SAMPLE_RATE)


class PiperTTS:
    name = "piper"

    def __init__(self, settings: Settings) -> None:
        self.model_path = Path(settings.voice_piper_model).expanduser()
        self._voice: Any = None
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()  # uma síntese por vez (CPU modesta)

    def status(self) -> EngineStatus:
        try:
            import piper  # noqa: F401
        except ImportError:
            return EngineStatus(self.name, "tts", False, True,
                                "Biblioteca 'piper-tts' não instalada (sh scripts/install_voice_local.sh).")
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


@dataclass
class SttSession:
    id: str
    user_id: uuid.UUID
    recognizer: Any
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    bytes_received: int = 0
    finals: list[str] = field(default_factory=list)  # segmentos já finalizados pelo Vosk


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
            text = json.loads(s.recognizer.Result()).get("text", "").strip()
            if text:
                s.finals.append(text)
            return " ".join(s.finals)
        partial = json.loads(s.recognizer.PartialResult()).get("partial", "").strip()
        return " ".join([*s.finals, partial]).strip()

    def finish(self, sid: str, user_id: uuid.UUID) -> str:
        s = self._get(sid, user_id)
        with self._lock:
            self._sessions.pop(sid, None)
        last = json.loads(s.recognizer.FinalResult()).get("text", "").strip()
        return " ".join([*s.finals, last]).strip()

    def cancel(self, sid: str, user_id: uuid.UUID) -> None:
        with self._lock:
            s = self._sessions.get(sid)
            if s is not None and s.user_id == user_id:
                self._sessions.pop(sid, None)


class VoiceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stt = VoskSTT(settings)
        self.tts = PiperTTS(settings)
        self.sessions = SttSessions(self.stt, settings.voice_max_utterance_seconds)

    def status(self) -> list[EngineStatus]:
        return [self.stt.status(), self.tts.status()]
