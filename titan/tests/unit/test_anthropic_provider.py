"""Adaptador Anthropic com cliente FALSO: nenhuma chamada de rede ou cobrança real."""

from types import SimpleNamespace

import pytest

from titan.db.engine import make_engine, make_session_factory
from titan.db.models import ModelUsage
from titan.models.anthropic_provider import AnthropicProvider, to_api_messages
from titan.models.providers import ChatTurn, ModelUnavailable
from titan.policies.budget import BudgetGuard, cost_brl
from titan.policies.model_gate import ProviderBlocked

KEY = "sk-ant-teste-chave-falsa-0123456789abcdef"


class FakeAPIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"erro {status_code}")
        self.status_code = status_code


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response
        self.error = error
        create = self._create
        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.response


def response(text="Olá!", stop="end_turn", inp=100, out=50, model="claude-opus-5-5"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop, stop_details=None, model=model, _request_id="req_teste",
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )


@pytest.fixture
def paid_settings(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="anthropic", model_name="claude-opus-5-5", local_only=False,
                      allow_external_models=True, allow_paid_apis=True,
                      daily_paid_budget_brl=2.0, usd_brl_rate=5.0, anthropic_api_key=KEY,
                      model_max_output_tokens=1000)
    upgrade_head(s.database_url)
    return s


@pytest.fixture
def factory(paid_settings):
    engine = make_engine(paid_settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def rows(factory):
    with factory() as db:
        return db.query(ModelUsage).all()


def test_successful_call_records_real_cost(paid_settings, factory):
    client = FakeClient(response(inp=1000, out=500))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    reply = p.chat([ChatTurn("user", "oi")])
    assert reply.content == "Olá!" and reply.provider == "anthropic"
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 1000
    assert call["messages"] == [{"role": "user", "content": "oi"}]
    assert call["fallbacks"] == "default"  # fallback do servidor ativado por padrão
    assert KEY not in str(call)
    (row,) = rows(factory)
    assert row.status == "FINAL"
    # 1000 * $4/M + 500 * $20/M = $0.014 -> R$ 0.07
    assert row.cost_brl == pytest.approx(0.07)
    assert row.cost_brl == pytest.approx(cost_brl(paid_settings, "claude-opus-5-5", 1000, 500))


def test_budget_blocks_before_sending(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="anthropic", model_name="claude-opus-5-5", local_only=False,
                      allow_external_models=True, allow_paid_apis=True,
                      daily_paid_budget_brl=0.01, usd_brl_rate=5.0, anthropic_api_key=KEY)
    upgrade_head(s.database_url)
    engine = make_engine(s.database_url)
    f = make_session_factory(engine)
    client = FakeClient(response())
    p = AnthropicProvider(s, BudgetGuard(s, f), client=client)
    with pytest.raises(ProviderBlocked, match="NÃO foi enviada"):
        p.chat([ChatTurn("user", "oi")])
    assert client.calls == []  # nada foi enviado
    assert rows(f) == []
    engine.dispose()


def test_daily_budget_accumulates(paid_settings, factory):
    # 1ª chamada gasta R$ 1,90 de R$ 2,00; a reserva de pior caso da 2ª não cabe.
    client = FakeClient(response(inp=20_000, out=15_000))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    p.chat([ChatTurn("user", "1")])
    assert BudgetGuard(paid_settings, factory).spent_today() == pytest.approx(1.90)
    with pytest.raises(ProviderBlocked):
        p.chat([ChatTurn("user", "2")])
    assert len(client.calls) == 1


def test_auth_error_is_reported_and_not_charged(paid_settings, factory):
    client = FakeClient(error=FakeAPIError(401))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    with pytest.raises(ModelUnavailable, match="Chave da Anthropic inválida"):
        p.chat([ChatTurn("user", "oi")])
    (row,) = rows(factory)
    assert row.status == "FAILED" and row.cost_brl == 0.0


def test_connection_error_keeps_conservative_reservation(paid_settings, factory):
    client = FakeClient(error=TimeoutError("sem resposta"))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    with pytest.raises(ModelUnavailable, match="conexão"):
        p.chat([ChatTurn("user", "oi")])
    (row,) = rows(factory)
    assert row.status == "FAILED" and row.cost_brl > 0  # incerto: conta como gasto


def test_refusal_is_reported_honestly(paid_settings, factory):
    client = FakeClient(response(text="", stop="refusal"))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    assert "recusou" in p.chat([ChatTurn("user", "x")]).content


def test_empty_reply_is_an_error_not_success(paid_settings, factory):
    client = FakeClient(response(text="", stop="end_turn"))
    p = AnthropicProvider(paid_settings, BudgetGuard(paid_settings, factory), client=client)
    with pytest.raises(ModelUnavailable):
        p.chat([ChatTurn("user", "x")])


def test_history_is_normalized():
    msgs = to_api_messages([
        ChatTurn("assistant", "sobra"), ChatTurn("user", "a"), ChatTurn("user", "b"),
        ChatTurn("system", "ignorar"), ChatTurn("assistant", "c"),
    ])
    assert msgs == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"}]


def test_unknown_model_priced_at_worst_case(paid_settings):
    assert cost_brl(paid_settings, "modelo-novo", 1_000_000, 0) == pytest.approx(50.0)
