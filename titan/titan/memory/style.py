"""Instruções de estilo enviadas ao modelo junto com o prompt do sistema.

Só frases FIXAS, escolhidas por opções fechadas (modo voz e preferências
explícitas do usuário). Nenhum texto livre — do usuário, aprendido ou vindo de
outra fonte — entra aqui: preferências mudam o jeito de responder, nunca as
regras de segurança, permissões ou aprovações.
"""

from __future__ import annotations

from typing import Optional

VOICE = (
    "A resposta será lida em voz alta pelo TITAN. Fale como numa conversa: frases curtas e "
    "naturais, sem markdown, listas, tabelas, emojis, links ou blocos de código. Para perguntas "
    "simples, responda em uma a três frases. Escreva números, horários, datas, valores e siglas do "
    "jeito que são falados (por exemplo: 'dez e meia', 'vinte e três reais'). Se o assunto for "
    "longo, dê o essencial e pergunte se a pessoa quer mais detalhes."
)

# Opções fechadas das preferências (titan/memory/preferences.py valida os valores).
LENGTH = {
    "curta": "O usuário prefere respostas curtas e diretas.",
    "normal": "",
    "detalhada": "O usuário prefere respostas mais completas, com explicações.",
}
FORMALITY = {
    "informal": "Use um tom informal e próximo, sem gírias forçadas.",
    "neutra": "",
    "formal": "Use um tom formal e educado.",
}
EXAMPLES = {
    "sim": "Quando ajudar, inclua um exemplo curto.",
    "nao": "Evite exemplos, a não ser que o usuário peça.",
    "auto": "",
}


def build_style(mode: str = "text", prefs: Optional[dict] = None) -> str:
    """Monta o texto de estilo. ``mode``: "text" ou "voice"."""
    parts = []
    if mode == "voice":
        parts.append(VOICE)
    p = prefs or {}
    for table, key in ((LENGTH, "response_length"), (FORMALITY, "formality"), (EXAMPLES, "examples")):
        sentence = table.get(str(p.get(key, "")), "")
        if sentence:
            parts.append(sentence)
    return " ".join(parts)
