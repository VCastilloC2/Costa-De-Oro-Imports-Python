"""Shared authentication and authorization dependencies."""
from __future__ import annotations

from typing import Annotated
import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.cache import (
    cache_auth_token, cache_auth_user, cache_get_json, revoked_token_cache_key,
    token_cache_key, user_cache_key,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models import Rol, Usuario

security = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]
USER_TTL = settings.valkey_auth_ttl_seconds


def _is_revoked(token: str) -> bool:
    return bool(cache_get_json(revoked_token_cache_key(token)))


def _valid_account(user: Usuario) -> bool:
    return (user.is_enabled is True and user.account_non_expired is not False
            and user.account_non_locked is not False and user.credentials_non_expired is not False)


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
    token_expires = max(1, int(payload["exp"] - time.time()))

    cached_session = cache_get_json(token_cache_key(token))
    if cached_session and int(cached_session.get("usuario_id", -1)) != user_id:
        raise HTTPException(401, "Sesión inválida")
    cached = cache_get_json(user_cache_key(user_id))
    if cached and isinstance(cached.get("usuario"), dict):
        user = Usuario(**cached["usuario"])
        user._cached_role = cached.get("rol", "")
        if not _valid_account(user):
            raise HTTPException(401, "Usuario no autorizado o cuenta pendiente de activación")
        if cached_session is None:
            cache_auth_token(token, user_id, str(user._cached_role), token_expires)
        return user

    user = db.get(Usuario, user_id)
    if not user or not _valid_account(user):
        raise HTTPException(401, "Usuario no autorizado o cuenta pendiente de activación")
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    role_name = str(role.rol) if role and role.rol else ""
    cache_auth_user(user, role_name, USER_TTL)
    if cached_session is None:
        cache_auth_token(token, user_id, role_name, token_expires)
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

provider_user = require_roles("PROVEEDOR")


# --------------------------------------------------------------------------- API de predicciones
# Dos mecanismos de autenticación para clientes externos:
#   * JWT (Authorization: Bearer) de un usuario con rol permitido (PREDICTION_ALLOWED_ROLES, por defecto ADMIN).
#   * API Key de servicio (cabecera X-API-Key) emitida por un ADMIN, con permisos acotados.
# Entrenar modelos y gestionar API Keys exige SIEMPRE un JWT de ADMIN (las API Keys no sirven).
api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, scheme_name="ApiKeyAuth",
    description="Credencial de servicio para integraciones entre sistemas (Spring Boot, Node.js, etc.)")

def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None

def prediction_access(scope: str, admin_only: bool = False):
    """Dependencia de autorización + registro de accesos para /api/v1/predictions."""
    def checker(
        request: Request,
        db: DB,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
        api_key: Annotated[str | None, Depends(api_key_header)],
    ) -> dict:
        from app.prediction import repository

        def log(channel: str, requester: str | None, result: str) -> None:
            if settings.prediction_access_log_enabled:
                repository.record_access(db, request.method, request.url.path, channel, requester,
                                         _client_ip(request), result)

        if credentials:
            user = current_user(credentials, db)
            role = user_role(user, db)
            allowed = {"ADMIN"} if admin_only else settings.prediction_roles
            if role not in allowed:
                log("JWT", user.correo, "DENEGADO")
                raise HTTPException(403, "No tienes permisos para este recurso")
            log("JWT", user.correo, "PERMITIDO")
            return {"channel": "JWT", "name": user.correo, "user_id": int(user.usuario_id), "role": role}
        if api_key:
            if admin_only:
                log("API_KEY", None, "DENEGADO")
                raise HTTPException(403, "Esta operación requiere un JWT de administrador; las API Keys no están autorizadas")
            try:
                client = repository.verify_api_key(db, api_key)
            except repository.HistoryUnavailableError:
                client = None
            if client is None:
                log("API_KEY", api_key[:12], "DENEGADO")
                raise HTTPException(401, "API Key inválida o revocada", headers={"WWW-Authenticate": "ApiKey"})
            scopes = {s for s in client.permisos.split(",") if s}
            if scope not in scopes:
                log("API_KEY", client.nombre, "DENEGADO")
                raise HTTPException(403, f"La API Key no tiene el permiso '{scope}'")
            log("API_KEY", client.nombre, "PERMITIDO")
            return {"channel": "API_KEY", "name": f"api:{client.nombre}", "client_id": int(client.cliente_id),
                    "scopes": sorted(scopes)}
        raise HTTPException(401, "Se requiere Authorization: Bearer <JWT> o X-API-Key",
                            headers={"WWW-Authenticate": "Bearer"})
    return checker


# --------------------------------------------------------------------------- administración
ADMIN_EMAIL_HEADER = "X-Admin-Email"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def admin_user(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> Usuario:
    """Usuario ADMIN que hace la petición. Dos formas de autenticarse:

    * ``Authorization: Bearer <JWT>`` de un usuario con rol ADMIN (Swagger, Flutter, etc.).
    * Servicio a servicio (Spring Boot): ``X-API-Key`` con permiso ``admin:read`` (lecturas) o
      ``admin:write`` (lecturas y escrituras) **más** ``X-Admin-Email`` con el correo del administrador
      que inició sesión en Spring. Se verifica que ese correo sea un ADMIN activo, de modo que la clave
      por sí sola no basta para actuar, y cada acceso queda registrado con clave y administrador.
    """
    if credentials:
        user = current_user(credentials, db)
        if user_role(user, db) != "ADMIN":
            raise HTTPException(403, "No tienes permisos para este recurso")
        return user
    if not api_key:
        raise HTTPException(401, "Se requiere Authorization: Bearer <JWT> o X-API-Key",
                            headers={"WWW-Authenticate": "Bearer"})

    from app.prediction import repository

    def log(requester: str | None, result: str) -> None:
        if settings.prediction_access_log_enabled:
            repository.record_access(db, request.method, request.url.path, "API_KEY", requester,
                                     _client_ip(request), result)

    try:
        client = repository.verify_api_key(db, api_key)
    except repository.HistoryUnavailableError:
        client = None
    if client is None:
        log(api_key[:12], "DENEGADO")
        raise HTTPException(401, "API Key inválida o revocada", headers={"WWW-Authenticate": "ApiKey"})

    scopes = {s for s in (client.permisos or "").split(",") if s}
    needed = repository.SCOPE_ADMIN_READ if request.method in _SAFE_METHODS else repository.SCOPE_ADMIN_WRITE
    if needed not in scopes and repository.SCOPE_ADMIN_WRITE not in scopes:
        log(f"api:{client.nombre}", "DENEGADO")
        raise HTTPException(403, f"La API Key no tiene el permiso '{needed}'")

    email = (request.headers.get(ADMIN_EMAIL_HEADER) or "").strip()
    if not email:
        log(f"api:{client.nombre}", "DENEGADO")
        raise HTTPException(401, f"Falta la cabecera {ADMIN_EMAIL_HEADER} con el administrador que actúa")
    user = db.scalar(select(Usuario).where(func.lower(Usuario.correo) == email.lower()))
    if user is None or not _valid_account(user) or user_role(user, db) != "ADMIN":
        log(f"api:{client.nombre}->{email[:100]}", "DENEGADO")
        raise HTTPException(403, "El usuario indicado en X-Admin-Email no es un administrador activo")
    log(f"api:{client.nombre}->{user.correo}", "PERMITIDO")
    return user