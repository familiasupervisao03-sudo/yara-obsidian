"""Segurança: requisições indevidas e malformadas em todas as rotas da API.

Rotas tiradas do contrato (packages/api-contracts/openapi.json). Confere:
* sem login: nada responde com sucesso (401, ou 403 sem o cabeçalho anti-CSRF);
* logado, mas sem o cabeçalho anti-CSRF ou com Origin de outro site: métodos que
  alteram dados são recusados (403);
* recursos de outro usuário: 404, nunca os dados;
* corpos e parâmetros aleatórios/malformados/enormes: nunca erro 500;
* nenhuma resposta contém segredo (segredo do servidor, hash de senha, chave de API);
* tentativas seguidas de senha errada: bloqueio temporário (429).
"""

from __future__ import annotations

import json
import random
import string
import uuid
from pathlib import Path

from titan.sim.core import Context, RoundResult
from titan.sim.server import Client

CONTRACT = Path(__file__).resolve().parents[2] / "packages/api-contracts/openapi.json"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
EXPECTED_503 = {"voice_unavailable"}


def routes() -> list[tuple[str, str]]:
    spec = json.loads(CONTRACT.read_text())
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops
            if m.upper() in {"GET", *UNSAFE} and p.startswith("/api/")]


def _junk(rng: random.Random, depth: int = 0):
    kind = rng.randrange(9 if depth < 2 else 6)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False, 0, -1, 2**63, 1e308, -0.0])
    if kind == 2:
        return "".join(rng.choice(string.printable) for _ in range(rng.randrange(0, 40)))
    if kind == 3:
        return rng.choice(["../../etc/passwd", "' OR 1=1 --", "<script>alert(1)</script>", "\u0000", "🙂" * 50,
                           "a" * 100_000, "%00", "${jndi:ldap://x}"])
    if kind == 4:
        return str(uuid.uuid4())
    if kind == 5:
        return rng.choice(["voice", "approve", "reject", "curta", "PENDING"])
    if kind == 6:
        return [_junk(rng, depth + 1) for _ in range(rng.randrange(0, 5))]
    keys = ["content", "title", "description", "steps", "decision", "scope_hash", "mode", "text",
            "client_request_id", "retry_uncertain", "corrections", "voice_rate", "username", "password",
            rng.choice(string.ascii_letters)]
    return {rng.choice(keys): _junk(rng, depth + 1) for _ in range(rng.randrange(0, 6))}


def _fill(path: str, value: str) -> str:
    out, i = "", 0
    while i < len(path):
        if path[i] == "{":
            j = path.index("}", i)
            out += value
            i = j + 1
        else:
            out += path[i]
            i += 1
    return out


def run(ctx: Context) -> RoundResult:
    rng = random.Random(ctx.seed)
    res = RoundResult("seguranca", ctx.seed)
    srv = ctx.server()
    secrets_markers = [srv.secret, "password_hash", "token_hash", "sk-ant-", "scrypt$"]
    alice, bob = srv.client("alice"), srv.client("bob")
    anon = Client(srv.base)
    all_routes = routes()
    leaks, five_xx = [], []

    def inspect(r, method, path, body) -> None:
        # 503 com código conhecido (ex.: voz não instalada) é resposta correta; o resto é erro interno.
        try:
            data = r.json()
            code = data.get("error", {}).get("code") if isinstance(data, dict) else None
        except ValueError:
            code = None
        if r.status >= 500 and not (r.status == 503 and code in EXPECTED_503):
            five_xx.append({"method": method, "path": path, "status": r.status, "body": body, "response": r.text[:200]})
        text = r.text
        for m in secrets_markers:
            if m and m in text:
                leaks.append({"method": method, "path": path, "marker": m[:12] + "…"})

    # Recursos da alice para os testes de outro usuário
    cid = alice.post("/api/v1/conversations", {"title": "da alice"}).json()["id"]
    task = alice.post("/api/v1/tasks", {"title": "da alice", "description": "x", "steps": [
        {"title": "perguntar", "action_type": "ask_model", "parameters": {"prompt": "oi"},
         "success_criteria": [{"type": "output_nonempty"}]}]}).json()
    tid, aid = task["task"]["id"], task["approvals"][0]["id"]

    # 1. sem login
    open_routes = []
    for method, path in all_routes:
        if path == "/api/v1/auth/login":
            continue
        concrete = _fill(path, str(uuid.uuid4()))
        r = anon.request(method, concrete, body={} if method in UNSAFE else None)
        inspect(r, method, concrete, {})
        if r.status not in (401, 403):
            open_routes.append(f"{method} {concrete} → {r.status}")
    res.check(f"{len(all_routes)} rotas sem login: todas recusadas", not open_routes, "; ".join(open_routes[:5]))
    for o in open_routes[:5]:
        res.fail(f"Rota respondeu sem login: {o}")

    # 2. sem cabeçalho anti-CSRF / com Origin de outro site
    csrf_bad, origin_bad = [], []
    for method, path in all_routes:
        if method not in UNSAFE or path == "/api/v1/auth/login":
            continue
        concrete = _fill(path, cid)
        r = alice.request(method, concrete, body={}, csrf=False)
        if r.status != 403:
            csrf_bad.append(f"{method} {concrete} → {r.status}")
        r = alice.request(method, concrete, body={}, headers={"Origin": "https://site-malicioso.example"})
        if r.status != 403:
            origin_bad.append(f"{method} {concrete} → {r.status}")
    res.check("sem cabeçalho anti-CSRF: alterações recusadas", not csrf_bad, "; ".join(csrf_bad[:5]))
    res.check("Origin de outro site: alterações recusadas", not origin_bad, "; ".join(origin_bad[:5]))
    for o in (csrf_bad + origin_bad)[:5]:
        res.fail(f"Proteção contra requisição forjada falhou: {o}")

    # 3. outro usuário
    cross = []
    for method, path, body in [("GET", f"/api/v1/conversations/{cid}", None),
                               ("POST", f"/api/v1/conversations/{cid}/messages", {"content": "invasão"}),
                               ("GET", f"/api/v1/tasks/{tid}", None),
                               ("POST", f"/api/v1/tasks/{tid}/start", {}),
                               ("POST", f"/api/v1/tasks/{tid}/cancel", {}),
                               ("POST", f"/api/v1/approvals/{aid}/decision", {"decision": "approve",
                                                                              "scope_hash": task["approvals"][0]["scope_hash"]})]:
        r = bob.request(method, path, body=body)
        inspect(r, method, path, body)
        if r.status != 404:
            cross.append(f"{method} {path} → {r.status}")
    bob_sees = [t["id"] for t in bob.get("/api/v1/tasks").json()["items"]]
    if tid in bob_sees:
        cross.append("lista de tarefas do bob contém a da alice")
    res.check("outro usuário não acessa nada da alice", not cross, "; ".join(cross))
    for o in cross:
        res.fail(f"Isolamento entre usuários falhou: {o}")

    # 4. aleatório / malformado
    n = 150 if ctx.quick else 1500
    for _ in range(n):
        method, path = rng.choice(all_routes)
        param = rng.choice([cid, tid, aid, str(uuid.uuid4()), "nao-e-uuid", "..%2F..%2Fetc", "1" * 300, "%00"])
        concrete = _fill(path, param)
        if path.endswith("/events"):
            concrete += "?max_seconds=1"  # transmissão ao vivo: fica aberta de propósito
        if rng.random() < 0.1:
            raw = rng.choice([b"{", b"\xff\xfe", b"[]" * 50_000, b"null", b"x" * 300_000])
            r = alice.request(method, concrete, raw=raw, headers={"Content-Type": "application/json"})
            body = f"<{len(raw)} bytes brutos>"
        else:
            body = _junk(rng)
            r = alice.request(method, concrete, body=body if method in UNSAFE else None)
            body = json.dumps(body, ensure_ascii=False, default=str)[:300]
        inspect(r, method, concrete, body)
    res.check(f"{n} requisições aleatórias/malformadas: nenhum erro interno", not five_xx, f"{len(five_xx)} erros internos")
    for f in five_xx[:10]:
        res.fail(f"Erro interno ({f['status']}) em {f['method']} {f['path']}", **f)
    res.check("nenhum segredo em respostas", not leaks, str(leaks[:3]))
    for f in leaks[:5]:
        res.fail("Segredo apareceu numa resposta.", **f)

    # 5. senha errada seguida → bloqueio (num nome que não existe, para não bloquear a
    # alice nas próximas rodadas; o TITAN trata usuário inexistente do mesmo jeito)
    brute = Client(srv.base)
    target = f"atacante-{ctx.seed}"
    statuses = [brute.login(target, "senha-errada-" + str(i)).status for i in range(8)]
    res.check("senhas erradas seguidas: bloqueio temporário (429)", 429 in statuses, str(statuses))
    res.metrics.update(routes=len(all_routes), fuzz_requests=n, errors_500=len(five_xx), leaks=len(leaks),
                       login_statuses=statuses)
    return res
