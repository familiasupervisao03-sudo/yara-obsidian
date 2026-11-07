"""Abaixar o som do notebook enquanto você fala com o TITAN e enquanto ele responde
("ducking"), e devolver o volume de antes no final.

Funciona pelo servidor de som do Linux (PulseAudio ou PipeWire, via ``pactl``):
- só mexe nos programas que estão TOCANDO naquele momento (música, vídeo...);
- não mexe na voz do TITAN: o som dos apps do TITAN (titan abrir) fica de fora, e um som
  que começa depois do "abaixar" (a fala do TITAN) também;
- na volta, só restaura se você não mexeu no volume daquele programa enquanto isso;
- se o navegador sumir sem avisar, o volume volta sozinho em ~30 s.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

HOLD_S = 30.0  # sem renovação, o volume volta sozinho


@dataclass
class SinkInput:
    index: int
    corked: bool
    volumes: list[int]
    pid: Optional[int]
    app: str


def parse_sink_inputs(text: str) -> list[SinkInput]:
    """Lê a saída de ``LC_ALL=C pactl list sink-inputs``."""
    out: list[SinkInput] = []
    for block in re.split(r"^Sink Input #", text, flags=re.M)[1:]:
        idx = int(block.split("\n", 1)[0].strip())
        corked = bool(re.search(r"^\s*Corked:\s*yes", block, re.M))
        vline = re.search(r"^\s*Volume:\s*(.*)$", block, re.M)
        vols = [int(v) for v in re.findall(r":\s*(\d+)\s*/", vline.group(1))] if vline else []
        pid = re.search(r'application\.process\.id = "(\d+)"', block)
        app = re.search(r'application\.name = "([^"]*)"', block)
        out.append(SinkInput(idx, corked, vols, int(pid.group(1)) if pid else None, app.group(1) if app else ""))
    return out


def _ancestors(pid: int, proc: Path = Path("/proc")) -> set[int]:
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            raw = (proc / str(pid) / "stat").read_text()
            pid = int(raw[raw.rfind(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return seen


class Ducker:
    def __init__(self, level_pct: int = 20, apps_dir: Path = Path("var/apps"),
                 run: Optional[Callable[[list[str]], str]] = None, proc: Path = Path("/proc")):
        self.level = max(1, min(90, level_pct)) / 100
        self.apps_dir = apps_dir
        self.proc = proc
        self._run = run or self._pactl
        self._lock = threading.Lock()
        self._holders: dict[str, float] = {}           # quem pediu → até quando
        self._saved: dict[int, tuple[list[int], list[int]]] = {}  # índice → (original, o que pusemos)
        self._timer: Optional[threading.Timer] = None

    @staticmethod
    def available() -> bool:
        return shutil.which("pactl") is not None

    @staticmethod
    def _pactl(args: list[str]) -> str:
        env = {**os.environ, "LC_ALL": "C"}
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5, env=env)
        return r.stdout

    def _titan_pids(self) -> set[int]:
        """Processos dos apps do TITAN (abertos pelo ícone): o som deles não é abaixado."""
        pids: set[int] = set()
        for f in self.apps_dir.glob("*.pid") if self.apps_dir.is_dir() else []:
            try:
                pids.add(int(f.read_text().strip()))
            except ValueError:
                pass
        return pids

    def _is_titan(self, s: SinkInput, titan: set[int]) -> bool:
        return bool(s.pid and titan and _ancestors(s.pid, self.proc) & titan)

    # --- abaixar / devolver -----------------------------------------------------------------

    def duck(self, holder: str) -> int:
        """Abaixa o que está tocando agora. Chamado de novo enquanto ativo, só renova o prazo.
        Devolve quantos abaixou."""
        with self._lock:
            renewing = bool(self._holders)
            self._holders[holder] = time.monotonic() + HOLD_S
            self._schedule()
            if renewing:
                # já está abaixado: só renova. Não procura de novo, senão pegaria a própria voz
                # do TITAN, que começou a tocar depois do "abaixar".
                return 0
            titan = self._titan_pids()
            n = 0
            for s in parse_sink_inputs(self._run(["list", "sink-inputs"])):
                if s.index in self._saved or s.corked or not s.volumes or self._is_titan(s, titan):
                    continue
                low = [max(0, round(v * self.level)) for v in s.volumes]
                self._run(["set-sink-input-volume", str(s.index), *map(str, low)])
                self._saved[s.index] = (s.volumes, low)
                n += 1
            return n

    def release(self, holder: str) -> int:
        with self._lock:
            self._holders.pop(holder, None)
            if self._holders:
                return 0
            return self._restore()

    def _restore(self) -> int:
        if not self._saved:
            return 0
        current = {s.index: s for s in parse_sink_inputs(self._run(["list", "sink-inputs"]))}
        n = 0
        for idx, (orig, low) in self._saved.items():
            s = current.get(idx)
            if s is None:
                continue  # o programa fechou
            # você mexeu no volume enquanto isso? então deixa como você pôs
            if any(abs(a - b) > 1311 for a, b in zip(s.volumes, low)):  # ~2%
                continue
            self._run(["set-sink-input-volume", str(idx), *map(str, orig)])
            n += 1
        self._saved.clear()
        return n

    def _schedule(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(HOLD_S + 1, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._holders = {h: t for h, t in self._holders.items() if t > now}
            if self._holders:
                self._schedule()
            else:
                self._restore()

    @property
    def active(self) -> bool:
        return bool(self._saved)
