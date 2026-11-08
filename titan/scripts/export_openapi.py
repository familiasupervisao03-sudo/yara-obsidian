"""Exporta o esquema OpenAPI para packages/api-contracts/openapi.json."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
OUT = ROOT / "packages" / "api-contracts" / "openapi.json"


def build_schema() -> dict:
    from titan.config.settings import Settings
    from titan_api.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(
            _env_file=None, env="test", database_url=f"sqlite:///{tmp}/x.db",
            data_dir=Path(tmp), workspace_root=Path(tmp) / "ws", serve_web=False,
        )
        app = create_app(s)
        schema = app.openapi()
        app.state.ctx.engine.dispose()
    return schema


def render() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"Escrito {OUT.relative_to(ROOT)}")
