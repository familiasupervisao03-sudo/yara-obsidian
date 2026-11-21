"""Falhas e recuperação: queda abrupta no meio do uso, banco travado e backup interrompido.

1. Uso normal por alguns segundos e, num instante sorteado, SIGKILL no servidor
   (como falta de energia). Reinicia e confere: sobe de novo, auditoria íntegra,
   banco íntegro, nenhuma tarefa "presa" em andamento, nenhuma mensagem duplicada,
   e tarefas interrompidas podem ser retomadas até o fim.
2. Outro processo segura o banco travado por alguns segundos durante o uso: as
   requisições esperam e funcionam depois (sem erro e sem corromper nada).
3. Backup durante o uso; às vezes o backup é morto no meio — o banco continua
   bom e o backup seguinte funciona e passa no teste de restauração.
"""

from __future__ import annotations

import random
import sqlite3
import subprocess
import sys
import threading
import time

from titan.sim.core import Context, RoundResult
from titan.sim.traffic import Traffic

STUCK = {"RUNNING", "VERIFYING", "CANCEL_REQUESTED"}


def _db_checks(res: RoundResult, srv) -> None:
    con = sqlite3.connect(f"file:{srv.db_path}?mode=ro", uri=True, timeout=30)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        res.check("banco íntegro (integrity_check)", integrity == "ok", integrity)
        dups = con.execute(
            "SELECT conversation_id, client_request_id, COUNT(*) FROM messages "
            "WHERE client_request_id IS NOT NULL GROUP BY 1, 2 HAVING COUNT(*) > 1").fetchall()
        res.check("nenhuma mensagem duplicada", not dups, f"{len(dups)} grupos duplicados")
    finally:
        con.close()


def run(ctx: Context) -> RoundResult:
    rng = random.Random(ctx.seed)
    res = RoundResult("falhas", ctx.seed)
    srv = ctx.server()

    # --- 1. queda abrupta no meio do uso ---------------------------------------------
    traffic = Traffic(srv, ctx.seed)
    kill_after = rng.uniform(1.0, 3.0 if ctx.quick else 8.0)
    stop_traffic = threading.Event()
    th = threading.Thread(target=traffic.run_for, args=(kill_after + 5, 3, stop_traffic.is_set), daemon=True)
    th.start()
    time.sleep(kill_after)
    srv.kill()
    stop_traffic.set()
    th.join(30)
    res.metrics["killed_after_s"] = round(kill_after, 2)
    t0 = time.monotonic()
    try:
        srv.start()
        res.check("servidor volta depois da queda", True, f"{time.monotonic() - t0:.1f} s")
    except RuntimeError as exc:
        res.check("servidor volta depois da queda", False, str(exc))
        res.fail("O servidor não reiniciou depois de uma queda abrupta.", seed=ctx.seed,
                 killed_after_s=kill_after, log=str(srv.log_path))
        return res
    res.metrics["restart_s"] = round(time.monotonic() - t0, 1)
    _db_checks(res, srv)
    traffic = Traffic(srv, ctx.seed + 1)  # sessões novas (o servidor reiniciou)
    st = traffic.status("alice")
    res.check("auditoria íntegra depois da queda", st.ok, st.detail)
    stuck, resumed, resume_fail = [], 0, []
    for user, c in traffic.clients.items():
        for t in c.get("/api/v1/tasks").json()["items"]:
            if t["status"] in STUCK:
                stuck.append((user, t["id"], t["status"]))
            elif t["status"] == "INTERRUPTED":
                r = c.post(f"/api/v1/tasks/{t['id']}/resume", {"retry_uncertain": True})
                if r.status == 200 and r.json()["task"]["status"] == "READY":
                    c.post(f"/api/v1/tasks/{t['id']}/start", {})
                final = traffic._wait_task(c, t["id"], {"COMPLETED", "FAILED", "CANCELLED", "PENDING_APPROVAL",
                                                       "WAITING_FOR_USER"})
                if final in ("COMPLETED", "PENDING_APPROVAL", "WAITING_FOR_USER"):
                    resumed += 1
                else:
                    resume_fail.append((t["id"], final))
    res.check("nenhuma tarefa presa em andamento", not stuck, str(stuck[:3]))
    res.check("tarefas interrompidas retomam", not resume_fail, str(resume_fail[:3]))
    for tid, final in resume_fail[:5]:
        res.fail(f"Tarefa interrompida pela queda não concluiu ao retomar ({final}).", task_id=tid, seed=ctx.seed)
    res.metrics["interrupted_resumed"] = resumed

    # --- 2. banco travado por outro processo ------------------------------------------
    hold = rng.uniform(1.5, 4.0)
    locker = subprocess.Popen([sys.executable, "-c",
                               "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],timeout=30);"
                               "c.execute('BEGIN EXCLUSIVE');print('ok',flush=True);time.sleep(float(sys.argv[2]));"
                               "c.rollback()", str(srv.db_path), str(hold)],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)
    locker.stdout.readline()
    outcomes = [traffic.chat_post_and_retry("alice"), traffic.task_note("bob"), traffic.status("alice")]
    locker.wait(30)
    bad = [o for o in outcomes if not o.ok]
    res.check(f"banco travado {hold:.1f} s: requisições esperam e funcionam", not bad,
              "; ".join(o.detail for o in bad))
    for o in bad:
        res.fail(f"Com o banco travado: {o.action}: {o.detail}", **(o.repro or {}))
    res.metrics["db_lock_s"] = round(hold, 1)
    res.metrics["slowest_during_lock_ms"] = round(max(o.ms for o in outcomes))

    # --- 3. backup durante o uso (às vezes morto no meio) ------------------------------
    kill_backup = rng.random() < 0.5
    th = threading.Thread(target=traffic.run_for, args=(6 if not ctx.quick else 2, 2), daemon=True)
    th.start()
    if kill_backup:
        p = subprocess.Popen([sys.executable, "-m", "titan.cli", "backup"], cwd=srv.workdir, env=srv.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(rng.uniform(0.05, 0.6))
        p.kill()
        p.wait()
    r = srv.cli("backup")
    th.join(60)
    res.metrics["backup_killed_first"] = kill_backup
    ok = res.check("backup durante o uso passa no teste de restauração" + (" (depois de um backup morto)" if kill_backup else ""),
                   r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr)[-300:])
    if not ok:
        res.fail("Backup falhou durante o uso.", stdout=r.stdout[-500:], stderr=r.stderr[-500:], seed=ctx.seed)
    _db_checks(res, srv)
    return res
