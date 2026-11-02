"""Shared authentication and authorization dependencies."""
from __future__ import annotations

from typing import Annotated
import hashlib
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.cache import cache_get_json, cache_set_json, token_cache_key, user_cache_key
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models import Rol, Usuario

security = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]
USER_TTL = 30


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_revoked(token: str) -> bool:
    return bool(cache_get_json(f"auth:revoked:{_token_fingerprint(token)}"))


def _valid_account(user: Usuario) -> bool:
    return (user.is_enabled is True and user.account_non_expired is not False
            and user.account_non_locked is not False and user.credentials_non_expired is not False)


def _cache_user(user: Usuario, role_name: str) -> None:
    fields = ("usuario_id", "account_non_expired", "account_non_locked", "credentials_non_expired",
              "is_enabled", "empresa_id", "rol_id", "numero_identificacion", "telefono", "correo",
              "direccion", "apellidos", "nombres", "imagen", "tipo_identificacion")
    data = {name: getattr(user, name) for name in fields}
    cache_set_json(user_cache_key(int(user.usuario_id)), {"usuario": data, "rol": role_name}, USER_TTL)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: DB,
) -> Usuario:
    if not credentials:
        raise HTTPException(401, "Token requerido", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    if _is_revoked(token):
        raise HTTPException(401, "Token revocado")
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Token inválido o expirado")

    cached_session = cache_get_json(token_cache_key(token))
    if cached_session and int(cached_session.get("usuario_id", -1)) != user_id:
        raise HTTPException(401, "Sesión inválida")
    cached = cache_get_json(user_cache_key(user_id))
    if cached and isinstance(cached.get("usuario"), dict):
        user = Usuario(**cached["usuario"])
        user._cached_role = cached.get("rol", "")
        if not _valid_account(user):
            raise HTTPException(401, "Usuario no autorizado o cuenta pendiente de activación")
        return user

    user = db.get(Usuario, user_id)
    if not user or not _valid_account(user):
        raise HTTPException(401, "Usuario no autorizado o cuenta pendiente de activación")
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    role_name = str(role.rol) if role and role.rol else ""
    _cache_user(user, role_name)
    token_expires = max(1, int(payload["exp"] - time.time()))
    cache_set_json(token_cache_key(token), {"usuario_id": user_id, "rol": role_name}, token_expires)
    return user


def user_role(user: Usuario, db: Session) -> str:
    cached_role = getattr(user, "_cached_role", None)
    if cached_role is not None:
        return str(cached_role)
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    return str(role.rol) if role and role.rol else ""


def require_roles(*roles: str):
    def checker(user: Annotated[Usuario, Depends(current_user)], db: DB) -> Usuario:
        if user_role(user, db) not in roles:
            raise HTTPException(403, "No tienes permisos para este recurso")
        return user
    return checker


admin_user = require_roles("ADMIN")
provider_user = require_roles("PROVEEDOR")
