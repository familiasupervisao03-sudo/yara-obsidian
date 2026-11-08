"""Preferências explícitas do usuário: consultar, alterar e apagar (ver titan/memory/preferences.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.memory import preferences as prefs
from titan_api.deps import CurrentUser, current_user, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/preferences", tags=["preferences"],
                   responses={401: {"model": ErrorResponse}})


class Correction(BaseModel):
    heard: str = Field(min_length=1, max_length=60, description="o que o reconhecimento entende")
    meant: str = Field(min_length=1, max_length=60, description="o que você quis dizer")


class PreferencesIO(BaseModel):
    response_length: Literal["curta", "normal", "detalhada"] = "normal"
    formality: Literal["informal", "neutra", "formal"] = "neutra"
    examples: Literal["auto", "sim", "nao"] = "auto"
    voice_rate: int = Field(default=0, ge=-30, le=30, description="% da velocidade normal da voz")
    corrections: list[Correction] = Field(default_factory=list, max_length=prefs.MAX_CORRECTIONS)


@router.get("", response_model=PreferencesIO)
def read(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return PreferencesIO(**prefs.get(db, cu.user.id))


@router.put("", response_model=PreferencesIO, responses={422: {"model": ErrorResponse}})
def update(body: PreferencesIO, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        saved = prefs.save(db, cu.user.id, body.model_dump())
    except prefs.PreferenceError as exc:
        return JSONResponse({"error": {"code": "validation_error", "message": str(exc)}}, status_code=422)
    # Auditoria sem o conteúdo das correções (podem conter nomes pessoais).
    audit.record(db, "preferences.updated", actor_type="user", actor_id=cu.user.id,
                 entity_type="preferences", entity_id=str(cu.user.id),
                 data={k: saved[k] for k in ("response_length", "formality", "examples", "voice_rate")}
                 | {"corrections": len(saved["corrections"])})
    return PreferencesIO(**saved)


@router.delete("", status_code=204)
def erase(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)) -> Response:
    if prefs.delete(db, cu.user.id):
        audit.record(db, "preferences.deleted", actor_type="user", actor_id=cu.user.id,
                     entity_type="preferences", entity_id=str(cu.user.id))
    return Response(status_code=204)
