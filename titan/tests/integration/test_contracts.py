import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_contract_is_up_to_date():
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts" / "export_openapi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = (ROOT / "packages" / "api-contracts" / "openapi.json").read_text(encoding="utf-8")
    assert committed == mod.render(), "Execute: python scripts/export_openapi.py"


def test_contract_lists_phase1_routes():
    import json

    paths = json.loads((ROOT / "packages" / "api-contracts" / "openapi.json").read_text())["paths"]
    for p in ["/health", "/ready", "/api/v1/conversations", "/api/v1/conversations/{conversation_id}",
              "/api/v1/conversations/{conversation_id}/messages", "/api/v1/settings",
              "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/me", "/api/v1/system/status"]:
        assert p in paths, p
