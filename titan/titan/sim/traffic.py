"""Uso simulado do TITAN pela API (como a interface faria), com conferência de cada resposta."""

from __future__ import annotations

import random
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from titan.sim.server import Client, IsolatedServer

PHRASES = ["oi titan", "me lembra de beber água", "qual é a previsão do tempo amanhã",
           "anota que eu preciso comprar café", "e aí mano, beleza?", "explica como funciona o backup",
           "1234567890 " * 30, "ç á é í ó ú ã õ — “aspas” 🙂"]
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
SAMPLE = Path(__file__).resolve().parents[2] / "scripts/voice_eval/samples/fala_curta.wav"


@dataclass
class Outcome:
    action: str
    ok: bool
    ms: float
    detail: str = ""
    repro: Optional[dict] = None


class Traffic:
    def __init__(self, server: IsolatedServer, seed: int) -> None:
        self.server = server
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.clients = {u: server.client(u) for u in server.USERS}
        self.conversations: dict[str, list[str]] = {u: [] for u in server.USERS}
        self.voice = self._voice_available()
        self.task_ids: dict[str, list[str]] = {u: [] for u in server.USERS}

    def _voice_available(self) -> bool:
        r = self.clients["alice"].get("/api/v1/voice/status")
        if r.status != 200:
            return False
        return any(e["name"] == "vosk" and e["available"] for e in r.json()["engines"])

    # --- utilidades -----------------------------------------------------------------

    def _bad(self, action: str, ms: float, method: str, path: str, r, body=None, why="") -> Outcome:
        return Outcome(action, False, ms, why or f"{method} {path} → {r.status}",
                       {"method": method, "path": path, "status": r.status, "body": body,
                        "response": r.text[:300]})

    def _conversation(self, user: str) -> str:
        with self.lock:
            convs = self.conversations[user]
            if convs and self.rng.random() < 0.85:
                return self.rng.choice(convs)
        r = self.clients[user].post("/api/v1/conversations", {"title": "simulação"})
        if r.status != 201:
            raise RuntimeError(f"criar conversa → HTTP {r.status}: {r.text[:200]}")
        cid = r.json()["id"]
        with self.lock:
            self.conversations[user].append(cid)
        return cid

    def _wait_task(self, c: Client, tid: str, want: set[str], timeout: float = 20) -> str:
        deadline = time.monotonic() + timeout
        status = "?"
        while time.monotonic() < deadline:
            r = c.get(f"/api/v1/tasks/{tid}")
            if r.status != 200:  # erro ao consultar: anota e tenta de novo
                status = f"erro HTTP {r.status} ao consultar"
                time.sleep(0.15)
                continue
            status = r.json()["task"]["status"]
            if status in want or status in TERMINAL:
                return status
            time.sleep(0.15)
        return status

    # --- ações ----------------------------------------------------------------------

    def chat_stream(self, user: str) -> Outcome:
        c, cid = self.clients[user], self._conversation(user)
        body = {"content": self.rng.choice(PHRASES), "client_request_id": uuid.uuid4().hex,
                "mode": self.rng.choice(["text", "voice"])}
        t0 = time.perf_counter()
        r = c.post(f"/api/v1/conversations/{cid}/messages/stream", body)
        ms = (time.perf_counter() - t0) * 1000
        if r.status != 200 or "event: done" not in r.text:
            return self._bad("conversa (streaming)", ms, "POST", f"/conversations/{cid}/messages/stream", r, body,
                             f"streaming sem 'done' (HTTP {r.status})")
        return Outcome("conversa (streaming)", True, ms)

    def chat_post_and_retry(self, user: str) -> Outcome:
        c, cid = self.clients[user], self._conversation(user)
        body = {"content": self.rng.choice(PHRASES), "client_request_id": uuid.uuid4().hex}
        t0 = time.perf_counter()
        r1 = c.post(f"/api/v1/conversations/{cid}/messages", body)
        r2 = c.post(f"/api/v1/conversations/{cid}/messages", body)  # reenvio (rede instável)
        ms = (time.perf_counter() - t0) * 1000
        if r1.status != 201 or r1.json().get("reply") is None:
            return self._bad("conversa + reenvio", ms, "POST", f"/conversations/{cid}/messages", r1, body)
        if r2.status not in (200, 201) or not r2.json().get("duplicate"):
            return self._bad("conversa + reenvio", ms, "POST", f"/conversations/{cid}/messages", r2, body,
                             "reenvio com a mesma chave não foi reconhecido como duplicado")
        return Outcome("conversa + reenvio", True, ms)

    def read_conversations(self, user: str) -> Outcome:
        c = self.clients[user]
        t0 = time.perf_counter()
        r = c.get("/api/v1/conversations")
        ok = r.status == 200
        if ok and r.json()["items"]:
            r = c.get(f"/api/v1/conversations/{self.rng.choice(r.json()['items'])['id']}")
            ok = r.status == 200
        ms = (time.perf_counter() - t0) * 1000
        return Outcome("ler conversas", True, ms) if ok else self._bad("ler conversas", ms, "GET", "/conversations", r)

    def task_note(self, user: str) -> Outcome:
        c = self.clients[user]
        step = {"title": "anotar", "action_type": "note", "parameters": {"text": "comprar café"},
                "success_criteria": [{"type": "contains", "value": "café"}]}
        t0 = time.perf_counter()
        r = c.post("/api/v1/tasks", {"title": "simulação", "description": "nota", "steps": [step]})
        if r.status != 201:
            return self._bad("tarefa simples", 0, "POST", "/tasks", r)
        tid = r.json()["task"]["id"]
        with self.lock:
            self.task_ids[user].append(tid)
        r = c.post(f"/api/v1/tasks/{tid}/start", {})
        status = self._wait_task(c, tid, TERMINAL)
        ms = (time.perf_counter() - t0) * 1000
        if status != "COMPLETED":
            return Outcome("tarefa simples", False, ms, f"terminou em {status}", {"task_id": tid})
        return Outcome("tarefa simples", True, ms)

    def task_with_approval(self, user: str) -> Outcome:
        c = self.clients[user]
        step = {"title": "perguntar", "action_type": "ask_model", "parameters": {"prompt": "diga oi"},
                "success_criteria": [{"type": "output_nonempty"}]}
        t0 = time.perf_counter()
        r = c.post("/api/v1/tasks", {"title": "simulação", "description": "aprovação", "steps": [step]})
        d = r.json() if r.status == 201 else {}
        if r.status != 201 or d["task"]["status"] != "PENDING_APPROVAL":
            return self._bad("tarefa com aprovação", 0, "POST", "/tasks", r)
        tid = d["task"]["id"]
        with self.lock:
            self.task_ids[user].append(tid)
        ap = d["approvals"][0]
        r = c.post(f"/api/v1/approvals/{ap['id']}/decision", {"decision": "approve", "scope_hash": ap["scope_hash"]})
        if r.status != 200:
            return self._bad("tarefa com aprovação", 0, "POST", "/approvals/decision", r)
        c.post(f"/api/v1/tasks/{tid}/start", {})
        status = self._wait_task(c, tid, TERMINAL)
        ms = (time.perf_counter() - t0) * 1000
        if status != "COMPLETED":
            return Outcome("tarefa com aprovação", False, ms, f"terminou em {status}", {"task_id": tid})
        return Outcome("tarefa com aprovação", True, ms)

    def task_cancel(self, user: str) -> Outcome:
        c = self.clients[user]
        step = {"title": "perguntar ao usuário", "action_type": "wait_for_user",
                "parameters": {"question": "qual o nome?"}, "success_criteria": [{"type": "output_nonempty"}]}
        t0 = time.perf_counter()
        r = c.post("/api/v1/tasks", {"title": "simulação", "description": "cancelar", "steps": [step]})
        if r.status != 201:
            return self._bad("tarefa cancelada", 0, "POST", "/tasks", r)
        tid = r.json()["task"]["id"]
        c.post(f"/api/v1/tasks/{tid}/start", {})
        self._wait_task(c, tid, {"WAITING_FOR_USER"})
        r = c.post(f"/api/v1/tasks/{tid}/cancel", {"reason": "simulação"})
        status = self._wait_task(c, tid, {"CANCELLED"})
        ms = (time.perf_counter() - t0) * 1000
        if status != "CANCELLED":
            return Outcome("tarefa cancelada", False, ms, f"terminou em {status}", {"task_id": tid})
        return Outcome("tarefa cancelada", True, ms)

    def preferences(self, user: str) -> Outcome:
        c = self.clients[user]
        body = {"response_length": self.rng.choice(["curta", "normal", "detalhada"]),
                "formality": self.rng.choice(["informal", "neutra", "formal"]),
                "examples": self.rng.choice(["auto", "sim", "nao"]), "voice_rate": self.rng.randrange(-30, 31, 5),
                "corrections": [{"heard": "tita", "meant": "Titan"}]}
        t0 = time.perf_counter()
        r = c.request("PUT", "/api/v1/preferences", body)
        ok = r.status == 200 and c.get("/api/v1/preferences").json() == body
        ms = (time.perf_counter() - t0) * 1000
        return Outcome("preferências", True, ms) if ok else self._bad("preferências", ms, "PUT", "/preferences", r, body)

    def status(self, user: str) -> Outcome:
        t0 = time.perf_counter()
        r = self.clients[user].get("/api/v1/system/status")
        ms = (time.perf_counter() - t0) * 1000
        if r.status != 200:
            return self._bad("estado do sistema", ms, "GET", "/system/status", r)
        if not r.json()["audit_chain_ok"]:
            return Outcome("estado do sistema", False, ms, "cadeia de auditoria ADULTERADA", {})
        return Outcome("estado do sistema", True, ms)

    def task_events(self, user: str) -> Outcome:
        with self.lock:
            ids = list(self.task_ids[user])
        if not ids:
            return self.status(user)
        tid = self.rng.choice(ids)
        t0 = time.perf_counter()
        r = self.clients[user].get(f"/api/v1/tasks/{tid}/events?max_seconds=1")
        ms = (time.perf_counter() - t0) * 1000
        return Outcome("eventos ao vivo", True, ms) if r.status == 200 else self._bad("eventos ao vivo", ms, "GET", f"/tasks/{tid}/events", r)

    def voice_stt(self, user: str) -> Outcome:
        if not self.voice or not SAMPLE.exists():
            return self.read_conversations(user)
        c = self.clients[user]
        with wave.open(str(SAMPLE)) as wf:
            pcm = wf.readframes(wf.getnframes())
        t0 = time.perf_counter()
        r = c.post("/api/v1/voice/stt/sessions", {})
        if r.status == 503 and "simultâneas" in r.text:
            # Limite proposital de 2 reconhecimentos ao mesmo tempo (poupa a CPU): esperado.
            return Outcome("voz (recusada pelo limite de sessões)", True, (time.perf_counter() - t0) * 1000)
        if r.status != 201:
            return self._bad("voz (reconhecimento)", 0, "POST", "/voice/stt/sessions", r)
        sid = r.json()["session_id"]
        for i in range(0, len(pcm), 12800):
            c.post(f"/api/v1/voice/stt/sessions/{sid}/audio", raw=pcm[i:i + 12800],
                   headers={"Content-Type": "application/octet-stream"})
        r = c.post(f"/api/v1/voice/stt/sessions/{sid}/finish", {})
        ms = (time.perf_counter() - t0) * 1000
        if r.status != 200 or not r.json()["text"]:
            return self._bad("voz (reconhecimento)", ms, "POST", f"/voice/stt/sessions/{sid}/finish", r,
                             why="reconhecimento sem texto")
        return Outcome("voz (reconhecimento)", True, ms)

    def actions(self) -> list[tuple[Callable[[str], Outcome], int]]:
        return [(self.chat_stream, 5), (self.chat_post_and_retry, 3), (self.read_conversations, 3),
                (self.task_note, 2), (self.task_with_approval, 2), (self.task_cancel, 1),
                (self.preferences, 1), (self.status, 2), (self.task_events, 1), (self.voice_stt, 2)]

    def random_action(self, rng: random.Random) -> Outcome:
        acts = self.actions()
        fn = rng.choices([a for a, _ in acts], weights=[w for _, w in acts])[0]
        user = rng.choice(self.server.USERS)
        try:
            return fn(user)
        except Exception as exc:  # conexão recusada, timeout, JSON inválido…
            return Outcome(fn.__name__, False, 0, f"{type(exc).__name__}: {exc}"[:300],
                           {"action": fn.__name__, "user": user})

    def run_for(self, seconds: float, workers: int, stop: Callable[[], bool] = lambda: False) -> list[Outcome]:
        out: list[Outcome] = []
        deadline = time.monotonic() + seconds

        def loop(i: int) -> None:
            rng = random.Random(self.rng.random() + i)
            while time.monotonic() < deadline and not stop():
                o = self.random_action(rng)
                with self.lock:
                    out.append(o)

        threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return out
