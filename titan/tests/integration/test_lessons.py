"""Vídeo-aulas: roteiro estruturado, validação, armazenamento por usuário e idempotência."""

import pytest

from tests.conftest import CSRF, build_client, create_user, login
from titan.lessons import script
from titan.models.providers import MockProvider

GOOD = {
    "titulo": "Fotossíntese",
    "cenas": [
        {"tipo": "topicos", "titulo": "O que é", "narracao": "A planta faz o próprio alimento.",
         "itens": ["luz", "água", "gás carbônico"],
         "comparacao": {"a_titulo": "", "a_itens": [], "b_titulo": "", "b_itens": []},
         "grafico": {"forma": "", "unidade": "", "dados": []}, "diagrama_forma": "",
         "pergunta": {"enunciado": "", "opcoes": [], "correta": 0, "explicacao": ""}},
        {"tipo": "diagrama", "titulo": "Ciclo", "narracao": "Veja o ciclo.", "itens": ["luz", "folha", "açúcar"],
         "comparacao": {"a_titulo": "", "a_itens": [], "b_titulo": "", "b_itens": []},
         "grafico": {"forma": "", "unidade": "", "dados": []}, "diagrama_forma": "ciclo",
         "pergunta": {"enunciado": "", "opcoes": [], "correta": 0, "explicacao": ""}},
        {"tipo": "grafico", "titulo": "Sem dados", "narracao": "x", "itens": [],
         "comparacao": {"a_titulo": "", "a_itens": [], "b_titulo": "", "b_itens": []},
         "grafico": {"forma": "barras", "unidade": "%", "dados": [{"rotulo": "a", "valor": float("nan")}]},
         "diagrama_forma": "", "pergunta": {"enunciado": "", "opcoes": [], "correta": 0, "explicacao": ""}},
        {"tipo": "pergunta", "titulo": "", "narracao": "Responda.", "itens": [],
         "comparacao": {"a_titulo": "", "a_itens": [], "b_titulo": "", "b_itens": []},
         "grafico": {"forma": "", "unidade": "", "dados": []}, "diagrama_forma": "",
         "pergunta": {"enunciado": "A planta precisa de quê?", "opcoes": ["luz", "sal"], "correta": 0,
                      "explicacao": "Sem luz não há fotossíntese."}},
        {"tipo": "pergunta", "titulo": "Quebrada", "narracao": "", "itens": [],
         "comparacao": {"a_titulo": "", "a_itens": [], "b_titulo": "", "b_itens": []},
         "grafico": {"forma": "", "unidade": "", "dados": []}, "diagrama_forma": "",
         "pergunta": {"enunciado": "?", "opcoes": ["a"], "correta": 5, "explicacao": ""}},
    ],
}


def test_sanitize_limits_and_fixes():
    raw = {"titulo": "x" * 500, "cenas": [dict(GOOD["cenas"][0], narracao="a " * 2000,
                                                 itens=["i"] * 30, tipo="hackeado")] * 30}
    out = script.sanitize(raw)
    assert len(out["cenas"]) == script.MAX_SCENES and len(out["titulo"]) <= 90
    s = out["cenas"][0]
    assert s["tipo"] == "topicos" and len(s["narracao"]) <= script.MAX_NARRATION and len(s["itens"]) == 6
    good = script.sanitize(GOOD)
    kinds = [c["tipo"] for c in good["cenas"]]
    assert kinds == ["topicos", "diagrama", "topicos", "pergunta"]  # gráfico sem dados vira tópicos; pergunta quebrada sai
    assert good["cenas"][3]["titulo"] == "Teste rápido"


@pytest.mark.parametrize("text,wanted", [
    ("explica em vídeo como funciona a fotossíntese", True), ("me explica a fotossíntese em video", True),
    ("faz uma vídeo aula sobre frações", True), ("cria uma aula sobre o sistema solar", True),
    ("me mostra um video de gato", False), ("explica a fotossíntese", False),
])
def test_lesson_request_detection(text, wanted):
    assert script.wants_lesson(text) is wanted


@pytest.fixture
def chat(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="mock")
    upgrade_head(s.database_url)
    create_user(s)
    create_user(s, "outro")
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        yield c, cid, s
    MockProvider.json_reply = None


def test_create_play_and_isolation(chat):
    c, cid, s = chat
    MockProvider.json_reply = GOOD
    r = c.post(f"/api/v1/conversations/{cid}/lessons",
               json={"content": "explica em vídeo a fotossíntese", "client_request_id": "aula-0001"}, headers=CSRF)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["model"]["available"] and len(body["lesson"]["cenas"]) == 4
    assert script.STYLE in MockProvider.last_style  # a instrução da aula foi ao modelo
    reply = body["reply"]
    assert reply["content"].startswith(script.MARKER + "Fotossíntese")
    assert "(resposta: luz)" in reply["content"]
    got = c.get(f"/api/v1/lessons/{reply['id']}").json()
    assert got["lesson"]["titulo"] == "Fotossíntese"
    # reenvio com a mesma chave não cria outra aula
    again = c.post(f"/api/v1/conversations/{cid}/lessons",
                   json={"content": "explica em vídeo a fotossíntese", "client_request_id": "aula-0001"},
                   headers=CSRF).json()
    assert again["duplicate"] and again["reply"]["id"] == reply["id"] and again["lesson"]["titulo"] == "Fotossíntese"
    msgs = c.get(f"/api/v1/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    # outro usuário não vê a aula
    c.post("/api/v1/auth/logout", headers=CSRF)
    login(c, "outro")
    assert c.get(f"/api/v1/lessons/{reply['id']}").status_code == 404
    assert c.post(f"/api/v1/conversations/{cid}/lessons", json={"content": "x"}, headers=CSRF).status_code == 404


def test_no_valid_scene_and_no_model(chat, make_settings):
    c, cid, _ = chat
    MockProvider.json_reply = {"titulo": "vazio", "cenas": [{"tipo": "pergunta", "pergunta": {}}]}
    body = c.post(f"/api/v1/conversations/{cid}/lessons", json={"content": "aula"}, headers=CSRF).json()
    assert body["reply"] is None and not body["model"]["available"] and "nenhuma cena" in body["model"]["detail"]
