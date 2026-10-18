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


ANTHROPIC_WARNING = """
ATENÇÃO — você está ligando um provedor EXTERNO e PAGO (Anthropic).

  * Privacidade: a cada mensagem, o histórico recente da conversa (até 40
    mensagens) é enviado aos servidores da Anthropic. Banco, logs, senhas e
    arquivos continuam no notebook; as conversas, não.
  * Custo: a Anthropic cobra por uso, dos créditos da sua conta. O TITAN
    bloqueia qualquer chamada que possa passar do orçamento diário que você
    definir agora, reservando o custo MÁXIMO antes de enviar.
  * Para desligar a qualquer momento:  .venv/bin/titan disable-external
"""


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _ask_float(prompt: str, default: str | None, lo: float, hi: float) -> float:
    raw = _ask(prompt, default).replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(f"Valor inválido: {raw!r}")
    if not lo < value <= hi:
        raise SystemExit(f"Valor fora do intervalo ({lo} < valor <= {hi}).")
    return value


def cmd_enable_anthropic(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import read_env, update_env
    from titan.policies.budget import ANTHROPIC_PRICES_USD_PER_MTOK

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("Biblioteca 'anthropic' não instalada. Rode antes:\n"
              "  .venv/bin/pip install --only-binary=:all: -e '.[anthropic]'", file=sys.stderr)
        return 1

    print(ANTHROPIC_WARNING)
    current = read_env(env_path)
    model = _ask("Modelo (ex.: claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5)",
                 args.model or current.get("TITAN_MODEL_NAME") or "claude-opus-5-5")
    if model not in ANTHROPIC_PRICES_USD_PER_MTOK:
        print(f"Aviso: '{model}' não está na tabela de preços; será cobrado no orçamento "
              "pelo preço mais alto (conservador).")
    budget = _ask_float("Orçamento máximo por DIA em reais (R$)", args.budget_brl, 0, 1000)
    rate = _ask_float("Cotação do dólar em reais (ex.: 5.60) — use um valor um pouco acima do atual",
                      args.usd_brl, 0, 100)
    key = getpass.getpass("Cole a chave da API da Anthropic (não aparece na tela): ").strip()
    if not key:
        print("Nenhuma chave informada. Nada foi alterado.", file=sys.stderr)
        return 1
    if not key.startswith("sk-ant-"):
        print("Aviso: a chave não começa com 'sk-ant-'. Confira se é uma chave da Anthropic.")

    print(f"\nResumo: modelo {model}, orçamento R$ {budget:.2f}/dia, cotação R$ {rate:.2f}/US$.")
    print("As conversas passarão a ser enviadas à Anthropic.")
    if _ask("Digite AUTORIZO para confirmar") != "AUTORIZO":
        print("Não confirmado. Nada foi alterado.")
        return 1

    backup = update_env(env_path, {
        "TITAN_MODEL_PROVIDER": "anthropic",
        "TITAN_MODEL_NAME": model,
        "TITAN_LOCAL_ONLY": "false",
        "TITAN_ALLOW_EXTERNAL_MODELS": "true",
        "TITAN_ALLOW_PAID_APIS": "true",
        "TITAN_DAILY_PAID_BUDGET_BRL": f"{budget:.2f}",
        "TITAN_USD_BRL_RATE": f"{rate:.4f}",
        "ANTHROPIC_API_KEY": key,
    })
    print(f"\n.env atualizado (permissão 600). Cópia anterior: {backup}")
    print("Nenhuma chamada de teste foi feita (para não gerar custo).")
    print("Reinicie o servidor para aplicar:  .venv/bin/titan serve")
    return 0


def cmd_disable_external(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    updates: dict[str, str | None] = {
        "TITAN_MODEL_PROVIDER": "none",
        "TITAN_LOCAL_ONLY": "true",
        "TITAN_ALLOW_EXTERNAL_MODELS": "false",
        "TITAN_ALLOW_PAID_APIS": "false",
        "TITAN_DAILY_PAID_BUDGET_BRL": "0",
    }
    if not args.keep_key:
        updates["ANTHROPIC_API_KEY"] = None  # remove a linha
    backup = update_env(env_path, updates)
    print("Provedores externos desligados; modo 100% local restaurado.")
    if not args.keep_key:
        print("A chave da Anthropic foi removida do .env.")
        print(f"ATENÇÃO: a cópia de segurança {backup} ainda contém a chave; apague-a se quiser:")
        print(f"  rm {backup}")
    print("Reinicie o servidor para aplicar.")
    return 0


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
    p = sub.add_parser("enable-anthropic", help="liga a API da Anthropic (externa e paga) com orçamento")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--model")
    p.add_argument("--budget-brl")
    p.add_argument("--usd-brl")
    p.set_defaults(fn=cmd_enable_anthropic)
    p = sub.add_parser("disable-external", help="desliga provedores externos (volta ao modo local)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--keep-key", action="store_true", help="mantém a chave no .env")
    p.set_defaults(fn=cmd_disable_external)
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
