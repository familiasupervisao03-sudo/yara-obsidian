"""Laço da simulação contínua: rodadas alternando os tipos, diário e parada segura.

Parada: Ctrl+C (uma vez), fechar a janela, ``titan parar-simulacao`` em outro
terminal ou o arquivo var/simulacao/PARAR. Em todos os casos a rodada em
andamento TERMINA, é salva, e só então a simulação encerra. Os processos
auxiliares (servidor isolado, simulador de voz) rodam em sessão própria, então
o Ctrl+C não os interrompe no meio.

Se a energia cair (ou o processo for morto à força), a rodada incompleta fica
marcada em ``em-andamento.json`` e é registrada como descartada na próxima
sessão; as rodadas anteriores já estavam gravadas por completo.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from titan.sim.core import Context, RoundResult

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "var" / "simulacao"
SCHEDULE = ["orcamento", "uso", "seguranca", "falhas", "uso", "orcamento", "seguranca", "falhas", "voz"]
NEEDS_SERVER = {"uso", "seguranca", "falhas"}
NAMES = {"orcamento": "Orçamento da Anthropic", "uso": "Uso prolongado", "seguranca": "Segurança",
         "falhas": "Falhas e recuperação", "voz": "Voz (regressão)"}


def _scenario(kind: str) -> Callable[[Context], RoundResult]:
    from titan.sim import budget, load, recovery, security, voice

    return {"orcamento": budget.run, "uso": load.run, "seguranca": security.run,
            "falhas": recovery.run, "voz": voice.run}[kind]


def _atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "?"
    except (OSError, subprocess.TimeoutExpired):
        return "?"


def _mem_available_mb() -> Optional[float]:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


class Runner:
    def __init__(self, minutes: float = 3, pause: float = 10, max_rounds: Optional[int] = None,
                 kinds: Optional[list[str]] = None, quick: bool = False, base: Path = BASE,
                 say: Callable[[str], None] = print) -> None:
        self.round_seconds = max(10.0, minutes * 60)
        self.pause = pause
        self.max_rounds = max_rounds
        self.schedule = [k for k in SCHEDULE if not kinds or k in kinds] or list(kinds or SCHEDULE)
        self.quick = quick
        self.base = base
        self.stop_file = base / "PARAR"
        self.lock_file = base / ".em-execucao"
        self.say_raw = say
        self.stopping = False
        self.server = None
        self.voice_previous: Optional[dict] = None
        self.results: list[dict] = []

    # --- mensagens e sinais -----------------------------------------------------------

    def say(self, msg: str) -> None:
        try:
            self.say_raw(msg)
        except OSError:  # janela fechada: segue sem terminal
            pass

    def _on_signal(self, signum, _frame) -> None:
        if not self.stopping:
            self.stopping = True
            self.say("\n>>> Parada pedida. Terminando a rodada atual e salvando tudo — "
                     "NÃO feche a janela; isso pode levar alguns minutos.")
        else:
            self.say(">>> Já estou terminando a rodada atual. Aguarde a mensagem 'Simulação encerrada'.")

    def stop_requested(self) -> bool:
        if not self.stopping and self.stop_file.exists():
            self.stopping = True
            self.say(">>> Pedido de parada recebido (titan parar-simulacao). Terminando a rodada atual…")
        return self.stopping

    # --- sessão -----------------------------------------------------------------------

    def _acquire(self) -> bool:
        self.base.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                pid = int(self.lock_file.read_text().split()[0])
            except (ValueError, IndexError):
                pid = -1
            if pid > 0 and pid != os.getpid() and _pid_alive(pid):
                self.say(f"Já existe uma simulação rodando (processo {pid}). Para parar: titan parar-simulacao")
                return False
        _atomic(self.lock_file, f"{os.getpid()}\n")
        self.stop_file.unlink(missing_ok=True)  # pedido antigo não vale para esta sessão
        return True

    def _previous_interrupted(self) -> list[str]:
        found = []
        for marker in sorted(self.base.glob("*/em-andamento.json")):
            try:
                info = json.loads(marker.read_text())
            except ValueError:
                info = {}
            found.append(f"Sessão {marker.parent.name}: rodada {info.get('round', '?')} "
                         f"({NAMES.get(info.get('kind'), info.get('kind'))}) foi interrompida à força "
                         "e descartada; as anteriores estão completas.")
            os.replace(marker, marker.with_name("rodada-interrompida.json"))
        # Pastas temporárias de sessões que morreram à força (banco de teste, servidor isolado).
        for tmp in self.base.glob("*/tmp"):
            shutil.rmtree(tmp, ignore_errors=True)
        return found

    def _server(self):
        from titan.sim.server import IsolatedServer

        if self.server is None:
            self.server = IsolatedServer(self.tmp / "servidor")
            self.server.prepare()
            self.server.start()
        elif not self.server.alive():
            self.server.start()
        return self.server

    def run_one(self, kind: str, seed: int, workdir: Path) -> RoundResult:
        ctx = Context(seed, self.round_seconds if kind == "uso" else min(self.round_seconds, 120),
                      workdir, self._server, self.stop_requested, self.quick)
        t0 = time.monotonic()
        try:
            if kind == "voz":
                from titan.sim import voice

                res = voice.run(ctx, previous=self.voice_previous)
                if not res.skipped:
                    self.voice_previous = res.metrics
            else:
                res = _scenario(kind)(ctx)
        except Exception as exc:  # erro do próprio simulador: registrado, não esconde nada
            res = RoundResult(kind, seed)
            res.check("o simulador executou a rodada sem erro", False, f"{type(exc).__name__}: {exc}")
            res.notes.append("Erro do simulador (não necessariamente do TITAN):\n" + traceback.format_exc()[-2000:])
        res.seconds = round(time.monotonic() - t0, 1)
        return res

    def run(self) -> int:
        if not self._acquire():
            return 1
        started = datetime.now()
        self.session = self.base / started.strftime("%Y%m%d-%H%M%S")
        self.tmp = self.session / "tmp"
        (self.session / "falhas").mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=self.session / "registros-tecnicos.log", level=logging.WARNING, force=True,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, self._on_signal)
        try:
            os.nice(10)  # o notebook continua usável
        except OSError:
            pass
        previous = self._previous_interrupted()
        _atomic(self.session / "diario.md", self._header(started, previous))
        self.say(f"Simulação contínua iniciada. Diário: {self.session / 'diario.md'}")
        self.say("Para parar com segurança: Ctrl+C (uma vez) ou, em outro terminal, titan parar-simulacao")
        n = 0
        try:
            while not self.stop_requested() and (self.max_rounds is None or n < self.max_rounds):
                if not self._resources_ok():
                    break
                n += 1
                kind = self.schedule[(n - 1) % len(self.schedule)]
                seed = int(time.time() * 1000) % 1_000_000_007
                self._round(n, kind, seed)
                self._wait(self.pause)
        finally:
            self._finish(n)
        return 0

    def _round(self, n: int, kind: str, seed: int) -> None:
        marker = self.session / "em-andamento.json"
        _atomic(marker, json.dumps({"round": n, "kind": kind, "seed": seed,
                                    "started": datetime.now().isoformat(timespec="seconds")}))
        self.say(f"[{datetime.now():%H:%M:%S}] Rodada {n}: {NAMES[kind]} (semente {seed})…")
        if kind in NEEDS_SERVER and self.server is not None and not self.server.alive():
            note = "O servidor isolado tinha caído sozinho antes desta rodada (ver servidor.log)."
        else:
            note = None
        res = self.run_one(kind, seed, self.tmp)
        if note:
            res.fail(note, log=str(self.server.log_path))
        data = res.to_dict() | {"round": n, "finished": datetime.now().isoformat(timespec="seconds")}
        if res.failures:
            _atomic(self.session / "falhas" / f"rodada-{n:04d}-{kind}.json",
                    json.dumps(data, ensure_ascii=False, indent=1, default=str))
        _append(self.session / "rodadas.jsonl", json.dumps(data, ensure_ascii=False, default=str) + "\n")
        _append(self.session / "diario.md", self._entry(n, res))
        self.results.append(data)
        _atomic(self.session / "resumo.md", self._summary())
        marker.unlink(missing_ok=True)  # só agora a rodada conta como completa
        status = "pulada: " + res.skipped if res.skipped else ("OK" if res.ok else
                                                               f"FALHOU ({len(res.failures) or 'ver'} problema(s))")
        self.say(f"[{datetime.now():%H:%M:%S}] Rodada {n} {status} em {res.seconds:.0f} s")

    def _wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.stop_requested():
            time.sleep(0.5)

    def _resources_ok(self) -> bool:
        free_mb = shutil.disk_usage(self.base).free / 1e6
        if free_mb < 500:
            _append(self.session / "diario.md", f"\n**Parada automática:** pouco espaço em disco ({free_mb:.0f} MB).\n")
            self.say(f">>> Parando: pouco espaço em disco ({free_mb:.0f} MB livres).")
            return False
        mem = _mem_available_mb()
        if mem is not None and mem < 250:
            _append(self.session / "diario.md", f"\nMemória livre baixa ({mem:.0f} MB): aguardando 60 s.\n")
            self.say(f">>> Pouca memória livre ({mem:.0f} MB): aguardando 60 s antes da próxima rodada.")
            self._wait(60)
        return True

    def _finish(self, rounds: int) -> None:
        if self.server is not None:
            self.server.stop()
            # Guarda o log do servidor de teste (últimos 5 MB) para diagnóstico.
            if self.server.log_path.exists():
                data = self.server.log_path.read_bytes()[-5_000_000:]
                (self.session / "servidor-de-teste.log").write_bytes(data)
        shutil.rmtree(self.tmp, ignore_errors=True)
        _append(self.session / "diario.md",
                f"\n---\n**Sessão encerrada** em {datetime.now():%d/%m/%Y %H:%M:%S} após {rounds} rodada(s).\n")
        _atomic(self.session / "resumo.md", self._summary(final=True))
        self.lock_file.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.say(f"Simulação encerrada com segurança após {rounds} rodada(s). Resumo: {self.session / 'resumo.md'}")

    # --- documentação -------------------------------------------------------------------

    def _header(self, started: datetime, previous: list[str]) -> str:
        from titan.sim.server import IsolatedServer  # noqa: F401  (garante import antes de rodar)

        cpu = "?"
        try:
            cpu = next(ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines()
                       if ln.startswith("model name"))
        except (OSError, StopIteration):
            pass
        lines = [f"# Diário da simulação contínua — {started:%d/%m/%Y %H:%M:%S}", "",
                 f"- Commit `{_commit()}` · CPU {cpu} · Python {sys.version.split()[0]}",
                 f"- Ordem das rodadas: {', '.join(NAMES[k] for k in self.schedule)}",
                 f"- Duração da rodada de uso: {self.round_seconds / 60:.1f} min · pausa entre rodadas: {self.pause:.0f} s"
                 + (" · modo rápido" if self.quick else ""),
                 "- Tudo roda numa cópia isolada do TITAN (banco temporário, outra porta, provedor de IA "
                 "falso, sem o .env real): os seus dados e a sua chave não são usados.",
                 "- Para parar com segurança: Ctrl+C uma vez, ou `titan parar-simulacao` em outro terminal.", ""]
        if previous:
            lines += ["## Aviso sobre a sessão anterior", *[f"- {p}" for p in previous], ""]
        return "\n".join(lines) + "\n## Rodadas\n"

    def _entry(self, n: int, res: RoundResult) -> str:
        head = "PULADA" if res.skipped else ("OK" if res.ok else "FALHOU")
        out = [f"\n### Rodada {n} — {NAMES[res.kind]} — {datetime.now():%H:%M:%S} — {head} ({res.seconds:.0f} s, semente {res.seed})"]
        if res.skipped:
            out.append(f"- Pulada: {res.skipped}")
        out += [f"- {'✓' if c.ok else '✗'} {c.name}" + (f" — {c.detail}" if c.detail else "") for c in res.checks]
        for f in res.failures[:10]:
            out.append(f"- **Problema:** {f.what}")
        if res.failures:
            out.append(f"- Detalhes para reproduzir: `falhas/rodada-{n:04d}-{res.kind}.json` "
                       f"(repetir: `titan simular --repetir {res.kind}:{res.seed}`)")
        for note in res.notes:
            out.append(f"- Observação: {note.splitlines()[0]}")
        brief = {k: v for k, v in res.metrics.items() if k not in ("latency_ms",)}
        if brief:
            out.append(f"- Medidas: `{json.dumps(brief, ensure_ascii=False, default=str)[:600]}`")
        if "latency_ms" in res.metrics:
            lat = ", ".join(f"{a} p95 {v['p95']} ms" for a, v in res.metrics["latency_ms"].items())
            out.append(f"- Tempos de resposta: {lat}")
        return "\n".join(out) + "\n"

    def _summary(self, final: bool = False) -> str:
        by_kind = defaultdict(Counter)
        problems: dict[str, list[int]] = defaultdict(list)
        for r in self.results:
            k = "pulada" if r["skipped"] else ("ok" if r["ok"] else "falhou")
            by_kind[r["kind"]][k] += 1
            for f in r["failures"]:
                problems[f"[{NAMES[r['kind']]}] {f['what'][:160]}"].append(r["round"])
            for c in r["checks"]:
                if not c["ok"] and not r["failures"]:
                    problems[f"[{NAMES[r['kind']]}] {c['name']}: {c['detail'][:120]}"].append(r["round"])
        lines = [f"# Resumo da simulação — {'encerrada' if final else 'em andamento'}",
                 f"Atualizado em {datetime.now():%d/%m/%Y %H:%M:%S}. Rodadas: {len(self.results)}.", "",
                 "| Tipo | OK | Falhou | Pulada |", "|---|---|---|---|"]
        for kind in dict.fromkeys(SCHEDULE):
            if kind in by_kind:
                c = by_kind[kind]
                lines.append(f"| {NAMES[kind]} | {c['ok']} | {c['falhou']} | {c['pulada']} |")
        lines += ["", "## Problemas encontrados (em quais rodadas)"]
        if problems:
            for what, rounds in sorted(problems.items(), key=lambda x: -len(x[1])):
                lines.append(f"- {what} — {len(rounds)}× (rodadas {', '.join(map(str, rounds[:15]))})")
        else:
            lines.append("- Nenhum até agora.")
        uso = [r for r in self.results if r["kind"] == "uso" and not r["skipped"]]
        if uso:
            lines += ["", "## Memória e tempos (uso prolongado)",
                      "| Rodada | Servidor no ar há | Memória início → fim | Arquivos abertos | Erros | Streaming p95 |",
                      "|---|---|---|---|---|---|"]
            for r in uso[-20:]:
                m = r["metrics"]
                p95 = m.get("latency_ms", {}).get("conversa (streaming)", {}).get("p95", "—")
                lines.append(f"| {r['round']} | {m.get('server_uptime_min', '?')} min | {m.get('rss_start_mb')} → "
                             f"{m.get('rss_end_mb')} MB | {m.get('open_files')} | {m.get('errors')} | {p95} ms |")
        orc = [r for r in self.results if r["kind"] == "orcamento" and not r["skipped"]]
        if orc:
            sims = sum(r["metrics"].get("simulations", 0) for r in orc)
            worst = max(r["metrics"].get("max_ledger_pct_of_budget", 0) for r in orc)
            lines += ["", "## Orçamento", f"- {sims} simulações; maior uso do limite diário: {worst}% "
                      "(nunca pode passar de 100%)."]
        return "\n".join(lines) + "\n"


def request_stop(base: Path = BASE) -> str:
    base.mkdir(parents=True, exist_ok=True)
    lock = base / ".em-execucao"
    running = lock.exists() and _pid_alive(int((lock.read_text().split() or ["-1"])[0] or -1))
    (base / "PARAR").write_text(datetime.now().isoformat())
    if running:
        return ("Pedido de parada enviado. A simulação vai terminar a rodada atual, salvar tudo e encerrar "
                "(pode levar alguns minutos). Acompanhe no terminal dela.")
    return "Nenhuma simulação rodando agora (o pedido fica registrado e é descartado na próxima)."
