"""Simulação contínua (titan/sim): parada segura, diário e cenários."""

import json
import os
import signal
import threading
import time

import pytest

from titan.sim import runner as R
from titan.sim.core import Context, RoundResult


def _fake_scenarios(monkeypatch, seconds=0.3, on_round=None):
    calls = []

    def fake(kind):
        def run(ctx):
            calls.append(kind)
            if on_round:
                on_round(len(calls))
            time.sleep(seconds)  # "trabalho" da rodada
            res = RoundResult(kind, ctx.seed)
            res.check("rodada inteira", True)
            res.metrics["fim"] = True
            return res
        return run

    monkeypatch.setattr(R, "_scenario", fake)
    return calls


def test_ctrl_c_finishes_the_current_round(tmp_path, monkeypatch):
    msgs = []
    # Ctrl+C chega no MEIO da 2ª rodada: ela precisa terminar inteira e a 3ª não começa.
    _fake_scenarios(monkeypatch, 0.5, on_round=lambda n: n == 2 and threading.Timer(
        0.1, os.kill, (os.getpid(), signal.SIGINT)).start())
    r = R.Runner(kinds=["orcamento", "seguranca"], pause=0, base=tmp_path, say=msgs.append)
    assert r.run() == 0
    session = next(tmp_path.glob("2*"))
    rounds = [json.loads(line) for line in (session / "rodadas.jsonl").read_text().splitlines()]
    assert [x["round"] for x in rounds] == [1, 2] and all(x["metrics"]["fim"] for x in rounds)
    assert not (session / "em-andamento.json").exists()
    assert not (tmp_path / ".em-execucao").exists()
    assert "Sessão encerrada" in (session / "diario.md").read_text()
    assert any("Parada pedida" in m for m in msgs) and "encerrada com segurança" in msgs[-1]
    signal.signal(signal.SIGINT, signal.default_int_handler)


def test_stop_file_and_second_instance(tmp_path, monkeypatch):
    calls = _fake_scenarios(monkeypatch, 0.2, on_round=lambda n: n == 2 and R.request_stop(tmp_path))
    msgs = []
    first = R.Runner(kinds=["orcamento"], pause=0, base=tmp_path, say=msgs.append)
    # outra instância VIVA (aqui: o processo pai do pytest) impede uma segunda simulação
    (tmp_path / ".em-execucao").write_text(f"{os.getppid()}\n")
    assert R.Runner(base=tmp_path, say=msgs.append)._acquire() is False
    assert any("Já existe uma simulação rodando" in m for m in msgs)
    (tmp_path / ".em-execucao").write_text("999999999\n")  # trava velha de processo morto: liberada
    assert R.Runner(base=tmp_path, say=msgs.append)._acquire() is True
    (tmp_path / ".em-execucao").unlink()
    assert first.run() == 0
    assert calls == ["orcamento", "orcamento"]  # parou depois de terminar a 2ª
    assert not (tmp_path / "PARAR").exists()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.SIG_DFL if sig != signal.SIGINT else signal.default_int_handler)


def test_round_killed_by_force_is_reported_next_time(tmp_path, monkeypatch):
    _fake_scenarios(monkeypatch, 0)
    dead = tmp_path / "20200101-000000"
    (dead / "tmp").mkdir(parents=True)
    (dead / "em-andamento.json").write_text(json.dumps({"round": 7, "kind": "uso"}))
    R.Runner(kinds=["orcamento"], max_rounds=1, pause=0, base=tmp_path, say=lambda m: None).run()
    session = sorted(tmp_path.glob("2*"))[-1]
    assert "rodada 7 (Uso prolongado) foi interrompida à força" in (session / "diario.md").read_text()
    assert (dead / "rodada-interrompida.json").exists() and not (dead / "tmp").exists()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.SIG_DFL if sig != signal.SIGINT else signal.default_int_handler)


def test_simulator_error_is_recorded_not_hidden(tmp_path, monkeypatch):
    def boom(kind):
        def run(ctx):
            raise ValueError("defeito no cenário")
        return run

    monkeypatch.setattr(R, "_scenario", boom)
    R.Runner(kinds=["orcamento"], max_rounds=1, pause=0, base=tmp_path, say=lambda m: None).run()
    session = next(tmp_path.glob("2*"))
    data = json.loads((session / "rodadas.jsonl").read_text())
    assert data["ok"] is False and "defeito no cenário" in data["checks"][0]["detail"]
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.SIG_DFL if sig != signal.SIGINT else signal.default_int_handler)


def test_budget_scenario_never_exceeds_and_never_underreports(tmp_path):
    from titan.sim import budget

    res = budget.run(Context(42, 5, tmp_path, lambda: None, lambda: False, quick=True))
    assert res.ok, [c for c in res.checks if not c.ok]
    assert res.metrics["simulations"] >= 3 and res.metrics["max_ledger_pct_of_budget"] <= 100


def test_security_scenario_on_isolated_server(tmp_path):
    from titan.sim import security
    from titan.sim.server import IsolatedServer

    srv = IsolatedServer(tmp_path / "srv")
    srv.prepare()
    srv.start()
    try:
        assert "ANTHROPIC_API_KEY" not in srv.env and srv.env["TITAN_MODEL_PROVIDER"] == "mock"
        res = security.run(Context(7, 10, tmp_path, lambda: srv, lambda: False, quick=True))
    finally:
        srv.stop()
    assert res.ok, [(c.name, c.detail) for c in res.checks if not c.ok] + [f.what for f in res.failures]
    assert res.metrics["routes"] >= 30
