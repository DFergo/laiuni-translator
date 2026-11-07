"""Admin management of machine-API tokens (Sprint 22, SPEC §16.1)."""

import logging

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.v1.admin.auth import require_admin
from src.services import api_tokens

logger = logging.getLogger("backend.admin.api_tokens")

router = APIRouter(prefix="/admin/api-tokens", tags=["admin-api-tokens"])


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["translate", "admin"] = Field(
        "translate", description="`admin` also grants every /admin/* route (SPEC §16.5).")


@router.get("")
async def list_tokens(_: dict = Depends(require_admin)):
    return {"tokens": api_tokens.list_tokens()}


@router.post("")
async def create_token(req: CreateTokenRequest, _: dict = Depends(require_admin)):
    """Returns the plaintext token **once**; only its hash is kept."""
    try:
        plaintext, entry = api_tokens.create(req.name, req.scope)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    logger.info(f"API token created: {entry['id']} ({entry['name']}, scope={entry['scope']})")
    return {"token": plaintext, **entry}


@router.delete("/{token_id}")
async def revoke_token(token_id: str, _: dict = Depends(require_admin)):
    if not api_tokens.revoke(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    logger.info(f"API token revoked: {token_id}")
    return {"ok": True}
