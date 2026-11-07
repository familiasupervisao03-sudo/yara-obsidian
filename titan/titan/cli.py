"""Linha de comando do TITAN: python -m titan.cli <comando>."""

from __future__ import annotations

import argparse
import os
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
    from titan.envfile import read_env

    groq_on = read_env(env_path).get("TITAN_VOICE_STT") in ("groq", "xai")
    update_env(env_path, {"TITAN_VOICE_TTS": "piper",
                          "TITAN_ALLOW_EXTERNAL_VOICE": "true" if groq_on else "false"})
    print("Voz on-line desligada. Reinicie o servidor para aplicar.")
    return 0


CLOUD_STT_WARNING = """
Reconhecimento de voz on-line do TITAN ({company})
  * O ÁUDIO de cada fala sua é enviado à {company} (EUA) quando você termina de falar,
    para virar texto. Silêncio não é enviado. Nada é gravado no notebook.
  * O Vosk continua no notebook: mostra o texto enquanto você fala e assume sozinho
    se a {company} falhar, ficar sem internet ou chegar ao limite.
  * Custo: {custo}
  * Teto do TITAN: {minutos} minutos de áudio por dia (TITAN_VOICE_CLOUD_MAX_MINUTES_DAY).
  * Para desligar depois: .venv/bin/titan {off}
"""

CLOUD_STT = {
    "groq": dict(company="Groq", key="GROQ_API_KEY", prefix="gsk_", off="disable-groq-stt",
                 custo="conta grátis (sem cartão) não cobra; ao passar do limite deles o Vosk assume. "
                       "Com cartão: ~US$ 0,04 por hora de fala (mínimo de 10 s por fala)."),
    "xai": dict(company="xAI", key="XAI_API_KEY", prefix="xai-", off="disable-xai-stt",
                custo="pago pelos créditos da sua conta xAI: ~US$ 0,10 por hora de fala "
                      "(~R$ 0,01 por minuto). Sem créditos, o Vosk assume."),
}


def _enable_cloud_stt(args: argparse.Namespace, provider: str) -> int:
    from pathlib import Path

    from titan.envfile import read_env, update_env

    info = CLOUD_STT[provider]
    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    try:
        import httpx  # noqa: F401
    except ImportError:
        print("Biblioteca 'httpx' não instalada. Rode: .venv/bin/pip install -e '.[groq]'", file=sys.stderr)
        return 1
    env = read_env(env_path)
    minutes = int(_ask_float("Teto de minutos de fala por dia enviados para fora",
                             args.minutos or env.get("TITAN_VOICE_CLOUD_MAX_MINUTES_DAY") or "60", 1, 1440))
    print(CLOUD_STT_WARNING.format(minutos=minutes, **info))
    key = getpass.getpass(f"Cole a chave da API da {info['company']} (não aparece na tela): ").strip()
    if not key:
        print("Nenhuma chave informada. Nada foi alterado.", file=sys.stderr)
        return 1
    if not key.startswith(info["prefix"]):
        print(f"Aviso: a chave não começa com '{info['prefix']}'. Confira se é uma chave da {info['company']}.")
    if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
        print("Não confirmado. Nada foi alterado.")
        return 1
    backup = update_env(env_path, {
        "TITAN_VOICE_STT": provider,
        info["key"]: key,
        "TITAN_VOICE_CLOUD_MAX_MINUTES_DAY": str(minutes),
        "TITAN_ALLOW_EXTERNAL_VOICE": "true",
        "TITAN_LOCAL_ONLY": "false",
    })
    print(f"\nReconhecimento pela {info['company']} ligado. .env atualizado (permissão 600); cópia anterior: {backup}")
    print("Nenhuma chamada de teste foi feita. Reinicie o TITAN para valer:  .venv/bin/titan ligar")
    return 0


def _disable_cloud_stt(args: argparse.Namespace, provider: str) -> int:
    from pathlib import Path

    from titan.envfile import read_env, update_env

    info = CLOUD_STT[provider]
    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    env = read_env(env_path)
    updates: dict[str, str | None] = {}
    if env.get("TITAN_VOICE_STT") == provider:
        updates["TITAN_VOICE_STT"] = "vosk"
        updates["TITAN_ALLOW_EXTERNAL_VOICE"] = "true" if env.get("TITAN_VOICE_TTS") == "edge" else "false"
    if not args.keep_key:
        updates[info["key"]] = None
    backup = update_env(env_path, updates)
    print(f"Reconhecimento pela {info['company']} desligado: o áudio volta a ficar só no notebook (Vosk).")
    if not args.keep_key:
        print(f"A chave foi removida do .env. A cópia {backup} ainda a contém; apague com: rm {backup}")
    print("Reinicie o servidor para aplicar.")
    return 0


def _read_wav_16k(path) -> bytes:
    """Lê um WAV e devolve PCM 16 bits mono 16 kHz (converte com interpolação simples)."""
    import sys as _sys
    import wave
    from array import array

    with wave.open(str(path), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("o WAV precisa ser 16 bits (ex.: arecord -f S16_LE)")
    a = array("h")
    a.frombytes(raw)
    if _sys.byteorder == "big":
        a.byteswap()
    if ch > 1:
        a = array("h", (sum(a[i:i + ch]) // ch for i in range(0, len(a) - ch + 1, ch)))
    if rate != 16000:
        n = int(len(a) * 16000 / rate)
        step = rate / 16000
        a = array("h", (a[min(int(i * step), len(a) - 1)] for i in range(n)))
    if _sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def cmd_test_voice(args: argparse.Namespace) -> int:
    """Grava (ou lê) uma fala e mostra o que o Vosk e o reconhecimento on-line entenderam."""
    import shutil
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    from titan.voice import engines

    s = _settings()
    if args.arquivo:
        wav = Path(args.arquivo)
    else:
        if not shutil.which("arecord"):
            print("Programa 'arecord' não encontrado (sudo apt install alsa-utils) ou use --arquivo fala.wav",
                  file=sys.stderr)
            return 1
        wav = Path(tempfile.mkdtemp()) / "fala.wav"
        input(f"Aperte Enter e fale por {args.segundos} segundos (ex.: 'TITAN, qual é a capital da Austrália?')...")
        print("Gravando... fale agora.")
        res = subprocess.run(["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
                              "-d", str(args.segundos), str(wav)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Não consegui gravar: {res.stderr.strip()[:200]}", file=sys.stderr)
            return 1
    try:
        pcm = _read_wav_16k(wav)
    except Exception as exc:  # arquivo inválido
        print(f"Não consegui ler o áudio: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.arquivo:
            shutil.rmtree(wav.parent, ignore_errors=True)
    print(f"Áudio: {len(pcm) / 32000:.1f} s, volume médio {engines.speech_level(pcm):.0f} "
          f"(abaixo de {engines.MIN_SPEECH_LEVEL:.0f} conta como silêncio)")

    vosk = engines.VoskSTT(s)
    st = vosk.status()
    if st.available:
        rec = vosk.recognizer()
        rec.AcceptWaveform(pcm)
        import json

        print(f"\nVosk (local):   {json.loads(rec.FinalResult()).get('text', '') or '(nada)'}")
    else:
        print(f"\nVosk (local):   indisponível — {st.detail}")

    cloud = {"groq": engines.GroqSTT, "xai": engines.XaiSTT}.get(s.voice_stt)
    if cloud is None:
        print("On-line:        desligado (TITAN_VOICE_STT=vosk). Ligue com: .venv/bin/titan enable-groq-stt")
        return 0
    eng = cloud(s)
    t0 = time.monotonic()
    try:
        t = eng.transcribe(pcm)
    except engines.VoiceUnavailable as exc:
        print(f"{eng.company + ':':15} FALHOU — {exc}")
        return 1
    print(f"{eng.company + ':':15} {t.text or '(nada)'}   [{t.verdict}, {time.monotonic() - t0:.1f} s]")
    if t.verdict == "noise":
        print("  (o reconhecimento achou que era ruído/silêncio: fale mais perto do microfone)")
    return 0


TUYA_WARNING = """
TITAN Casa com a sua conta Tuya / Smart Life (nuvem oficial da Tuya)
  * Os comandos (ligar, desligar, temperatura...) vão do notebook para a nuvem da Tuya,
    que manda para os aparelhos. Nada da sua conversa com o TITAN vai junto.
  * Precisa de um projeto de desenvolvedor na Tuya (grátis): Access ID e Access Secret.
    Passo a passo: docs/casa.md
  * O plano grátis da Tuya precisa ser renovado de tempos em tempos (no site da Tuya).
  * Para voltar à demonstração: .venv/bin/titan disable-tuya
"""


def cmd_enable_tuya(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    print(TUYA_WARNING)
    access_id = (args.access_id or _ask("Access ID (Client ID) do projeto Tuya")).strip()
    if not access_id or not access_id.isalnum() or len(access_id) > 64:
        print("Access ID inválido. Nada foi alterado.", file=sys.stderr)
        return 1
    secret = getpass.getpass("Access Secret (Client Secret) — não aparece na tela: ").strip()
    if not secret or len(secret) > 128:
        print("Access Secret vazio. Nada foi alterado.", file=sys.stderr)
        return 1
    region = (args.region or _ask("Centro de dados (us = Américas/Brasil, eu, cn, in)", "us")).strip().lower()
    if region not in {"us", "eu", "cn", "in", "ueaz", "weaz"}:
        print("Centro de dados inválido. Use us, eu, cn ou in. Nada foi alterado.", file=sys.stderr)
        return 1
    if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
        print("Não confirmado. Nada foi alterado.")
        return 1
    backup = update_env(env_path, {"TITAN_CASA_PROVIDER": "tuya", "TITAN_TUYA_ACCESS_ID": access_id,
                                   "TUYA_ACCESS_SECRET": secret, "TITAN_TUYA_REGION": region,
                                   "TITAN_LOCAL_ONLY": "false"})
    print(f"\nTuya ligada. .env atualizado (permissão 600); cópia anterior: {backup}")
    print("Teste (só lista, não mexe em nada):  .venv/bin/titan tuya-teste")
    print("Depois: .venv/bin/titan ligar  →  no tablet, TITAN Casa › AJUSTES › PROCURAR NOVOS")
    return 0


def cmd_disable_tuya(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    backup = update_env(env_path, {"TITAN_CASA_PROVIDER": "demo", "TUYA_ACCESS_SECRET": None})
    print("TITAN Casa voltou para a demonstração; o Access Secret foi removido do .env.")
    print(f"A cópia {backup} ainda o contém; apague com: rm {backup}")
    return 0


def cmd_tuya_test(_: argparse.Namespace) -> int:
    """Lista os aparelhos da conta Tuya (só leitura: nenhum comando é enviado)."""
    from titan.casa.providers import ProviderError, provider_for

    s = _settings()
    if s.casa_provider != "tuya":
        print("A Tuya está desligada (TITAN_CASA_PROVIDER=demo). Ligue com: .venv/bin/titan enable-tuya")
        return 1
    try:
        found = provider_for(s).list_devices(None)
    except ProviderError as exc:
        print(f"Falhou: {exc}", file=sys.stderr)
        print("Confira o Access ID/Secret, o centro de dados e se a conta do app está ligada ao projeto (docs/casa.md).")
        return 1
    print(f"Conexão com a Tuya OK. {len(found)} aparelho(s):")
    for d in found:
        tipo = {"plug": "tomada", "light": "lâmpada", "tv": "TV (IR)", "ac": "ar (IR)", "fan": "ventilador"}.get(d.kind, d.category)
        print(f"  · {d.name:30} {tipo:12} {'online' if d.online else 'OFFLINE'}")
    uids = {d.meta.get("uid") for d in found if d.meta.get("uid")}
    if len(uids) > 1:
        print("Atenção: há mais de uma conta ligada ao projeto. O TITAN Casa só aceita uma por casa.")
    return 0


def cmd_central_clima(args: argparse.Namespace) -> int:
    """Cidade do clima do TITAN Central (Open-Meteo: grátis, sem chave)."""
    from pathlib import Path

    from titan.central import weather
    from titan.envfile import read_env, update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    name = " ".join(args.cidade).strip() or _ask("Sua cidade (ex.: Fortaleza)")
    if not name or len(name) > 80:
        print("Cidade inválida. Nada foi alterado.", file=sys.stderr)
        return 1
    try:
        found = weather.geocode(name)
    except Exception as exc:
        print(f"Não consegui procurar a cidade ({type(exc).__name__}). O notebook está com internet?", file=sys.stderr)
        return 1
    if not found:
        print(f"Não achei \"{name}\". Tente o nome com o estado, ex.: \"Fortaleza Ceará\".", file=sys.stderr)
        return 1
    where = ", ".join(x for x in (found["name"], found["admin"], found["country"]) if x)
    print(f"Achei: {where}  ({found['lat']:.3f}, {found['lon']:.3f})")
    values = {"TITAN_CENTRAL_CITY": found["name"], "TITAN_CENTRAL_LAT": f"{found['lat']:.4f}",
              "TITAN_CENTRAL_LON": f"{found['lon']:.4f}"}
    if read_env(env_path).get("TITAN_LOCAL_ONLY", "true").lower() != "false":
        print("\nO TITAN está em modo só-local (nada sai do notebook). Para o clima funcionar, o servidor")
        print("consulta a Open-Meteo a cada 20 min mandando SÓ as coordenadas da cidade.")
        if _ask("Digite AUTORIZO para permitir").strip().upper() != "AUTORIZO":
            print("Não confirmado. Nada foi alterado.")
            return 1
        values["TITAN_LOCAL_ONLY"] = "false"
    elif not args.sim and _ask("Usar esta cidade? (s/n)", "s").strip().lower() not in ("s", "sim"):
        print("Nada foi alterado.")
        return 1
    backup = update_env(env_path, values)
    print(f"Pronto: o TITAN Central vai mostrar o clima de {found['name']}. Cópia anterior do .env: {backup}")
    print("Reinicie o servidor (Ctrl+C e .venv/bin/titan ligar).")
    return 0


def _project_paths(env_file: str):
    from pathlib import Path

    env_path = Path(env_file).resolve()
    project = env_path.parent
    titan_bin = str(Path(sys.argv[0]).resolve()) if Path(sys.argv[0]).name == "titan" else str(project / ".venv/bin/titan")
    return env_path, project, titan_bin


def cmd_abrir(args: argparse.Namespace) -> int:
    """Abre um app do TITAN (liga o servidor em segundo plano se estiver desligado)."""
    from titan import desktop
    from titan.envfile import read_env

    env_path, project, titan_bin = _project_paths(args.env_file)
    env = read_env(env_path) if env_path.exists() else {}
    url = desktop.base_url(env)
    if not desktop.server_up(url):
        print(f"Servidor desligado: ligando em segundo plano (registro em {project / 'var/servidor.log'})...")
        desktop.start_server(titan_bin, project, project / "var/servidor.log", project / "var/servidor.pid")
        if not desktop.wait_up(url):
            print("O servidor não respondeu. Veja var/servidor.log ou ligue no terminal: .venv/bin/titan ligar",
                  file=sys.stderr)
            return 1
    found = desktop.find_browser()
    if not found:
        print(f"Nenhum navegador encontrado. Abra: {url}{desktop.APPS[args.app]['path']}", file=sys.stderr)
        return 1
    cmd = desktop.browser_command(found[0], found[1], args.app, url, project / "var/apps")
    import subprocess

    proc = subprocess.Popen(cmd, cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    # o som deste app é a voz do TITAN: nunca é abaixado quando o TITAN fala (ver titan/voice/duck.py)
    try:
        (project / "var/apps").mkdir(parents=True, exist_ok=True)
        (project / f"var/apps/{args.app}.pid").write_text(str(getattr(proc, "pid", "")))
    except OSError:
        pass
    print(f"{desktop.APPS[args.app]['name']} abrindo: {url}{desktop.APPS[args.app]['path']}")
    if args.app == "central":
        print("Tela cheia: Alt+F4 sai. Mexa o mouse para ver os botões.")
    return 0


def cmd_central(args: argparse.Namespace) -> int:
    """Abre o TITAN Central em tela cheia (para o notebook ligado na TV pelo HDMI)."""
    args.app = "central"
    return cmd_abrir(args)


def cmd_instalar_app(args: argparse.Namespace) -> int:
    """Põe TITAN, TITAN Casa e TITAN Central no menu de aplicativos do Linux."""
    from pathlib import Path

    from titan import desktop

    env_path, project, titan_bin = _project_paths(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    found = desktop.find_browser()
    if not found:
        print("Nenhum navegador (Firefox ou Chromium) encontrado.", file=sys.stderr)
        return 1
    apps_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    icons = {"main": project / "apps/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png",
             "casa": project / "apps/android/app/src/casa/res/mipmap-xxxhdpi/ic_launcher.png",
             "central": project / "apps/android/app/src/central/res/mipmap-xxxhdpi/ic_launcher.png"}
    for app, info in desktop.APPS.items():
        f = apps_dir / f"titan-{app}.desktop"
        f.write_text(desktop.desktop_entry(app, titan_bin, project, env_path, icons[info["icon"]]))
        f.chmod(0o755)
        print(f"  ✓ {info['name']} no menu ({f})")
    # cadeado do TITAN confiável nos perfis dos apps (sem aviso de segurança)
    ca = project / "var/tls/titan-ca.crt"
    done = desktop.trust_ca(ca, project / "var/apps", found[0])
    if done:
        print("  ✓ Cadeado do TITAN confiável nos apps (sem aviso de segurança).")
    elif not ca.is_file():
        print("  ! Ainda não há cadeado (rode .venv/bin/titan ligar uma vez) — depois rode este comando de novo.")
    else:
        print("  ! Para os apps confiarem no cadeado sozinhos, instale uma ferramenta e rode este comando de novo:")
        print("      sudo apt install libnss3-tools")
        print("    (Sem ela, na primeira vez cada app mostra o aviso: Avançado → Aceitar o risco e continuar.)")
    autostart = args.ao_ligar
    if autostart is None and sys.stdin.isatty():
        autostart = _ask("Abrir o TITAN Central sozinho quando o notebook ligar? (s/n)", "n").strip().lower() in ("s", "sim")
    auto = Path.home() / ".config/autostart/titan-central.desktop"
    if autostart:
        auto.parent.mkdir(parents=True, exist_ok=True)
        auto.write_text(desktop.desktop_entry("central", titan_bin, project, env_path, icons["central"]))
        print("  ✓ A Central abre sozinha quando o notebook ligar (para tirar: titan instalar-app --nao-ao-ligar).")
    elif autostart is False and auto.exists():
        auto.unlink()
        print("  ✓ A Central não abre mais sozinha ao ligar.")
    print("\nPronto. Procure \"TITAN\" no menu do Linux Mint. Clicou no ícone: o servidor liga sozinho se precisar.")
    print("Para desligar o servidor que foi ligado pelo ícone: .venv/bin/titan parar")
    return 0


def cmd_parar(args: argparse.Namespace) -> int:
    """Desliga o servidor que um app ligou em segundo plano."""
    from titan import desktop

    env_path, project, _ = _project_paths(args.env_file)
    if desktop.stop_server(project / "var/servidor.pid"):
        print("Servidor desligado.")
        return 0
    print("Nenhum servidor ligado pelos apps. (Se ligou no terminal, use Ctrl+C lá.)")
    return 1


def cmd_enable_groq_stt(args: argparse.Namespace) -> int:
    return _enable_cloud_stt(args, "groq")


def cmd_disable_groq_stt(args: argparse.Namespace) -> int:
    return _disable_cloud_stt(args, "groq")


def cmd_enable_xai_stt(args: argparse.Namespace) -> int:
    return _enable_cloud_stt(args, "xai")


def cmd_disable_xai_stt(args: argparse.Namespace) -> int:
    return _disable_cloud_stt(args, "xai")


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


MOBILE_WARNING = """
Ligar o TITAN ao celular
  * O TITAN passa a aceitar conexões da sua Wi-Fi (e do Tailscale, se escolher),
    sempre com cadeado (HTTPS) e com login obrigatório.
  * Nada é aberto para a internet: sem portas no roteador, sem túnel público.
  * Por 15 minutos fica no ar uma página de instalação sem cadeado que entrega só
    o certificado PÚBLICO do notebook e as instruções.
  * Para desfazer: .venv/bin/titan desligar-celular
"""


def cmd_mobile_on(args: argparse.Namespace) -> int:
    from pathlib import Path

    from titan import mobile
    from titan.envfile import read_env, update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    try:
        ip = mobile.lan_ip()
        ts = mobile.tailscale_ip() if args.tailscale else None
        if args.tailscale and not ts:
            print("Tailscale não encontrado ou desconectado. Instale e entre com: "
                  "curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up\n"
                  "Seguindo só com a Wi-Fi.")
        print(MOBILE_WARNING)
        print(f"Notebook na Wi-Fi: {ip} (rede {mobile.lan_network(ip)})" + (f" · Tailscale: {ts}" if ts else ""))
        if _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
            print("Não confirmado. Nada foi alterado.")
            return 1
        ca, crt, key = mobile.make_certificates([ip] + ([ts] if ts else []))
    except mobile.MobileError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    updates = mobile.env_updates(ip, crt, key, tailscale=bool(ts))
    backup = update_env(env_path, updates)
    port = read_env(env_path).get("TITAN_PORT", "8000")
    app_url = f"https://{ip}:{port}"
    print(f"\n✓ Cadeado (HTTPS) criado só para este notebook ({crt})")
    print(f"✓ Só aparelhos da sua Wi-Fi{' e do Tailscale' if ts else ''} podem chegar ao TITAN")
    print("✓ Login continua obrigatório")
    print(f"✓ .env atualizado (cópia anterior: {backup})")
    print(f"\nDepois de instalar, o TITAN fica em {app_url}" + (f" (fora de casa: https://{ts}:{port})" if ts else ""))
    print(f"No notebook, use https://localhost:{port} — para o navegador do notebook confiar,")
    print(f"importe {ca} em Configurações → Privacidade e segurança → Certificados → Autoridades.")
    print("Reinicie o TITAN para valer:  .venv/bin/titan serve")
    if args.sem_pagina:
        print(f"\nInstale {ca} no celular (cabo USB) e abra {app_url}.")
        return 0
    install_url = f"http://{ip}:{args.porta}/instalar"
    try:
        server = mobile.make_install_server(ca, app_url, updates["TITAN_ALLOWED_NETWORKS"].split(","), args.porta)
    except OSError as exc:
        print(f"Não consegui abrir a página de instalação na porta {args.porta}: {exc}", file=sys.stderr)
        return 1
    qr = mobile.qr_text(install_url)
    print("\nAponte a câmera do celular para o QR code:" if qr else
          "\n(Para mostrar um QR code aqui: .venv/bin/pip install segno)")
    if qr:
        print(qr)
    print(f"ou digite no navegador do celular:  {install_url}")
    print(f"A página fica aberta por {mobile.INSTALL_MINUTES} minutos (Ctrl+C fecha antes).")
    try:
        mobile.serve_install_page(server)
    except KeyboardInterrupt:
        pass
    print("Página de instalação fechada.")
    return 0


TAILSCALE_HOWTO = """
Para usar o TITAN FORA DE CASA (4G, outra Wi-Fi), ligue o Tailscale — grátis e privado:
  1. No notebook:  curl -fsSL https://tailscale.com/install.sh | sh  &&  sudo tailscale up
     (abra o link que aparecer e entre com a sua conta)
  2. No celular: app Tailscale, mesma conta, deixe "Connected".
  3. Rode de novo:  .venv/bin/titan ligar
"""

LIGAR_WARNING = """
Primeira vez: ligar o TITAN para o notebook E o celular (um comando só)
  * O TITAN passa a aceitar conexões da sua Wi-Fi, sempre com cadeado (HTTPS) e login.
  * Nada é aberto para a internet: sem portas no roteador, sem túnel público.
  * O navegador deste notebook (Chrome/Chromium) passa a confiar no cadeado do TITAN.
  * Para desfazer: .venv/bin/titan desligar-celular
"""


def _prepare_both(env_path, tailscale="auto", ask: bool = True):
    """Deixa o .env e o cadeado prontos para notebook + celular. Devolve (ip, ts, ca, nets) ou None.

    ``tailscale``: "auto" (usa se estiver instalado e conectado), "on" (avisa se faltar) ou "off".
    """
    if tailscale is True:
        tailscale = "on"
    elif tailscale is False:
        tailscale = "auto"
    from pathlib import Path

    from titan import mobile
    from titan.envfile import read_env, update_env

    env = read_env(env_path)
    ip = mobile.lan_ip()
    ts = mobile.tailscale_ip() if tailscale != "off" else None
    if tailscale == "on" and not ts:
        print("! Tailscale não encontrado ou desconectado neste notebook (veja como ligar abaixo).")
    had_ts = mobile.TAILSCALE_NET in env.get("TITAN_ALLOWED_NETWORKS", "")
    crt = Path(env.get("TITAN_TLS_CERT_FILE", "")) if env.get("TITAN_TLS_CERT_FILE") else None
    ca = mobile.TLS_DIR / "titan-ca.crt"
    first = not (crt and crt.is_file() and ca.is_file() and env.get("TITAN_HOST") == "0.0.0.0")
    if first:
        print(LIGAR_WARNING)
        print(f"Notebook na Wi-Fi: {ip}" + (f" · Tailscale: {ts}" if ts else ""))
        if ask and _ask("Digite AUTORIZO para confirmar").strip().upper() != "AUTORIZO":
            print("Não confirmado. Nada foi alterado.")
            return None
    wanted = [ip] + ([ts] if ts else [])
    if first or not set(wanted) <= mobile.cert_ips(crt):
        if not first:
            print(f"Endereço novo do notebook ({', '.join(wanted)}): renovando o cadeado "
                  "(o cadeado instalado no celular continua valendo).")
        ca, crt, key = mobile.make_certificates(wanted)
    else:
        key = Path(env.get("TITAN_TLS_KEY_FILE", str(mobile.TLS_DIR / "server.key")))
    if ts and not had_ts and not first:
        print("✓ Tailscale encontrado: o TITAN passa a aceitar também os SEUS aparelhos do Tailscale "
              "(de qualquer lugar; ninguém de fora da sua conta Tailscale chega nele).")
    updates = mobile.env_updates(ip, crt, key, tailscale=(bool(ts) or had_ts) and tailscale != "off")
    if any(env.get(k) != v for k, v in updates.items()):
        update_env(env_path, updates)
    if first:
        problem = mobile.trust_on_notebook(ca)
        print("✓ Chrome/Chromium do notebook confia no cadeado do TITAN" if problem is None else
              f"! O navegador do notebook ainda não confia no cadeado: {problem}")
    return ip, ts, ca, updates["TITAN_ALLOWED_NETWORKS"].split(",")


def cmd_ligar(args: argparse.Namespace) -> int:
    """Um comando só: liga o servidor e deixa notebook e celular prontos."""
    import shutil
    import subprocess
    import threading
    from pathlib import Path

    from titan import mobile
    from titan.config.settings import get_settings
    from titan.envfile import read_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe. Rode primeiro scripts/setup.sh.", file=sys.stderr)
        return 1
    try:
        ready = _prepare_both(env_path, "off" if args.sem_tailscale else "on" if args.tailscale else "auto")
    except mobile.MobileError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    if ready is None:
        return 1
    ip, ts, ca, nets = ready
    port = read_env(env_path).get("TITAN_PORT", "8000")
    lan_url = f"https://{ip}:{port}"
    ts_url = f"https://{ts}:{port}" if ts else None
    app_url = ts_url or lan_url
    print("\n" + "=" * 64)
    print(f"  NOTEBOOK:  https://localhost:{port}")
    if ts_url:
        print(f"  CELULAR, EM QUALQUER LUGAR (Tailscale):  {ts_url}")
        print(f"  CELULAR, Wi-Fi de casa (reserva):         {lan_url}")
    else:
        print(f"  CELULAR:   {lan_url}   (só na mesma Wi-Fi)")
    print(f"  TITAN CASA (tablet):  {lan_url}/casa")
    print(f"  TITAN CENTRAL (TV):   {lan_url}/central   (notebook na TV pelo HDMI: titan central)")
    print("=" * 64)
    if not ts_url:
        print(TAILSCALE_HOWTO)

    if not args.sem_pagina:
        try:
            server = mobile.make_install_server(ca, app_url, nets, args.porta,
                                                alt_url=lan_url if ts_url else None)
        except OSError as exc:
            print(f"(Página de instalação não abriu na porta {args.porta}: {exc})")
        else:
            install_url = f"http://{ip}:{args.porta}/instalar"
            print(f"\nCelular novo? Aponte a câmera para o QR (ou abra {install_url}):")
            qr = mobile.qr_text(install_url)
            print(qr if qr else "(Para ver o QR code aqui: .venv/bin/pip install segno)")
            print(f"Lá estão o cadeado e os apps TITAN, TITAN Casa e TITAN Central (APK). A página fecha sozinha em {mobile.INSTALL_MINUTES} minutos.")
            threading.Thread(target=mobile.serve_install_page, args=(server,), daemon=True).start()

    if not args.sem_navegador and shutil.which("xdg-open"):
        def _open() -> None:
            subprocess.Popen(["xdg-open", f"https://localhost:{port}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Timer(4, _open).start()

    print("\nLigando o servidor... (Ctrl+C desliga tudo)\n")
    get_settings.cache_clear()
    return cmd_serve(argparse.Namespace(no_migrate=False))


def cmd_mobile_off(args: argparse.Namespace) -> int:
    import shutil
    from pathlib import Path

    from titan import mobile
    from titan.envfile import update_env

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"{env_path} não existe.", file=sys.stderr)
        return 1
    update_env(env_path, {k: None for k in mobile.ENV_KEYS})
    print("Acesso pelo celular desligado: o TITAN volta a aceitar só este notebook (http://127.0.0.1).")
    if args.apagar_certificados:
        shutil.rmtree(mobile.TLS_DIR, ignore_errors=True)
        print(f"Certificados apagados ({mobile.TLS_DIR}). Remova também o cadeado do celular:")
        print("  Configurações → Segurança → Credenciais do usuário → TITAN CA → Remover")
    print("Reinicie o servidor para aplicar.")
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
        "TITAN_VOICE_STT": "vosk",
        "TITAN_ALLOW_EXTERNAL_VOICE": "false",
        "TITAN_WEB_ENABLED": "false",
    }
    if not args.keep_key:
        updates["ANTHROPIC_API_KEY"] = None  # remove a linha
        updates["GROQ_API_KEY"] = None
        updates["XAI_API_KEY"] = None
    backup = update_env(env_path, updates)
    print("Provedores externos desligados; modo 100% local restaurado.")
    if not args.keep_key:
        print("As chaves da Anthropic, Groq e xAI foram removidas do .env.")
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
    p = sub.add_parser("enable-groq-stt", help="liga o reconhecimento de voz on-line da Groq (o áudio sai do notebook)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--minutos", help="teto de minutos de fala por dia")
    p.set_defaults(fn=cmd_enable_groq_stt)
    p = sub.add_parser("disable-groq-stt", help="volta ao reconhecimento local (Vosk)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--keep-key", action="store_true", help="mantém a chave no .env")
    p.set_defaults(fn=cmd_disable_groq_stt)
    p = sub.add_parser("testar-voz", help="grava uma fala e mostra o que o Vosk e a Groq/xAI entenderam")
    p.add_argument("--arquivo", help="usar um WAV em vez de gravar")
    p.add_argument("--segundos", type=int, default=5)
    p.set_defaults(fn=cmd_test_voice)
    p = sub.add_parser("enable-xai-stt", help="liga o reconhecimento de voz on-line da xAI/Grok (o áudio sai do notebook)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--minutos", help="teto de minutos de fala por dia")
    p.set_defaults(fn=cmd_enable_xai_stt)
    p = sub.add_parser("disable-xai-stt", help="volta ao reconhecimento local (Vosk)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--keep-key", action="store_true", help="mantém a chave no .env")
    p.set_defaults(fn=cmd_disable_xai_stt)
    p = sub.add_parser("enable-tuya", help="liga o TITAN Casa à sua conta Tuya/Smart Life (nuvem da Tuya)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--access-id")
    p.add_argument("--region")
    p.set_defaults(fn=cmd_enable_tuya)
    p = sub.add_parser("disable-tuya", help="TITAN Casa volta para a demonstração")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_disable_tuya)
    sub.add_parser("tuya-teste", help="lista os aparelhos da conta Tuya (só leitura)").set_defaults(fn=cmd_tuya_test)
    p = sub.add_parser("central-clima", help="cidade do clima no TITAN Central (Open-Meteo, grátis)")
    p.add_argument("cidade", nargs="*")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--sim", action="store_true", help="não pergunta de novo")
    p.set_defaults(fn=cmd_central_clima)
    p = sub.add_parser("central", help="abre o TITAN Central em tela cheia (notebook na TV pelo HDMI)")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_central)
    p = sub.add_parser("abrir", help="abre um app do TITAN (liga o servidor sozinho se precisar)")
    p.add_argument("app", choices=["titan", "casa", "central"])
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_abrir)
    p = sub.add_parser("instalar-app", help="põe TITAN, TITAN Casa e TITAN Central no menu do Linux")
    p.add_argument("--env-file", default=".env")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--ao-ligar", dest="ao_ligar", action="store_true", default=None,
                   help="abre a Central sozinha quando o notebook ligar")
    g.add_argument("--nao-ao-ligar", dest="ao_ligar", action="store_false")
    p.set_defaults(fn=cmd_instalar_app)
    p = sub.add_parser("parar", help="desliga o servidor ligado pelos apps")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(fn=cmd_parar)
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
    p = sub.add_parser("ligar-celular", help="liga o acesso pelo celular (Wi-Fi/Tailscale, HTTPS) com QR code")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--tailscale", action="store_true", help="também permite usar fora de casa pelo Tailscale")
    p.add_argument("--porta", type=int, default=8001, help="porta da página de instalação temporária")
    p.add_argument("--sem-pagina", action="store_true", help="não abre a página de instalação")
    p.set_defaults(fn=cmd_mobile_on)
    p = sub.add_parser("ligar", help="UM COMANDO SÓ: liga o servidor para o notebook e o celular")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--tailscale", action="store_true", help="exige o Tailscale (avisa se faltar); por padrão já é usado se estiver ligado")
    p.add_argument("--sem-tailscale", action="store_true", help="não usa o Tailscale (só a Wi-Fi de casa)")
    p.add_argument("--porta", type=int, default=8001, help="porta da página de instalação temporária")
    p.add_argument("--sem-pagina", action="store_true", help="não abre a página de instalação/QR")
    p.add_argument("--sem-navegador", action="store_true", help="não abre o navegador do notebook")
    p.set_defaults(fn=cmd_ligar)
    p = sub.add_parser("desligar-celular", help="desliga o acesso pelo celular (volta a só este notebook)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--apagar-certificados", action="store_true")
    p.set_defaults(fn=cmd_mobile_off)
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
