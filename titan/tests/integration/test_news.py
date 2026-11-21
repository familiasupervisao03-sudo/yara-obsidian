"""Notícias do TITAN: ler feeds, juntar o mesmo fato, avisar, seguir assuntos (com preço e data reais),
nunca inventar, e cada conta vendo só o que é dela. Tudo sem internet (feeds de exemplo)."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import CSRF, build_client, create_user, login

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate><description>{s}</description></item>"
        for t, u, d, s in items)
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{body}</channel></rss>'


D = "Mon, 16 Nov 2026 14:00:00 +0000"
FEEDS = {
    "https://tecnoblog.net/feed/": rss(("Google lança Gemini 3 com novos recursos de IA", "https://tb.example/gemini",
                                        D, "O Gemini 3 traz <b>raciocínio</b> melhor e um modo multimodal.")),
    "https://canaltech.com.br/rss/": rss(("Gemini 3: Google lança nova versão da IA com recursos inéditos",
                                          "https://ct.example/gemini", D, "Nova IA do Google chega hoje."),
                                         ("ESP32 cai de preço: placa sai por R$ 35,90 em lojas; o Arduino custa R$ 80",
                                          "https://ct.example/esp32", D, "Módulo ESP32 por R$ 35,90.")),
    "https://ge.globo.com/rss/ge/": rss(("Fortaleza vence o Ceará no clássico", "https://ge.example/jogo", D, "Placar 2 a 1.")),
}


def fake_fetch(url):
    if url in FEEDS:
        return FEEDS[url]
    if url.startswith("https://news.google.com/"):
        return rss(("ESP32 em promoção por R$ 29,90 - Tecnoblog", "https://news.example/esp32-antigo",
                    "Tue, 03 Nov 2026 10:00:00 +0000", ""))
    raise OSError("fora do ar")


def test_parse_rss_atom_e_recusa_truque_xml():
    from titan.news import feeds

    es = feeds.parse(FEEDS["https://tecnoblog.net/feed/"], "Tecnoblog", NOW)
    assert es[0].title.startswith("Google lança") and es[0].summary == "O Gemini 3 traz raciocínio melhor e um modo multimodal."
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Oi</title><link rel="alternate" '
            'href="https://x.example/a"/><updated>2026-11-16T10:00:00Z</updated><summary>txt</summary></entry></feed>')
    assert feeds.parse(atom, "X", NOW)[0].url == "https://x.example/a"
    with pytest.raises(feeds.FeedError):
        feeds.parse('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss/>', "X", NOW)
    bad = rss(("Link perigoso", "javascript:alert(1)", D, ""))
    assert feeds.parse(bad, "X", NOW) == []


def test_preco_so_da_mesma_frase_e_nada_inventado():
    from titan.news.group import prices_in

    assert prices_in("ESP32 por R$ 35,90; o Arduino custa R$ 80.", "esp32") == [(35.9, "ESP32 por R$ 35,90;")]
    assert prices_in("O Arduino custa R$ 80.", "esp32") == []
    assert prices_in("Notebook sai por R$ 3.499,00 na promoção", "notebook")[0][0] == 3499.0


def _setup(settings):
    from titan.db.engine import make_engine, make_session_factory

    create_user(settings, "alice")
    create_user(settings, "bob")
    engine = make_engine(settings.database_url)
    return engine, make_session_factory(engine)


def test_coleta_junta_o_mesmo_fato_avisa_e_cada_conta_ve_o_seu(settings, monkeypatch):
    import titan_api.routers.news as news_router
    from titan.db.models import NewsStory, TitanNote, User
    from titan.news import service

    # a lista mostra as últimas 72 h: o "agora" do servidor fica no dia dos feeds de exemplo
    monkeypatch.setattr(news_router, "utcnow", lambda: NOW + timedelta(hours=1))

    engine, sf = _setup(settings)
    report = service.tick(settings, sf, fake_fetch, None, now=NOW)
    assert report["novas"] == 4
    with sf() as db:
        gem = [s for s in db.query(NewsStory).all() if "Gemini" in s.title]
        assert len(gem) == 1, "duas notícias do mesmo fato viram uma só"
        notes = db.query(TitanNote).filter_by(kind="noticia").all()
        alice = db.query(User).filter_by(username="alice").one()
        assert notes and all(n.body.endswith("Toque para ver em Notícias.") for n in notes)
        assert {n.user_id for n in notes} == {u.id for u in db.query(User).all()}  # cada conta recebe o seu
    # rodar de novo não duplica nada
    assert service.tick(settings, sf, fake_fetch, None, now=NOW + timedelta(minutes=40))["novas"] == 0
    engine.dispose()
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        lst = a.get("/api/v1/news").json()
        g = next(s for s in lst["stories"] if "Gemini" in s["title"])
        assert g["n_sources"] == 2 and {x["name"] for x in g["sources"]} == {"Tecnoblog", "Canaltech"}
        assert all(x["url"].startswith("https://") for x in g["sources"])
        assert g["analysis"] is None, "sem IA: só título e link, nenhum resumo inventado"
        r = a.post(f"/api/v1/news/stories/{g['id']}/state", json={"vote": 1, "saved": True}, headers=CSRF).json()
        assert r["vote"] == 1 and r["saved"] is True
        assert [s["id"] for s in a.get("/api/v1/news?cat=salvas").json()["stories"]] == [g["id"]]
        assert b.get("/api/v1/news?cat=salvas").json()["stories"] == []    # o 👍/salvar da alice não aparece pro bob
        assert [s["title"] for s in a.get("/api/v1/news?cat=esportes").json()["stories"]] == \
            ["Fortaleza vence o Ceará no clássico"]
        assert any("Gemini" in s["title"] for s in a.get("/api/v1/news?cat=ia").json()["stories"])


def test_analise_usa_so_o_texto_e_descarta_termo_inventado(settings):
    from titan.db.models import NewsStory, NewsTerm, User
    from titan.models.providers import MockProvider
    from titan.news import service

    engine, sf = _setup(settings)
    service.tick(settings, sf, fake_fetch, None, now=NOW)
    MockProvider.json_reply = {
        "resumo": "Google lançou o Gemini 3.", "por_que_importa": "IA nova pode baratear o TITAN.",
        "afeta_titan": "Testar como reserva.", "oportunidade": "", "discordam": False, "discordancia": "",
        "termos": [{"termo": "multimodal", "explicacao": "Entende texto e imagem."},
                   {"termo": "blockchain", "explicacao": "inventado: não está no texto"}]}
    try:
        with sf.begin() as db:
            alice = db.query(User).filter_by(username="alice").one().id
            st = next(s for s in db.query(NewsStory).all() if "Gemini" in s.title)
            out = service.analyze(MockProvider(), db, alice, st)
        assert out["resumo"] == "Google lançou o Gemini 3." and out["discordam"] is False
        assert [t["termo"] for t in out["termos"]] == ["multimodal"]
        with sf() as db:
            assert [t.term for t in db.query(NewsTerm).all()] == ["multimodal"]
    finally:
        MockProvider.json_reply = None
        engine.dispose()


def test_seguir_assunto_passado_e_futuro_com_preco_data_e_link(settings):
    from titan.db.models import NewsFollow, User
    from titan.news import service

    engine, sf = _setup(settings)
    service.tick(settings, sf, fake_fetch, None, now=NOW)
    with sf.begin() as db:
        alice = db.query(User).filter_by(username="alice").one().id
        p = service.parse_follow("Titan analisa os preços da ESP32 nas próximas 3 semanas e também nas semanas passadas", NOW)
        assert (p["topic"], p["prices"], p["past_weeks"], p["future_weeks"]) == ("ESP32", True, 2, 3)
        f = service.create_follow(db, alice, p["topic"], p["prices"], p["past_weeks"], p["future_weeks"], now=NOW)
        assert service.check_follow(db, f, fake_fetch, NOW) == 2
        s = service.follow_summary(db, f)
        prices = [(h.published_at.strftime("%d/%m/%y"), h.price, h.quote) for h in s["hits"]]
        assert prices[0][:2] == ("03/11/26", 29.9) and prices[1][:2] == ("16/11/26", 35.9)
        assert all(q for _, _, q in prices), "cada preço vem com o trecho exato do texto"
        assert s["trend"] == "De R$ 29,90 (03/11/26) para R$ 35,90 (16/11/26): subiu R$ 6,00."
        assert service.parse_follow("você acompanha futebol?", NOW) is None
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        fl = a.get("/api/v1/news/follows").json()
        assert fl[0]["topic"] == "ESP32" and len(fl[0]["hits"]) == 2
        assert b.get("/api/v1/news/follows").json() == []
        assert b.delete(f"/api/v1/news/follows/{fl[0]['id']}", headers=CSRF).status_code == 404
        r = a.post("/api/v1/news/follows/from-text", json={"text": "segue as notícias sobre Realme nas últimas 2 semanas"},
                   headers=CSRF)
        assert r.status_code == 201 and r.json()["topic"] == "Realme" and r.json()["prices"] is False
    engine.dispose()


def test_sem_preco_achado_ele_diz_que_nao_achou(settings):
    from titan.db.models import User
    from titan.news import service

    engine, sf = _setup(settings)
    with sf.begin() as db:
        alice = db.query(User).filter_by(username="alice").one().id
        f = service.create_follow(db, alice, "Raspberry Pi", True, 2, 2, now=NOW)
        service.check_follow(db, f, lambda u: rss(), NOW)
        assert service.follow_summary(db, f)["trend"] == "Ainda não achei nenhum preço citado com data. Não vou inventar um."
    engine.dispose()


def test_jornal_as_19h_e_contexto_da_conversa_com_links(settings):
    from titan.db.models import TitanNote, User
    from titan.news import service

    engine, sf = _setup(settings)
    service.tick(settings, sf, fake_fetch, None, now=NOW)
    with sf() as db:
        alice = db.query(User).filter_by(username="alice").one().id
        ctx = service.context_block(db, alice, "Titã, o que saiu de notícia hoje?", now=NOW)
        assert "https://tb.example/gemini" in ctx and "NUNCA invente" in ctx
        assert service.context_block(db, alice, "liga a luz", now=NOW) == ""
        body = service.jornal(db, alice, NOW)
        assert body.startswith("Boa noite, senhor.") and "• " in body
    engine.dispose()


def test_fontes_e_assunto_pela_conversa(auth_client, settings):
    c = auth_client
    src = c.get("/api/v1/news/sources").json()
    assert any(s["name"] == "Tecnoblog" and s["enabled"] for s in src)
    r = c.put("/api/v1/news/sources", json={"url": "https://tecnoblog.net/feed/", "enabled": False}, headers=CSRF).json()
    assert next(s for s in r if s["name"] == "Tecnoblog")["enabled"] is False
    assert c.put("/api/v1/news/sources", json={"url": "http://inseguro.example/rss"}, headers=CSRF).status_code == 422
    cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    from tests.integration.test_chat_stream import parse

    ev = dict(parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                           json={"content": "Titan analisa os preços da esp32 nas próximas 3 semanas"},
                           headers=CSRF).text))
    assert ev["done"]["message"]["content"].startswith("Pois não, senhor. Vou acompanhar os preços e as notícias sobre esp32")
    assert ev["actions"]["actions"][0]["type"] == "assunto"
    assert c.get("/api/v1/news/follows").json()[0]["topic"] == "esp32"
