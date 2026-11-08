from tests.conftest import build_client


def _dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>TITAN-UI</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "segredo.txt").write_text("NAO-SERVIR")
    return dist


def test_spa_served_with_fallback(make_settings, tmp_path):
    s = make_settings(web_dist_dir=_dist(tmp_path))
    with build_client(s) as c:
        assert "TITAN-UI" in c.get("/").text
        assert "TITAN-UI" in c.get("/qualquer/rota").text
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/v1/inexistente").status_code == 404


def test_spa_does_not_escape_dist(make_settings, tmp_path):
    s = make_settings(web_dist_dir=_dist(tmp_path))
    with build_client(s) as c:
        for path in ["/../segredo.txt", "/%2e%2e/segredo.txt", "/assets/../../segredo.txt"]:
            assert "NAO-SERVIR" not in c.get(path).text
