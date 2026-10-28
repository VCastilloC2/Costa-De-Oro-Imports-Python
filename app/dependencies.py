from typing import Annotated
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models import Usuario, Rol

security = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)], db: DB) -> Usuario:
    if not credentials:
        raise HTTPException(401, "Token requerido", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(credentials.credentials)
        user = db.get(Usuario, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Token inválido o expirado")
    if not user or user.is_enabled is not True or user.account_non_expired is False or user.account_non_locked is False or user.credentials_non_expired is False:
        raise HTTPException(401, "Usuario no autorizado o cuenta pendiente de activación")
    # No confiar únicamente en el rol del JWT: consultar el rol actual de la BD.
    return user


def user_role(user: Usuario, db: Session) -> str:
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
