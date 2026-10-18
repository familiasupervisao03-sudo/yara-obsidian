"""Linha de comando do TITAN: python -m titan.cli <comando>."""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys


def _settings():
    from titan.config.settings import get_settings

    return get_settings()


def cmd_gen_secret(_: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(48))
    return 0


def cmd_check_config(_: argparse.Namespace) -> int:
    s = _settings()
    for k, v in s.public_view().items():
        print(f"{k} = {v}")
    print("Configuração válida.")
    return 0


def cmd_migrate(_: argparse.Namespace) -> int:
    from titan.db.migrate import upgrade_head

    upgrade_head(_settings().database_url)
    print("Migrações aplicadas.")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from titan.audit import log as audit
    from titan.auth.service import AuthError, AuthService
    from titan.db.engine import make_engine, make_session_factory

    s = _settings()
    password = getpass.getpass("Senha: ")
    if password != getpass.getpass("Confirme a senha: "):
        print("As senhas não conferem.", file=sys.stderr)
        return 1
    engine = make_engine(s.database_url)
    try:
        with make_session_factory(engine).begin() as db:
            user = AuthService.create_user(db, args.username, password, role=args.role)
            audit.record(db, "user.created", entity_type="user", entity_id=str(user.id),
                         data={"username": user.username, "role": user.role, "via": "cli"})
    except AuthError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Usuário '{args.username}' criado.")
    return 0


def cmd_audit_verify(_: argparse.Namespace) -> int:
    from titan.audit.log import verify_chain
    from titan.db.engine import make_engine, make_session_factory

    engine = make_engine(_settings().database_url)
    with make_session_factory(engine)() as db:
        ok, bad = verify_chain(db)
    engine.dispose()
    print("Cadeia de auditoria íntegra." if ok else f"Cadeia ADULTERADA a partir do evento {bad}.")
    return 0 if ok else 2


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from titan.db.migrate import upgrade_head

    s = _settings()
    if not args.no_migrate:
        upgrade_head(s.database_url)
    from titan_api.app import create_app

    uvicorn.run(
        create_app(s),
        host=s.host,
        port=s.port,
        workers=1,
        # Não confiar em X-Forwarded-For: impediria falsificar a rede de origem.
        proxy_headers=False,
        server_header=False,
        log_level=s.log_level.lower(),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="titan", description="TITAN — servidor local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-secret", help="gera um TITAN_AUTH_SECRET aleatório").set_defaults(fn=cmd_gen_secret)
    sub.add_parser("check-config", help="valida a configuração").set_defaults(fn=cmd_check_config)
    sub.add_parser("migrate", help="aplica as migrações do banco").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("create-user", help="cria um usuário local")
    p.add_argument("username")
    p.add_argument("--role", choices=["owner", "member"], default="owner")
    p.set_defaults(fn=cmd_create_user)
    sub.add_parser("audit-verify", help="verifica a integridade da auditoria").set_defaults(fn=cmd_audit_verify)
    p = sub.add_parser("serve", help="inicia o servidor local")
    p.add_argument("--no-migrate", action="store_true")
    p.set_defaults(fn=cmd_serve)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            print(f"Configuração inválida:\n{exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
