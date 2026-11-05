"""O TITAN (chat e voz do app principal) também manda na casa: "liga o ventilador".

Só pega frases que são claramente comandos (começam com liga/desliga/acende/apaga/
põe/coloca/aumenta/abaixa, ou são a frase de uma cena) e que citam um aparelho
cadastrado. O resto (perguntas, conversa) segue para a IA normalmente.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from titan.casa import service as casa
from titan.casa.providers import ProviderError, provider_for

log = logging.getLogger("titan.casa")
_COMMAND = re.compile(r"^(liga|desliga|acende|apaga|poe|coloca|bota|aumenta|abaixa|diminui|ativa|desativa)\b")
_cache: dict[tuple, object] = {}


def shared_provider(settings):
    key = (settings.casa_provider, settings.tuya_access_id, settings.tuya_region)
    if key not in _cache:
        _cache[key] = provider_for(settings)
    return _cache[key]


def try_handle(settings, session_factory, user_id: uuid.UUID, text: str) -> Optional[str]:
    """Executa o comando da casa e devolve a resposta, ou None se não for comando da casa."""
    t, _ = casa.strip_wake(text)
    if not t or len(t) > 120:
        return None
    try:
        with session_factory.begin() as db:
            home = casa.home_for(db, user_id, settings.casa_provider)
            if home.provider != settings.casa_provider:
                home.provider = settings.casa_provider
            ds = casa.devices(db, home, True)
            scs = casa.scenes(db, home)
            if not ds:
                return None
            intent = casa.understand(text, ds, scs)
            kind = intent["type"]
            if kind == "scene":
                sc = intent["scene"]
                res = casa.run_scene(db, home, sc, shared_provider(settings), user_id=user_id, source="chat",
                                     limit=settings.casa_max_commands_per_minute)
                reply = sc.reply or f"Cena {sc.name} pronta."
                return reply + (f" Não consegui: {', '.join(f.split(':')[0] for f in res['failed'])}." if res["failed"] else "")
            if not _COMMAND.match(t):
                return None
            if kind == "act":
                d = intent["device"]
                casa.act(db, home, d, intent["action"], shared_provider(settings), user_id=user_id, source="chat",
                         limit=settings.casa_max_commands_per_minute)
                return casa.reply_for(intent, d)
            if kind == "all":
                for d in ds:
                    casa.act(db, home, d, {"do": "on" if intent["on"] else "off"} if d.kind != "ac"
                             else {"do": "ac", "on": intent["on"]}, shared_provider(settings), user_id=user_id,
                             source="chat", limit=settings.casa_max_commands_per_minute)
                return "Liguei tudo." if intent["on"] else "Desliguei tudo."
    except casa.RateLimited as exc:
        return str(exc)
    except (ProviderError, casa.CasaError) as exc:
        return f"Não consegui mexer na casa agora: {exc}"
    except Exception:
        log.exception("Falha ao tratar comando da casa pelo chat")
    return None
