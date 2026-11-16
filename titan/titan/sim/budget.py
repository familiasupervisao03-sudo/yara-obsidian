"""Simulação do orçamento da Anthropic com um cliente FALSO (sem rede, sem gasto).

Centenas de chamadas, em várias threads ao mesmo tempo, com respostas de tamanhos
aleatórios, erros antes da geração (não cobrados), quedas de conexão (cobrança
incerta) e respostas interrompidas pelo usuário no meio do streaming. O cliente
falso registra o que uma API real teria cobrado; o simulador confere:

* o total registrado no dia nunca passa do orçamento;
* o registrado nunca fica abaixo do que teria sido cobrado de verdade;
* nenhuma reserva fica pendurada; cada envio tem exatamente um registro;
* depois de esgotado, nada mais é enviado (o cliente falso não é chamado).
"""

from __future__ import annotations

import random
import threading
from pathlib import Path
from types import SimpleNamespace

from titan.sim.core import Context, RoundResult


class _FakeAPIError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"erro {status_code}")
        self.status_code = status_code


class FakeAnthropic:
    """Imita messages.create / messages.stream e anota a cobrança "real"."""

    def __init__(self, rng: random.Random, settings, prices) -> None:
        self.rng = rng
        self.settings = settings
        self.prices = prices
        self.lock = threading.Lock()
        self.sent = 0
        self.charged_brl = 0.0
        self.max_seen_input_ratio = 0.0
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)
        self.beta = SimpleNamespace(messages=self.messages)

    def _charge(self, model: str, inp: int, out: int) -> None:
        from titan.policies.budget import cost_brl

        with self.lock:
            self.charged_brl += cost_brl(self.settings, model, inp, out)

    def _plan(self, kw: dict) -> dict:
        """Sorteia o que esta chamada "faz" na API, como uma API real faria."""
        chars = len(kw.get("system", "")) + sum(len(m["content"]) for m in kw["messages"])
        # Texto com muitos números/símbolos tem mais tokens por caractere: varia de 2 a 4,5.
        inp = int(chars / self.rng.uniform(2.0, 4.5)) + 10
        out = self.rng.randint(1, kw["max_tokens"])
        served = kw["model"] if self.rng.random() < 0.9 else self.rng.choice(list(self.prices))
        roll = self.rng.random()
        kind = "ok" if roll < 0.75 else "http_error" if roll < 0.85 else "timeout" if roll < 0.95 else "refusal"
        with self.lock:
            self.sent += 1
        return {"inp": inp, "out": out, "served": served, "kind": kind}

    def _response(self, p: dict, text: str = "resposta simulada"):
        stop = "refusal" if p["kind"] == "refusal" else "end_turn"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, stop_details=None,
            model=p["served"], _request_id="req_sim",
            usage=SimpleNamespace(input_tokens=p["inp"], output_tokens=p["out"],
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))

    def _create(self, **kw):
        p = self._plan(kw)
        if p["kind"] == "http_error":
            raise _FakeAPIError(self.rng.choice([400, 429, 500, 529]))  # antes da geração: sem cobrança
        if p["kind"] == "timeout":
            if self.rng.random() < 0.5:  # a API pode ter cobrado parte antes de cair
                self._charge(p["served"], p["inp"], self.rng.randint(0, p["out"]))
            raise TimeoutError("conexão caiu")
        self._charge(p["served"], p["inp"], p["out"])
        return self._response(p)

    def _stream(self, **kw):
        fake = self
        p = self._plan(kw)

        class _Stream:
            def __enter__(self):
                if p["kind"] == "http_error":
                    raise _FakeAPIError(500)
                return self

            def __exit__(self, *exc):
                return False

            @property
            def text_stream(self):
                if p["kind"] == "timeout":
                    if fake.rng.random() < 0.5:
                        fake._charge(p["served"], p["inp"], fake.rng.randint(0, p["out"]))
                    raise TimeoutError("conexão caiu no meio")
                for i in range(5):
                    yield f"pedaço {i} "

            def get_final_message(self):
                fake._charge(p["served"], p["inp"], p["out"])
                return fake._response(p)

        return _Stream()


def run(ctx: Context) -> RoundResult:
    """Uma rodada = várias simulações independentes (sementes derivadas) no tempo da rodada."""
    import time

    res = RoundResult("orcamento", ctx.seed)
    deadline = time.monotonic() + min(ctx.seconds, 60 if not ctx.quick else 5)
    runs, totals = 0, {"sent": 0, "blocked": 0, "aborted": 0, "unavailable": 0}
    worst_pct, retained = 0.0, 0.0
    while runs < 3 or (time.monotonic() < deadline and runs < 40):
        one = _one(ctx, ctx.seed * 1000 + runs)
        runs += 1
        for c in one.checks:
            if not c.ok:
                res.check(f"{c.name} (simulação {one.seed})", False, c.detail)
        res.failures.extend(one.failures)
        for k in totals:
            totals[k] += one.metrics.get(k, 0)
        worst_pct = max(worst_pct, one.metrics["ledger_pct_of_budget"])
        retained += one.metrics["ledger_brl"] - one.metrics["charged_brl"]
    if not any(not c.ok for c in res.checks):
        res.check(f"{runs} simulações: orçamento nunca ultrapassado e registro nunca abaixo do cobrado", True)
    res.metrics.update(simulations=runs, max_ledger_pct_of_budget=worst_pct,
                       retained_by_uncertain_failures_brl=round(retained, 4), **totals)
    res.notes.append("Quedas e interrupções mantêm a reserva do pior caso (conservador): o "
                     "registrado fica acima do cobrado e o limite do dia chega antes.")
    return res


def _one(ctx: Context, seed: int) -> RoundResult:
    from sqlalchemy import func, select

    from titan.config.settings import Settings
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.migrate import upgrade_head
    from titan.db.models import ModelUsage
    from titan.models.anthropic_provider import AnthropicProvider
    from titan.models.providers import ChatTurn, ModelUnavailable
    from titan.policies.budget import ANTHROPIC_PRICES_USD_PER_MTOK, BudgetGuard, cost_brl, today
    from titan.policies.model_gate import ProviderBlocked

    rng = random.Random(seed)
    res = RoundResult("orcamento", seed)
    db = Path(ctx.workdir) / "orcamento.db"
    db.unlink(missing_ok=True)
    url = f"sqlite:///{db}"
    upgrade_head(url)
    model = rng.choice(list(ANTHROPIC_PRICES_USD_PER_MTOK))
    budget = round(rng.uniform(0.5, 10.0), 2)
    s = Settings(_env_file=None, env="test", auth_secret="x" * 40, model_provider="anthropic",
                 model_name=model, local_only=False, allow_external_models=True, allow_paid_apis=True,
                 daily_paid_budget_brl=budget, usd_brl_rate=round(rng.uniform(5.0, 6.5), 2),
                 anthropic_api_key="sk-ant-simulacao-chave-falsa-000000000000",
                 model_max_output_tokens=rng.choice([256, 512, 1024, 2048]))
    engine = make_engine(url)
    factory = make_session_factory(engine)
    fake = FakeAnthropic(rng, s, ANTHROPIC_PRICES_USD_PER_MTOK)
    guard = BudgetGuard(s, factory)
    calls = 40 if ctx.quick else rng.randint(150, 400)
    counters = {"ok": 0, "blocked": 0, "unavailable": 0, "aborted": 0}
    lock = threading.Lock()
    work = list(range(calls))
    texts = ["oi", "me explica o backup " * 20, "1234567890 {}[]() " * 200, "a " * 3000]

    def worker(wid: int) -> None:
        local = random.Random(seed * 100 + wid)
        provider = AnthropicProvider(s, guard, client=fake)
        while True:
            with lock:
                if not work:
                    return
                work.pop()
            history = [ChatTurn("user", local.choice(texts)) for _ in range(local.randint(1, 4))]
            try:
                if local.random() < 0.5:
                    provider.chat(history)
                else:
                    gen = provider.chat_stream(history)
                    for i, (kind, _) in enumerate(gen):
                        if kind == "delta" and i == 1 and local.random() < 0.3:
                            gen.close()  # usuário interrompeu a resposta
                            with lock:
                                counters["aborted"] += 1
                            break
                with lock:
                    counters["ok"] += 1
            except ProviderBlocked:
                with lock:
                    counters["blocked"] += 1
            except ModelUnavailable:
                with lock:
                    counters["unavailable"] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Chamada recusada pelo orçamento NUNCA pode chegar ao cliente (a recusa vem antes do envio).
    before = fake.sent
    try:
        AnthropicProvider(s, guard, client=fake).chat([ChatTurn("user", "a " * 3000)])
        res.metrics["final_call"] = "enviada (havia espaço no limite)"
    except ProviderBlocked:
        res.check("chamada recusada pelo orçamento não é enviada", fake.sent == before,
                  f"envios antes {before}, depois {fake.sent}")
        res.metrics["final_call"] = "recusada"
    except ModelUnavailable:
        res.metrics["final_call"] = "falhou (erro simulado da API)"

    with factory() as d:
        rows = d.scalars(select(ModelUsage).where(ModelUsage.day == today())).all()
        ledger = float(d.scalar(select(func.coalesce(func.sum(ModelUsage.cost_brl), 0.0))) or 0.0)
    engine.dispose()
    pending = [r for r in rows if r.status == "RESERVED"]
    bad_final = [r for r in rows if r.status == "FINAL"
                 and abs(r.cost_brl - cost_brl(s, r.model, r.input_tokens or 0, r.output_tokens or 0)) > 1e-6]
    res.metrics.update(model=model, budget_brl=budget, calls=calls, sent=fake.sent, rows=len(rows),
                       ledger_brl=round(ledger, 6), charged_brl=round(fake.charged_brl, 6),
                       ledger_pct_of_budget=round(100 * ledger / budget, 1), **counters)
    res.check("registrado ≤ orçamento", ledger <= budget + 1e-9, f"R$ {ledger:.4f} de R$ {budget:.2f}")
    ok = res.check("registrado ≥ cobrado de verdade", fake.charged_brl <= ledger + 1e-9,
                   f"cobrado R$ {fake.charged_brl:.4f}, registrado R$ {ledger:.4f}")
    if not ok:
        res.fail("O custo real passou do registrado (o orçamento subestimou alguma chamada).",
                 seed=seed, model=model, budget=budget)
    res.check("nenhuma reserva pendurada", not pending, f"{len(pending)} pendentes")
    res.check("um registro por envio", len(rows) == fake.sent, f"{len(rows)} registros, {fake.sent} envios")
    res.check("custo final recalculado confere", not bad_final, f"{len(bad_final)} divergentes")
    if ledger > budget + 1e-9:
        res.fail("O total registrado passou do orçamento diário.", seed=seed, model=model,
                 budget=budget, ledger=ledger)
    return res
