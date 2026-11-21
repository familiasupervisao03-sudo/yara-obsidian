"""Telemetria do notebook para o TITAN Central: processador, memória, temperatura,
bateria, gasto da IA e a tomada do carregador — e os ALERTAS CRÍTICOS.

Alerta é só para coisa grave (o que, se continuar, derruba o TITAN). Lembrete não é alerta.
Tudo é lido do próprio Linux (/proc e /sys); o que o notebook não expõe fica de fora
(ex.: temperatura da bateria em muitos modelos). Nada aqui age sozinho: os alertas só
dizem o que está acontecendo e o que fazer.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HISTORY = 60            # pontos guardados (≈ 10 min com 1 ponto a cada 10 s)
SAMPLE_EVERY_S = 10.0

# Limites (°C, %, W). Ficam aqui para todo mundo enxergar o porquê do alerta.
TEMP_LIMIT = 85.0          # processador: acima disso, risco de desligar sozinho
BAT_TEMP_LIMIT = 48.0      # bateria
CPU_LIMIT = 90.0           # processador travado em ≥ 90% ...
CPU_SUSTAIN = 6            # ... por 6 pontos seguidos (≈ 1 min)
SPEND_WARN = 90.0          # % do orçamento diário de IA paga
CHARGER_MAX_W = 90.0       # tomada do carregador puxando mais que isso = anormal


@dataclass
class Sample:
    at: float
    cpu: Optional[float] = None
    mem: Optional[float] = None
    temp: Optional[float] = None
    bat_temp: Optional[float] = None
    bat_pct: Optional[float] = None
    charging: Optional[bool] = None
    spend_pct: Optional[float] = None
    charger_w: Optional[float] = None


@dataclass
class _ProcSnap:
    total: int = 0
    idle: int = 0
    procs: dict = field(default_factory=dict)  # pid -> (nome, ticks)


def _read(p: Path) -> Optional[str]:
    try:
        return p.read_text().strip()
    except OSError:
        return None


class Sampler:
    """Lê o sistema e guarda os últimos 10 minutos. ``root`` existe para os testes."""

    def __init__(self, root: str = "/"):
        self.root = Path(root)
        self.history: deque[Sample] = deque(maxlen=HISTORY)
        self._snap: Optional[_ProcSnap] = None
        self._lock = threading.Lock()
        self.top_process: Optional[str] = None

    # --- leituras ---------------------------------------------------------------------

    def _cpu_ticks(self) -> Optional[tuple[int, int]]:
        line = (_read(self.root / "proc/stat") or "").splitlines()[:1]
        if not line or not line[0].startswith("cpu "):
            return None
        v = [int(x) for x in line[0].split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        return sum(v), idle

    def _procs(self) -> dict:
        out = {}
        proc = self.root / "proc"
        try:
            names = os.listdir(proc)
        except OSError:
            return out
        for pid in names:
            if not pid.isdigit():
                continue
            raw = _read(proc / pid / "stat")
            if not raw or ")" not in raw:
                continue
            name = raw[raw.find("(") + 1:raw.rfind(")")]
            rest = raw[raw.rfind(")") + 2:].split()
            try:
                out[pid] = (name, int(rest[11]) + int(rest[12]))  # utime + stime
            except (IndexError, ValueError):
                continue
        return out

    def _mem(self) -> Optional[float]:
        info = {}
        for line in (_read(self.root / "proc/meminfo") or "").splitlines():
            k, _, v = line.partition(":")
            try:
                info[k] = int(v.split()[0])
            except (IndexError, ValueError):
                pass
        total, avail = info.get("MemTotal"), info.get("MemAvailable")
        if not total or avail is None:
            return None
        return round(100 * (total - avail) / total, 1)

    def _temp(self) -> Optional[float]:
        """Maior temperatura do processador (hwmon coretemp/k10temp; senão zonas térmicas)."""
        best: Optional[float] = None
        hw = self.root / "sys/class/hwmon"
        for d in sorted(hw.glob("hwmon*")) if hw.is_dir() else []:
            if (_read(d / "name") or "") not in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
                continue
            for f in d.glob("temp*_input"):
                try:
                    t = int(_read(f) or "") / 1000
                except ValueError:
                    continue
                if 0 < t < 130:
                    best = t if best is None else max(best, t)
        if best is None:
            tz = self.root / "sys/class/thermal"
            for z in sorted(tz.glob("thermal_zone*")) if tz.is_dir() else []:
                try:
                    t = int(_read(z / "temp") or "") / 1000
                except ValueError:
                    continue
                if 0 < t < 130:
                    best = t if best is None else max(best, t)
        return round(best, 1) if best is not None else None

    def _battery(self) -> tuple[Optional[float], Optional[float], Optional[bool]]:
        ps = self.root / "sys/class/power_supply"
        for b in sorted(ps.glob("BAT*")) if ps.is_dir() else []:
            pct = _read(b / "capacity")
            temp = _read(b / "temp")  # décimos de °C (poucos notebooks expõem)
            status = (_read(b / "status") or "").lower()
            return (round(int(temp) / 10, 1) if temp and temp.lstrip("-").isdigit() else None,
                    float(pct) if pct and pct.isdigit() else None,
                    status == "charging" if status else None)
        return None, None, None

    # --- amostra ------------------------------------------------------------------------

    def sample(self, spend_pct: Optional[float] = None, charger_w: Optional[float] = None,
               now: Optional[float] = None) -> Sample:
        with self._lock:
            now = time.time() if now is None else now
            ticks = self._cpu_ticks()
            cpu = None
            procs = self._procs() if ticks else {}
            if ticks and self._snap and ticks[0] > self._snap.total:
                dt, di = ticks[0] - self._snap.total, ticks[1] - self._snap.idle
                cpu = round(100 * (dt - di) / dt, 1)
                # quem está comendo o processador (o "culpado" do alerta)
                deltas = [(t - self._snap.procs[p][1], n) for p, (n, t) in procs.items() if p in self._snap.procs]
                deltas = [d for d in deltas if d[0] > 0]
                self.top_process = max(deltas)[1] if deltas else None
            if ticks:
                self._snap = _ProcSnap(ticks[0], ticks[1], procs)
            bat_temp, bat_pct, charging = self._battery()
            s = Sample(at=now, cpu=cpu, mem=self._mem(), temp=self._temp(), bat_temp=bat_temp, bat_pct=bat_pct,
                       charging=charging, spend_pct=spend_pct, charger_w=charger_w)
            self.history.append(s)
            return s

    def sample_if_due(self, **kw) -> Sample:
        last = self.history[-1] if self.history else None
        if last is not None and time.time() - last.at < SAMPLE_EVERY_S:
            return last
        return self.sample(**kw)


# --- alertas ----------------------------------------------------------------------------

def _series(hist: list[Sample], key: str) -> list[float]:
    return [getattr(s, key) for s in hist if getattr(s, key) is not None]


def alerts(hist: list[Sample], top_process: Optional[str] = None, charger_plug: Optional[dict] = None) -> list[dict]:
    """Só o que é grave. Cada alerta traz o histórico para o gráfico e o que fazer."""
    if not hist:
        return []
    cur = hist[-1]
    out: list[dict] = []

    def add(key, level, title, value, unit, limit, vmax, text, todo, series, **extra):
        out.append({"key": key, "level": level, "title": title, "value": value, "unit": unit, "limit": limit,
                    "max": vmax, "text": text, "todo": todo, "history": series[-HISTORY:], **extra})

    temps = _series(hist, "temp")
    if cur.temp is not None and len(temps) >= 2 and temps[-1] >= TEMP_LIMIT and temps[-2] >= TEMP_LIMIT:
        add("temp", "crit", "SUPERAQUECIMENTO DO NOTEBOOK", cur.temp, "°C", TEMP_LIMIT, 105,
            "Processador acima do limite seguro. Se continuar, o notebook desliga sozinho e o TITAN cai.",
            "Desobstrua a saída de ar (nada de cama ou coberta embaixo), feche programas pesados ou use uma base "
            "com ventoinha. A Central já entrou em modo leve.", temps)

    bts = _series(hist, "bat_temp")
    if cur.bat_temp is not None and cur.bat_temp >= BAT_TEMP_LIMIT:
        add("bat", "crit", "BATERIA AQUECENDO", cur.bat_temp, "°C", BAT_TEMP_LIMIT, 70,
            "A bateria está quente demais" + (" com o carregador ligado." if cur.charging else "."),
            "Tire o carregador da tomada e deixe o notebook num lugar ventilado.", bts,
            plug=charger_plug)

    watts = _series(hist, "charger_w")
    if cur.charger_w is not None and cur.charger_w >= CHARGER_MAX_W:
        add("charger", "crit", "CARREGADOR PUXANDO ENERGIA DEMAIS", cur.charger_w, "W", CHARGER_MAX_W, 150,
            f"A tomada do carregador está puxando {cur.charger_w:.0f} W (um carregador de notebook costuma ficar "
            "abaixo de 65 W). Pode ser carregador esquentando ou com defeito.",
            "Desligue a tomada do carregador e veja se ele está quente. Se estiver, não use até trocar.", watts,
            plug=charger_plug)

    cpus = _series(hist, "cpu")
    if len(cpus) >= CPU_SUSTAIN and all(c >= CPU_LIMIT for c in cpus[-CPU_SUSTAIN:]):
        culprit = f" O que mais está usando agora: {top_process}." if top_process else ""
        add("cpu", "crit", "SOBRECARGA DO PROCESSADOR", cur.cpu, "%", CPU_LIMIT, 100,
            "Processador travado perto de 100% há mais de 1 minuto. O TITAN pode demorar ou congelar." + culprit,
            "Feche abas e programas que não está usando. A Central já entrou em modo leve.", cpus,
            culprit=top_process)

    spend = _series(hist, "spend_pct")
    if cur.spend_pct is not None and cur.spend_pct >= SPEND_WARN:
        full = cur.spend_pct >= 100
        add("spend", "crit" if full else "warn", "LIMITE DE GASTO DA IA" + (" ATINGIDO" if full else ""),
            cur.spend_pct, "%", SPEND_WARN, 100,
            ("O orçamento de hoje acabou: o núcleo de IA está pausado até amanhã." if full else
             "Quase todo o orçamento de IA de hoje já foi usado. Quando chegar em 100%, a IA pausa sozinha."),
            "Comandos da casa e lembretes continuam funcionando (não gastam IA). O limite diário é o que "
            "você definiu no notebook (titan enable-anthropic).", spend)
    return out


def snapshot(s: Sample) -> dict:
    return {"cpu": s.cpu, "mem": s.mem, "temp": s.temp, "bat_temp": s.bat_temp, "bat_pct": s.bat_pct,
            "charging": s.charging, "spend_pct": s.spend_pct, "charger_w": s.charger_w}
