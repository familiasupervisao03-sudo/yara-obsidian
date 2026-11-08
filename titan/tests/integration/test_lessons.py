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
    assert script.build_style() in MockProvider.last_style  # a instrução da aula foi ao modelo
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


def test_new_scene_types_are_validated():
    raw = {"titulo": "T", "assunto": "inventado", "cenas": [
        {"tipo": "capa", "titulo": "Aula", "itens": ["a", "b"], "icone": "folha", "icones_itens": ["sol", "xyz"]},
        {"tipo": "destaque", "titulo": "Dado", "destaque": {"valor": "21%", "rotulo": "do ar", "percentual": 250}},
        {"tipo": "destaque", "titulo": "Sem valor", "narracao": "n", "destaque": {"valor": ""}},
        {"tipo": "mapa_mental", "titulo": "Mapa", "centro": "", "itens": ["x", "y", "z"]},
        {"tipo": "erro_comum", "titulo": "Erro", "erro_comum": {"errado": "A planta come terra", "certo": "Ela fabrica"}},
        {"tipo": "tabela", "titulo": "Tab", "tabela": {"colunas": ["a", "b"], "linhas": [["1"], ["2", "3", "4"], 5]}},
        {"tipo": "teoria", "titulo": "Sua ideia", "teoria": {"ideia": "A lua faz a planta crescer",
                                                           "veredito": "talvez", "certo": [], "errado": ["não"]}},
        {"tipo": "pergunta", "pergunta": {"enunciado": "?", "opcoes": ["a", "b"], "correta": 1, "revisar_cena": 1}},
        {"tipo": "pergunta", "pergunta": {"enunciado": "?", "opcoes": ["a", "b"], "correta": 0, "revisar_cena": 7}},
    ]}
    out = script.sanitize(raw)
    c = out["cenas"]
    assert out["assunto"] == "outro"
    assert c[0]["icone"] == "folha" and c[0]["icones_itens"] == ["sol", "nenhum"]
    assert c[1]["destaque"]["percentual"] == -1  # fora de 0–100 não vira porcentagem
    assert c[2]["tipo"] == "topicos"  # destaque sem valor
    assert c[3]["centro"] == "Mapa"
    assert c[5]["tabela"]["linhas"] == [["1", ""], ["2", "3"]]
    assert c[6]["teoria"]["veredito"] == "não dá para saber"
    assert c[7]["pergunta"]["revisar_cena"] == 1 and c[8]["pergunta"]["revisar_cena"] == -1  # não aponta p/ pergunta
    assert all(x["tipo"] != "capa" for x in script.sanitize(raw, continuation=True)["cenas"])


def test_style_by_level_length_and_continuation():
    quick = script.build_style("crianca", "rapida")
    assert "criança" in quick and "de 4 a 6 cenas" in quick and "1 cena(s) \"pergunta\"" in quick
    full = script.build_style("avancado", "completa")
    assert "de 11 a 16 cenas" in full and "3 cena(s)" in full
    parent = {"titulo": "Fotossíntese", "cenas": [{"titulo": "Ciclo", "narracao": "luz e água"}]}
    cont = script.build_style("basico", "normal", parent, focus=0)
    assert "CONTINUAÇÃO" in cont and "\"Ciclo\"" in cont and "teoria" in cont and "SEM \"capa\"" in cont
    assert "MAIS SIMPLES" in script.build_style(parent=parent, focus=0, simpler=True)
    assert script.max_tokens("completa", False) > script.max_tokens("rapida", False)


def test_continuation_flow_and_ownership(chat):
    c, cid, s = chat
    MockProvider.json_reply = GOOD
    first = c.post(f"/api/v1/conversations/{cid}/lessons", json={"content": "explica em vídeo a fotossíntese"},
                   headers=CSRF).json()
    parent_id = first["reply"]["id"]
    MockProvider.json_reply = {"titulo": "Sua pergunta", "assunto": "ciencia", "cenas": [
        dict(GOOD["cenas"][0], tipo="capa"), dict(GOOD["cenas"][0], titulo="Resposta")]}
    r = c.post(f"/api/v1/conversations/{cid}/lessons", json={
        "content": "e se a planta ficar no escuro?", "continues": parent_id, "focus_scene": 1,
        "level": "crianca"}, headers=CSRF).json()
    assert r["lesson"]["continua"] == parent_id and r["lesson"]["nivel"] == "crianca"
    assert [x["tipo"] for x in r["lesson"]["cenas"]] == ["topicos"]  # sem capa na continuação
    assert "CONTINUAÇÃO" in MockProvider.last_style and "\"Ciclo\"" in MockProvider.last_style
    # continuar aula de outra conversa ou inexistente: 404
    other = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    assert c.post(f"/api/v1/conversations/{other}/lessons", json={"content": "x", "continues": parent_id},
                  headers=CSRF).status_code == 404
    c.post("/api/v1/auth/logout", headers=CSRF)
    login(c, "outro")
    mine = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    assert c.post(f"/api/v1/conversations/{mine}/lessons", json={"content": "x", "continues": parent_id},
                  headers=CSRF).status_code == 404
