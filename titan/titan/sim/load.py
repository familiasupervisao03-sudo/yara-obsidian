"""Uso prolongado: várias "pessoas" usando o TITAN ao mesmo tempo durante a rodada.

Mede tempos de resposta, erros, memória (RSS) e arquivos abertos do servidor, e o
tamanho do banco. O servidor isolado continua de uma rodada para a outra, então o
resumo acompanha se a memória cresce ao longo das horas (vazamento).
"""

from __future__ import annotations

import collections
import threading
import time

from titan.sim.core import Context, RoundResult, percentile
from titan.sim.traffic import Traffic


def run(ctx: Context) -> RoundResult:
    res = RoundResult("uso", ctx.seed)
    srv = ctx.server()
    traffic = Traffic(srv, ctx.seed)
    # Aquecimento: cada tipo de ação uma vez antes de medir (a 1ª voz carrega o modelo
    # Vosk, ~180 MB, uma única vez — isso não é vazamento).
    warmup = [fn("alice") for fn, _ in traffic.actions()]
    rss0, fds0, db0 = srv.rss_mb(), srv.open_files(), srv.db_size_kb()
    samples: list[float] = []
    done = threading.Event()

    def sampler() -> None:
        while not done.wait(5):
            v = srv.rss_mb()
            if v:
                samples.append(v)

    threading.Thread(target=sampler, daemon=True).start()
    outcomes = traffic.run_for(ctx.seconds, workers=2 if ctx.quick else 3)
    done.set()
    rss1, fds1, db1 = srv.rss_mb(), srv.open_files(), srv.db_size_kb()

    by_action = collections.defaultdict(list)
    for o in outcomes:
        by_action[o.action].append(o)
    outcomes = warmup + outcomes
    errors = [o for o in outcomes if not o.ok]
    for o in errors[:20]:
        res.fail(f"{o.action}: {o.detail}", **(o.repro or {}))
    res.check("todas as ações deram o resultado esperado", not errors,
              f"{len(errors)} de {len(outcomes)} falharam")
    st = traffic.status("alice")
    res.check("auditoria íntegra no fim", st.ok, st.detail)
    res.check("servidor continua no ar", srv.alive())
    if fds0 is not None and fds1 is not None:
        res.check("arquivos abertos não disparam", fds1 - fds0 < 30, f"{fds0} → {fds1}")
    res.metrics.update(
        actions=len(outcomes), errors=len(errors), voice_tested=traffic.voice,
        rss_start_mb=round(rss0 or 0, 1), rss_end_mb=round(rss1 or 0, 1),
        rss_max_mb=round(max(samples + [rss1 or 0]), 1), open_files=[fds0, fds1],
        db_kb=[db0, db1], server_uptime_min=round((time.monotonic() - srv.started_at) / 60, 1),
        latency_ms={a: {"n": len(v), "p50": round(percentile([o.ms for o in v], 0.5)),
                        "p95": round(percentile([o.ms for o in v], 0.95))} for a, v in sorted(by_action.items())},
    )
    if rss0 and rss1 and rss1 - rss0 > 40:
        res.notes.append(f"Memória do servidor subiu {rss1 - rss0:.0f} MB nesta rodada "
                         "(acompanhe no resumo se continua subindo nas próximas).")
    return res
