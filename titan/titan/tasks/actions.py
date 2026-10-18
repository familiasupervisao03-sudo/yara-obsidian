"""Ações que uma etapa pode executar e critérios objetivos de sucesso.

Somente ações deste catálogo são aceitas em planos (inclusive planos gerados
pelo modelo). Ações sensíveis SEMPRE exigem aprovação humana, independentemente
do que o plano disser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    sensitive: bool
    risk: str
    required_params: tuple[str, ...]
    available: bool = True
    unavailable_reason: str = ""


ACTIONS: dict[str, ActionSpec] = {
    "note": ActionSpec(
        name="note", label="Registrar anotação na memória local", sensitive=False,
        risk="Grava um texto no banco local do notebook. Nada sai do computador.",
        required_params=("text",),
    ),
    "ask_model": ActionSpec(
        name="ask_model", label="Perguntar ao modelo de IA configurado", sensitive=True,
        risk="Envia o texto do prompt ao provedor de IA configurado. Se for externo "
             "(ex.: Anthropic), o texto sai do notebook e a chamada consome créditos, "
             "limitada pelo orçamento diário.",
        required_params=("prompt",),
    ),
    "wait_for_user": ActionSpec(
        name="wait_for_user", label="Perguntar algo ao usuário", sensitive=False,
        risk="Pausa a tarefa até o usuário responder pela interface.",
        required_params=("question",),
    ),
    "run_code": ActionSpec(
        name="run_code", label="Executar código em sandbox isolado", sensitive=True,
        risk="Executaria código gerado. BLOQUEADO: o sandbox isolado ainda não foi "
             "implementado e validado (Fase 3).",
        required_params=("language", "code"),
        available=False,
        unavailable_reason="Execução de código bloqueada até existir sandbox validado (Fase 3).",
    ),
}

CRITERIA_TYPES = {"output_nonempty", "contains", "not_contains", "equals", "max_length"}


class PlanValidationError(ValueError):
    pass


def validate_step(step: dict[str, Any]) -> None:
    action = step.get("action_type")
    spec = ACTIONS.get(action or "")
    if spec is None:
        raise PlanValidationError(f"Ação desconhecida: {action!r}. Permitidas: {sorted(ACTIONS)}")
    params = step.get("parameters") or {}
    if not isinstance(params, dict):
        raise PlanValidationError("parameters deve ser um objeto.")
    for p in spec.required_params:
        if not str(params.get(p, "")).strip():
            raise PlanValidationError(f"Etapa '{step.get('title')}': parâmetro '{p}' é obrigatório.")
    criteria = step.get("success_criteria") or []
    if not criteria:
        raise PlanValidationError(
            f"Etapa '{step.get('title')}': defina ao menos um critério objetivo de sucesso."
        )
    for c in criteria:
        if not isinstance(c, dict) or c.get("type") not in CRITERIA_TYPES:
            raise PlanValidationError(f"Critério inválido: {c!r}. Tipos: {sorted(CRITERIA_TYPES)}")
        if c["type"] in {"contains", "not_contains", "equals"} and not str(c.get("value", "")):
            raise PlanValidationError(f"Critério '{c['type']}' exige 'value'.")
        if c["type"] == "max_length":
            try:
                if int(c.get("value")) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise PlanValidationError("Critério 'max_length' exige 'value' inteiro positivo.")


def check_criterion(criterion: dict[str, Any], output: str) -> tuple[bool, str]:
    kind = criterion["type"]
    value = criterion.get("value")
    if kind == "output_nonempty":
        ok = bool(output.strip())
        return ok, "saída não vazia" if ok else "saída vazia"
    if kind == "contains":
        ok = str(value).lower() in output.lower()
        return ok, f"{'contém' if ok else 'não contém'} {value!r}"
    if kind == "not_contains":
        ok = str(value).lower() not in output.lower()
        return ok, f"{'não contém' if ok else 'contém'} {value!r}"
    if kind == "equals":
        ok = output.strip() == str(value).strip()
        return ok, "igual ao esperado" if ok else "diferente do esperado"
    if kind == "max_length":
        ok = len(output) <= int(value)
        return ok, f"{len(output)} caracteres (limite {value})"
    return False, f"critério desconhecido {kind}"


def describe_criterion(c: dict[str, Any]) -> str:
    return {
        "output_nonempty": "a saída não pode ser vazia",
        "contains": f"a saída deve conter {c.get('value')!r}",
        "not_contains": f"a saída não pode conter {c.get('value')!r}",
        "equals": f"a saída deve ser exatamente {c.get('value')!r}",
        "max_length": f"a saída deve ter no máximo {c.get('value')} caracteres",
    }.get(c.get("type", ""), str(c))
