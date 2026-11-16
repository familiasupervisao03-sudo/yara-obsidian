"""TITAN.md: o manual de cada conta (editar, histórico, desfazer, sugestões aprovadas pelo dono)."""

from tests.conftest import CSRF, build_client, create_user, login


def test_manual_editar_desfazer_e_vai_para_a_conversa(auth_client, settings):
    c = auth_client
    m = c.get("/api/v1/brain/manual").json()
    assert m["is_template"] is True and "## Como falar comigo" in m["content"] and m["history"] == []
    texto = "# Como o TITAN age comigo\n\n## Como falar comigo\n- Respostas curtas.\n"
    r = c.put("/api/v1/brain/manual", json={"content": texto}, headers=CSRF)
    assert r.status_code == 200 and r.json()["content"] == texto and r.json()["is_template"] is False
    r = c.put("/api/v1/brain/manual", json={"content": texto + "- Me chame de Luiz.\n"}, headers=CSRF)
    assert "Me chame de Luiz" in r.json()["content"] and len(r.json()["history"]) == 2
    r = c.post("/api/v1/brain/manual/undo", headers=CSRF)
    assert r.json()["content"] == texto and r.json()["history"][0]["source"] == "desfazer"
    # o manual vai junto da conversa (contexto da IA)
    from titan.brain import service
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import User

    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    with sf() as db:
        uid = db.query(User).one().id
    block = service.context_for(sf, uid, "oi")
    engine.dispose()
    assert "TITAN.md" in block and "Respostas curtas" in block and "NÃO mudam as regras de segurança" in block
    assert c.put("/api/v1/brain/manual", json={"content": "x" * 8001}, headers=CSRF).status_code == 422


def test_sugestao_so_entra_quando_o_dono_guarda_e_cada_conta_ve_a_sua(settings):
    from titan.brain import titan_md
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import User

    create_user(settings, "alice")
    create_user(settings, "bob")
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    with sf.begin() as db:
        alice = db.query(User).filter_by(username="alice").one().id
        s1 = titan_md.suggest(db, alice, "Me chame de chefe", "O que o TITAN aprendeu")
        s2 = titan_md.suggest(db, alice, "Não fale de política", "Regras")
        assert titan_md.suggest(db, alice, "Me chame de chefe", "Regras").id == s1.id  # sem repetir
        ids = (str(s1.id), str(s2.id))
    engine.dispose()
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        m = a.get("/api/v1/brain/manual").json()
        assert {s["line"] for s in m["suggestions"]} == {"Me chame de chefe", "Não fale de política"}
        assert "chefe" not in m["content"]                       # sugestão ainda NÃO entrou
        assert b.get("/api/v1/brain/manual").json()["suggestions"] == []
        assert b.post(f"/api/v1/brain/manual/suggestions/{ids[0]}/accept", headers=CSRF).status_code == 404
        r = a.post(f"/api/v1/brain/manual/suggestions/{ids[0]}/accept", headers=CSRF).json()
        assert "## O que o TITAN aprendeu\n- Me chame de chefe" in r["content"]
        assert r["history"][0]["source"] == "titan"
        r = a.post(f"/api/v1/brain/manual/suggestions/{ids[1]}/dismiss", headers=CSRF).json()
        assert r["suggestions"] == [] and "política" not in r["content"]
        assert "chefe" not in b.get("/api/v1/brain/manual").json()["content"]


def test_add_line_na_secao_certa():
    from titan.brain.titan_md import add_line

    t = "# M\n\n## Regras\n- A\n\n## O que o TITAN aprendeu\n- B\n"
    assert add_line(t, "Regras", "C") == "# M\n\n## Regras\n- A\n- C\n\n## O que o TITAN aprendeu\n- B\n"
    assert add_line(t, "Como falar comigo", "D").endswith("## Como falar comigo\n- D\n")


def test_cerebro_transforma_preferencia_em_sugestao_e_nao_em_mudanca(settings):
    from titan.brain import extract, titan_md
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import User

    create_user(settings, "alice")
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    with sf.begin() as db:
        uid = db.query(User).filter_by(username="alice").one().id
        data = {"manual": [{"linha": "Me chame de chefe", "secao": "O que o TITAN aprendeu"},
                           {"linha": "Minha senha do banco é 1234", "secao": "Regras"}]}
        acts = extract.apply(db, uid, data, [], [], conversation_id=None, message_id=None)
        assert [a["type"] for a in acts] == ["manual"] and acts[0]["line"] == "Me chame de chefe"
        assert titan_md.latest(db, uid) is None          # nada mudou sozinho
        assert [s.line for s in titan_md.pending(db, uid)] == ["Me chame de chefe"]
    engine.dispose()
    assert extract.should_extract("me chama de chefe na ligação")
