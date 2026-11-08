"""O que o TITAN NUNCA guarda na memória (nem sugere guardar).

Regra do dono: nada que, se vazasse, pudesse causar problema — documentos, contatos,
endereço/escola/localização, senhas e dados de banco, saúde, intimidade e dados de
outras pessoas. Verificação por padrões (rápida, sem IA) aplicada a TODA lembrança,
venha da IA, de uma resposta às perguntas ou digitada pelo próprio usuário.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

BLOCKED_MESSAGE = "Isso eu não guardo, pra sua segurança"


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "parece um CPF"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}-?[\dxX]\b"), "parece um RG"),
    (re.compile(r"(?:\+?55\s?)?\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"), "parece um telefone"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "parece um número de cartão"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "parece um e-mail"),
    (re.compile(r"\b\d{5}-?\d{3}\b"), "parece um CEP"),
    (re.compile(r"\b(sk-ant-|gsk_|xai-|sk-)[\w-]{8,}"), "parece uma chave de API"),
]

# Palavras (sem acento) que indicam assunto que não deve ser guardado.
_WORDS: list[tuple[str, str]] = [
    (r"\bsenhas?\b|\bpassword\b|\bpin\b|\bcvv\b|\btoken\b|\bcodigo de (seguranca|verificacao)\b", "senha ou código"),
    (r"\bcpf\b|\b(rg|identidade|passaporte|cnh)\b|\bcertidao\b", "documento"),
    (r"\b(cartao|conta|agencia) (do banco|bancari|de credito|de debito)|\bpix\b.*\b(chave|e\b)|\bchave pix\b|\bsaldo\b|\bextrato\b",
     "dados de banco"),
    (r"\bmoro (na|no|em)\b|\bmeu endereco\b|\bminha rua\b|\brua \w+|\bavenida \w+|\bbairro\b|\bcep\b|\bapartamento \d|\bcasa \d",
     "endereço"),
    (r"\b(estudo|estudei) (na|no|em) (escola|colegio)\b|\bminha escola (e|se chama)\b|\bnome da (minha )?escola\b|\bcolegio \w+",
     "escola"),
    (r"\bestou (agora )?(na|no|em) (casa|escola|shopping|praca)\b|\bminha localizacao\b", "onde você está"),
    (r"\b(depressao|ansiedade|remedio|medicamento|diagnostico|doenca|transtorno|terapia|psicolog|psiquiatr|automutil|suicid)",
     "saúde"),
    (r"\b(sexo|sexual|nude|namorad[ao]s? (me|fez)|intim)", "intimidade"),
    (r"\b(apanho|me bate|briga (em|na) casa|meus pais brigam|violencia)", "assunto de família"),
    (r"\b(meu|minha) (pai|mae|irma|irmao|amig[ao]|namorad[ao]|primo|prima|tio|tia) (se chama|mora|trabalha|tem)\b",
     "dados de outra pessoa"),
    (r"\bmeu nome (completo|inteiro)\b|\bsobrenome\b", "nome completo"),
]
_WORD_PATTERNS = [(re.compile(p), why) for p, why in _WORDS]


def sensitive_reason(text: str) -> Optional[str]:
    """Motivo pelo qual ``text`` não pode ir para a memória, ou None se está tudo bem."""
    for pat, why in _PATTERNS:
        if pat.search(text):
            return why
    n = _norm(text)
    for pat, why in _WORD_PATTERNS:
        if pat.search(n):
            return why
    return None
