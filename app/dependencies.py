from typing import Annotated
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models import Usuario, Rol
security=HTTPBearer(auto_error=False)
DB=Annotated[Session,Depends(get_db)]
def current_user(credentials: Annotated[HTTPAuthorizationCredentials|None,Depends(security)], db: DB) -> Usuario:
    if not credentials: raise HTTPException(401,"Token requerido",headers={"WWW-Authenticate":"Bearer"})
    try:
        payload=decode_token(credentials.credentials)
        user=db.get(Usuario,int(payload["sub"]))
    except (jwt.PyJWTError,ValueError,KeyError):
        raise HTTPException(401,"Token inválido o expirado")
    if not user or user.is_enabled is False or user.account_non_locked is False:
        raise HTTPException(401,"Usuario no autorizado")
    return user
def admin_user(user: Annotated[Usuario,Depends(current_user)], db: DB) -> Usuario:
    role=db.get(Rol,user.rol_id) if user.rol_id else None
    if not role or role.rol != "ADMIN": raise HTTPException(403,"Se requiere rol ADMIN")
    return user
