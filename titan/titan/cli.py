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
    aliases = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
               "haiku": "claude-haiku-5-5"}
    model = _ask("Modelo: opus (mais capaz), sonnet (metade do preço) ou haiku (o mais barato)",
                 args.model or current.get("TITAN_MODEL_NAME") or "opus").strip().lower()
    model = aliases.get(model, model)
    if model not in ANTHROPIC_PRICES_USD_PER_MTOK:
        print(f"Modelo '{model}' não reconhecido. Use opus, sonnet, haiku ou um nome completo "
              f"da lista: {', '.join(sorted(ANTHROPIC_PRICES_USD_PER_MTOK))}. Nada foi alterado.",
              file=sys.stderr)
        return 1
    print(f"Modelo escolhido: {model}")
    budget = _ask_float("Orçamento máximo por DIA em reais (R$)", args.budget_brl, 0, 1000)
    rate = _ask_float("Cotação do dólar em reais (ex.: 5.80)", args.usd_brl, 0, 100)
    if rate > 15:
        print(f"Aviso: R$ {rate:.2f} por dólar é bem acima da cotação real (~R$ 5 a 6). "
              "Isso só torna o orçamento mais conservador (o TITAN bloqueia antes), "
              "mas o 'gasto hoje' no painel aparecerá maior que o real.")
    key = getpass.getpass("Cole a chave da API da Anthropic (não aparece na tela): ").strip()
    if not key:
        print("Nenhuma chave informada. Nada foi alterado.", file=sys.stderr)
        return 1
    if not key.startswith("sk-ant-"):
        print("Aviso: a chave não começa com 'sk-ant-'. Confira se é uma chave da Anthropic.")

    print(f"\nResumo: modelo {model}, orçamento R$ {budget:.2f}/dia, cotação R$ {rate:.2f}/US$.")
    print("As conversas passarão a ser enviadas à Anthropic.")
    if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
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


ONLINE_VOICE_WARNING = """
Voz natural on-line do TITAN (Microsoft, gratuita)
  * O TEXTO de cada resposta falada é enviado à Microsoft para virar áudio.
    O áudio da SUA fala continua local (Vosk) e não sai do notebook.
  * Serviço gratuito sem garantia: pode mudar ou parar sem aviso. Se falhar,
    a resposta continua aparecendo por escrito.
  * Para desligar depois: .venv/bin/titan disable-online-voice
"""

ONLINE_VOICES = {"antonio": "pt-BR-AntonioNeural", "francisca": "pt-BR-FranciscaNeural",
                 "thalita": "pt-BR-ThalitaMultilingualNeural"}


def cmd_enable_online_voice(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env
    from titan.voice.engines import probe_import

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    ok, why = probe_import("edge_tts")
    if not ok:
        print("Biblioteca 'edge-tts' indisponível. Rode: sh scripts/enable_online_voice.sh"
              + ("" if why == "not_installed" else f"\nMotivo: {why}"), file=sys.stderr)
        return 1
    print(ONLINE_VOICE_WARNING)
    choice = _ask("Voz: antonio (masculina), francisca ou thalita (femininas)",
                  args.voice or "antonio").strip().lower()
    choice = choice.replace("ô", "o")
    if choice not in ONLINE_VOICES:
        print(f"Voz '{choice}' não reconhecida. Use antonio, francisca ou thalita. Nada foi alterado.",
              file=sys.stderr)
        return 1
    if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
        print("Não confirmado. Nada foi alterado.")
        return 1
    backup = update_env(env_path, {
        "TITAN_VOICE_TTS": "edge",
        "TITAN_VOICE_EDGE_VOICE": ONLINE_VOICES[choice],
        "TITAN_ALLOW_EXTERNAL_VOICE": "true",
        "TITAN_LOCAL_ONLY": "false",
    })
    print(f"\nVoz on-line ligada ({choice}). .env atualizado; cópia anterior: {backup}")
    print("Reinicie o servidor para aplicar:  .venv/bin/titan serve")
    return 0


def cmd_disable_online_voice(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    update_env(env_path, {"TITAN_VOICE_TTS": "piper", "TITAN_ALLOW_EXTERNAL_VOICE": "false"})
    print("Voz on-line desligada. Reinicie o servidor para aplicar.")
    return 0


WEB_WARNING = """
Pesquisa na internet do TITAN (gratuita)
  * Quando você pedir ("pesquisa na internet ..." ou o botão Internet no chat),
    o TEXTO da pesquisa sai do notebook para a fonte de busca (Wikipédia ou o seu
    SearXNG local) e o TITAN baixa as páginas encontradas. Nada é pesquisado sem
    o seu pedido. Senhas, cookies e chaves nunca são enviados aos sites.
  * O conteúdo das páginas vai para a IA junto com a sua pergunta (com a Anthropic
    ligada, isso usa mais tokens do seu orçamento diário, que continua valendo).
  * Páginas da internet podem conter erros ou tentativas de enganar a IA: o TITAN
    as trata como conteúdo não confiável e mostra as fontes para você conferir.
  * Para desligar depois: .venv/bin/titan disable-web
"""


def cmd_enable_web(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    print(WEB_WARNING)
    searx = (args.searxng or "").strip()
    print("Fonte de busca: " + (f"SearXNG local em {searx}" if searx else
                                "Wikipédia em português (para busca geral, instale o SearXNG: "
                                "docs/pesquisa-internet.md)"))
    if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
        print("Não confirmado. Nada foi alterado.")
        return 1
    updates = {"TITAN_WEB_ENABLED": "true", "TITAN_LOCAL_ONLY": "false"}
    if args.searxng is not None:
        updates["TITAN_WEB_SEARXNG_URL"] = searx
    backup = update_env(env_path, updates)
    print(f"\nPesquisa na internet ligada. .env atualizado; cópia anterior: {backup}")
    print("Teste no terminal:  .venv/bin/titan pesquisar \"Curitiba\"")
    print("Reinicie o servidor para aplicar:  .venv/bin/titan serve")
    return 0


def cmd_disable_web(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    update_env(env_path, {"TITAN_WEB_ENABLED": "false"})
    print("Pesquisa na internet desligada. Reinicie o servidor para aplicar.")
    return 0


def cmd_web_search(args: argparse.Namespace) -> int:
    from titan.tools.web.research import RateLimited, WebDisabled, WebResearcher

    try:
        res = WebResearcher(_settings()).research(" ".join(args.texto))
    except (WebDisabled, RateLimited) as exc:
        print(f"{exc}\nPara ligar: .venv/bin/titan enable-web", file=sys.stderr)
        return 1
    print(f"Pesquisa: {res.query}  (fonte: {res.provider}, {res.elapsed_ms} ms)")
    for n in res.notes:
        print(f"  aviso: {n}")
    if not res.sources:
        print("Nenhuma fonte encontrada.")
        return 1
    for src in res.sources:
        preview = " ".join(src.text.split())[:240]
        print(f"\n[{src.n}] {src.title}\n    {src.url}\n    {preview}…")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from titan.sim.runner import Runner

    if args.repetir:
        import tempfile
        from pathlib import Path

        from titan.sim.runner import NAMES

        kind, _, seed = args.repetir.partition(":")
        if kind not in NAMES or not seed.isdigit():
            print(f"Use --repetir TIPO:SEMENTE (tipos: {', '.join(NAMES)}).", file=sys.stderr)
            return 1
        runner = Runner(minutes=args.minutos, quick=args.rapido)
        with tempfile.TemporaryDirectory(prefix="titan-repetir-") as tmp:
            runner.tmp = Path(tmp)
            res = runner.run_one(kind, int(seed), Path(tmp))
            if runner.server is not None:
                runner.server.stop()
        print(runner._entry(0, res))
        return 0 if res.ok else 2
    kinds = [k.strip() for k in args.tipos.split(",")] if args.tipos else None
    return Runner(minutes=args.minutos, pause=args.pausa, max_rounds=args.max_rodadas, kinds=kinds,
                  quick=args.rapido).run()


def cmd_stop_simulation(_: argparse.Namespace) -> int:
    from titan.sim.runner import request_stop

    print(request_stop())
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
        "TITAN_VOICE_TTS": "piper",
        "TITAN_ALLOW_EXTERNAL_VOICE": "false",
        "TITAN_WEB_ENABLED": "false",
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


def cmd_diagnose_network(args: argparse.Namespace) -> int:
    """Mede DNS e conexão TCP com a Anthropic (IPv4 e IPv6). Não envia dados nem a chave."""
    import socket
    import time

    host = args.host
    print(f"Diagnóstico de rede para {host}:443 (nenhum dado é enviado)\n")
    t0 = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        print(f"DNS: FALHOU ({exc}). Verifique a internet.")
        return 1
    print(f"DNS: {(time.monotonic() - t0):.2f}s")
    results = {}
    seen = set()
    for family, _type, _proto, _canon, addr in infos:
        if addr[0] in seen:
            continue
        seen.add(addr[0])
        label = "IPv4" if family == socket.AF_INET else "IPv6"
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(5)
        t = time.monotonic()
        try:
            sock.connect(addr[:2] if family == socket.AF_INET else addr)
            ms = (time.monotonic() - t) * 1000
            print(f"{label} {addr[0]}: conectou em {ms:.0f} ms")
            results.setdefault(label, True)
        except OSError as exc:
            print(f"{label} {addr[0]}: FALHOU em {(time.monotonic() - t):.1f}s ({exc.__class__.__name__})")
            results.setdefault(label, False)
        finally:
            sock.close()
    print()
    if results.get("IPv6") is False and results.get("IPv4"):
        print("Conclusão: IPv6 com problema e IPv4 OK. Mantenha TITAN_NETWORK_FORCE_IPV4=true (padrão).")
    elif results.get("IPv4"):
        print("Conclusão: conexão OK. Se o chat ainda demora, o tempo está na geração da resposta.")
    else:
        print("Conclusão: não foi possível conectar por IPv4. Verifique a internet/firewall.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.core.backup import BackupError, create_backup, prune, verify_restore

    s = _settings()
    dest = Path(args.dest) if args.dest else s.backup_dir
    try:
        info = create_backup(s, dest)
        print(f"Backup criado: {info.path} ({info.manifest['size_bytes']} bytes, "
              f"integridade: {info.manifest['integrity']})")
        report = verify_restore(info.path)
        print(f"Teste de restauração em pasta temporária: {'OK' if report['ok'] else 'FALHOU'} "
              f"(auditoria íntegra: {report['audit_chain_ok']}, linhas: {report['row_counts']})")
        if not report["ok"]:
            return 2
        removed = prune(dest, args.keep or s.backup_keep)
        if removed:
            print(f"Backups antigos removidos: {len(removed)} (retenção {args.keep or s.backup_keep}).")
    except BackupError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print("Lembrete: o .env (segredos) não entra no backup; guarde-o separadamente.")
    return 0


def cmd_backup_list(args: argparse.Namespace) -> int:
    from titan.core.backup import list_backups

    s = _settings()
    items = list_backups(s.backup_dir)
    if not items:
        print(f"Nenhum backup em {s.backup_dir}")
    for b in items:
        m = b.manifest
        print(f"{b.path.name}  {m.get('created_at', '?')}  {m.get('size_bytes', '?')} bytes  "
              f"integridade={m.get('integrity')}")
    return 0


def cmd_backup_verify(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.core.backup import BackupError, list_backups, verify_restore

    s = _settings()
    path = Path(args.file) if args.file else None
    if path is None:
        valid = [b for b in list_backups(s.backup_dir) if b.valid]
        if not valid:
            print("Nenhum backup válido encontrado.", file=sys.stderr)
            return 1
        path = valid[-1].path
    try:
        report = verify_restore(path)
    except BackupError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(f"{path.name}: {'OK' if report['ok'] else 'FALHOU'} — {report}")
    return 0 if report["ok"] else 2


def cmd_restore(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.core.backup import BackupError, restore

    if not args.yes:
        print("A restauração SUBSTITUI o banco atual. Pare o servidor (Ctrl+C) e rode de novo "
              "com --yes. Uma cópia do banco atual será guardada antes.", file=sys.stderr)
        return 1
    try:
        safety = restore(_settings(), Path(args.file))
    except BackupError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(f"Banco restaurado. Cópia do banco anterior: {safety}")
    return 0


def uvicorn_options(s) -> dict:
    opts = dict(
        host=s.host,
        port=s.port,
        workers=1,
        # Não confiar em X-Forwarded-For: impediria falsificar a rede de origem.
        proxy_headers=False,
        server_header=False,
        log_level=s.log_level.lower(),
    )
    if s.tls_enabled:
        opts.update(ssl_certfile=str(s.tls_cert_file), ssl_keyfile=str(s.tls_key_file))
    return opts


def cmd_sandbox_probe(args: argparse.Namespace) -> int:
    import json

    from titan.sandbox.probe import probe

    print(json.dumps(probe(), indent=2, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from titan.db.migrate import upgrade_head

    s = _settings()
    if not args.no_migrate:
        upgrade_head(s.database_url)
    from titan_api.app import create_app

    if s.lan_enabled:
        print(f"ATENÇÃO: acessível na rede local ({s.host}:{s.port}) para {s.allowed_networks}. "
              + ("HTTPS ativo." if s.tls_enabled else "SEM HTTPS: o tráfego na Wi-Fi não é cifrado."))
    uvicorn.run(create_app(s), **uvicorn_options(s))
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
    p = sub.add_parser("enable-online-voice", help="liga a voz natural on-line (o texto sai do notebook)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--voice")
    p.set_defaults(fn=cmd_enable_online_voice)
    p = sub.add_parser("disable-online-voice", help="volta para a voz local (Piper)")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_disable_online_voice)
    p = sub.add_parser("enable-web", help="liga a pesquisa na internet (a pergunta sai do notebook)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--searxng", help="endereço do SearXNG local, ex.: http://127.0.0.1:8888")
    p.set_defaults(fn=cmd_enable_web)
    p = sub.add_parser("disable-web", help="desliga a pesquisa na internet")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_disable_web)
    p = sub.add_parser("pesquisar", help="testa a pesquisa na internet no terminal")
    p.add_argument("texto", nargs="+")
    p.set_defaults(fn=cmd_web_search)
    p = sub.add_parser("simular", help="simulação contínua numa cópia isolada (pare com Ctrl+C ou parar-simulacao)")
    p.add_argument("--minutos", type=float, default=3, help="duração da rodada de uso prolongado")
    p.add_argument("--pausa", type=float, default=10, help="segundos entre rodadas")
    p.add_argument("--max-rodadas", type=int)
    p.add_argument("--tipos", help="ex.: orcamento,uso,seguranca,falhas,voz")
    p.add_argument("--rapido", action="store_true", help="rodadas curtas (teste)")
    p.add_argument("--repetir", help="TIPO:SEMENTE — repete uma rodada do diário")
    p.set_defaults(fn=cmd_simulate)
    sub.add_parser("parar-simulacao", help="para a simulação depois da rodada atual").set_defaults(fn=cmd_stop_simulation)
    p = sub.add_parser("disable-external", help="desliga provedores externos (volta ao modo local)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--keep-key", action="store_true", help="mantém a chave no .env")
    p.set_defaults(fn=cmd_disable_external)
    p = sub.add_parser("backup", help="cria backup do banco e testa a restauração")
    p.add_argument("--dest")
    p.add_argument("--keep", type=int)
    p.set_defaults(fn=cmd_backup)
    sub.add_parser("backup-list", help="lista os backups").set_defaults(fn=cmd_backup_list)
    p = sub.add_parser("backup-verify", help="testa a restauração de um backup (sem tocar no banco)")
    p.add_argument("file", nargs="?")
    p.set_defaults(fn=cmd_backup_verify)
    p = sub.add_parser("restore", help="restaura um backup (servidor parado)")
    p.add_argument("file")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_restore)
    sub.add_parser("sandbox-probe", help="verifica mecanismos de isolamento (somente leitura)").set_defaults(fn=cmd_sandbox_probe)
    p = sub.add_parser("diagnose-network", help="mede a conexão com a Anthropic (sem enviar dados)")
    p.add_argument("--host", default="api.anthropic.com")
    p.set_defaults(fn=cmd_diagnose_network)
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
