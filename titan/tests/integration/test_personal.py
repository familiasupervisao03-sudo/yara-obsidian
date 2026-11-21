"""Você → Personalizar: cada conta com o seu jeito; mensagens e IA seguem o tratamento escolhido."""

from tests.conftest import CSRF, build_client, create_user, login


def test_padrao_salvar_validar_e_voltar(auth_client):
    c = auth_client
    p = c.get("/api/v1/brain/personal").json()
    assert p["color"] == "azul" and p["nav"] == ["home", "chat", "news", "system"] and p["call"] == "senhor"
    assert [x["id"] for x in p["cards"]][:3] == ["orbe", "clima", "continuar"]
    p.update(color="verde", orb="reator", name="Jarvis", call="chefe", tone="amigo", font="G",
             nav=["home", "casa", "news", "system"])
    r = c.put("/api/v1/brain/personal", json=p, headers=CSRF)
    assert r.status_code == 200 and r.json()["name"] == "Jarvis"
    assert c.get("/api/v1/brain/personal").json()["color"] == "verde"
    for bad in ({"nav": ["home", "home", "news", "system"]}, {"color": "dourado"}, {"custom": "azul"},
                {"name": "<script>"}, {"call": "livre", "call_custom": ""}):
        assert c.put("/api/v1/brain/personal", json={**p, **bad}, headers=CSRF).status_code == 422, bad
    assert c.delete("/api/v1/brain/personal", headers=CSRF).json()["color"] == "azul"


def test_cada_conta_o_seu_jeito_e_mensagens_adaptadas(settings):
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import TitanNote, User

    create_user(settings, "alice")
    create_user(settings, "bob")
    engine = make_engine(settings.database_url)
    with make_session_factory(engine).begin() as db:
        for u in db.query(User).all():
            db.add(TitanNote(user_id=u.id, kind="sistema", title="TITAN · Servidor ligado",
                             body="Boa noite, senhor. Inicialização concluída.", day="2026-11-21"))
    engine.dispose()
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        p = a.get("/api/v1/brain/personal").json()
        a.put("/api/v1/brain/personal", json={**p, "name": "Jarvis", "call": "nome"}, headers=CSRF)
        na = a.get("/api/v1/brain/notes?device=web-a").json()[0]
        assert na["title"] == "Jarvis · Servidor ligado" and na["body"].startswith("Boa noite, Alice.")
        nb = b.get("/api/v1/brain/notes?device=web-b").json()[0]
        assert nb["title"] == "TITAN · Servidor ligado" and "senhor" in nb["body"], "o jeito da alice não vale para o bob"
        assert b.get("/api/v1/brain/personal").json()["name"] == "TITAN"


def test_instrucoes_para_a_ia():
    from titan.brain import personal

    assert personal.style_block(dict(personal.DEFAULTS), "luiz") == ""
    p = {**personal.DEFAULTS, "call": "livre", "call_custom": "capitão", "tone": "direto", "name": "Jarvis"}
    s = personal.style_block(p, "luiz")
    assert 'Chame o dono de "capitão"' in s and "Seu nome é Jarvis" in s and "direto ao ponto" in s
    assert personal.adapt("Pois não, senhor. Senhor, pronto.", p, "luiz") == "Pois não, capitão. Capitão, pronto."
