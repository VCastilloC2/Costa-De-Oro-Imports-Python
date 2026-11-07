"""Passkeys (WebAuthn / FIDO2) y validación de sesiones.

Rutas principales (``/api/v1/auth/passkey/...``) y alias con los nombres que ya usa la app Flutter
(``/auth/passkey/.../options|verify``, ver docs/passkeys.md del repositorio Flutter). Ambas apuntan a
los mismos handlers y usan el mismo contrato JSON. Errores: ``{"detail": "mensaje"}`` como el resto
de /auth.
"""
from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import current_user, security
from app.core.database import get_db
from app.models import Usuario
from app.schemas.passkey import (
    ChallengeResponse, LoginFinishRequest, LoginFinishResponse, LoginStartRequest, PasskeyInfo,
    RegisterFinishRequest, RegisterFinishResponse, RegisterStartRequest, SessionValidateResponse,
)
from app.services.passkey_service import (
    PasskeyError, check_rate_limit, passkey_service, public_info, validate_session,
)
from app.services.passkey_store import passkey_store

TAG = "Passkeys (WebAuthn)"
router = APIRouter(tags=[TAG])

ERRORS = {
    400: {"description": "La respuesta del autenticador no pudo verificarse"},
    401: {"description": "Token ausente/expirado, challenge expirado o ya usado, o passkey inválida"},
    403: {"description": "Cuenta deshabilitada o sin rol"},
    409: {"description": "La passkey ya estaba registrada"},
    429: {"description": "Demasiados intentos desde la misma IP"},
    503: {"description": "Passkeys no configuradas (PASSKEY_RP_ID) o almacenamiento no disponible"},
}


def _run(action: Callable):
    try:
        return action()
    except PasskeyError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except RuntimeError as exc:
        raise HTTPException(503, "Servicio de passkeys no disponible temporalmente") from exc


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ------------------------------------------------------------------------- registro

def register_start(payload: RegisterStartRequest, user: Annotated[Usuario, Depends(current_user)],
                   db: Session = Depends(get_db)) -> dict:
    """**Paso 1 del registro** (requiere `Authorization: Bearer <JWT>`).

    Devuelve `{challenge_id, options, expires_in}`. Flutter pasa `options` tal cual a
    `PasskeyService.createCredential` (navigator.credentials.create). El challenge se guarda en
    Valkey con TTL (por defecto 300 s) y sólo puede usarse una vez.
    """
    return _run(lambda: passkey_service.start_registration(db, user, payload.device_name))


def register_finish(payload: RegisterFinishRequest, user: Annotated[Usuario, Depends(current_user)],
                    db: Session = Depends(get_db)) -> dict:
    """**Paso 2 del registro**: recibe el `RegistrationResponseJSON` firmado por el dispositivo.

    Verifica atestación, challenge, origen, rpIdHash y verificación de usuario con
    `verify_registration_response`, guarda la credencial en MySQL y la carga en Valkey.
    """
    return _run(lambda: passkey_service.finish_registration(
        db, user, payload.challenge_id, payload.credential, payload.device_name))


# ------------------------------------------------------------------------- login

def login_start(request: Request, payload: LoginStartRequest | None = None, db: Session = Depends(get_db)) -> dict:
    """**Paso 1 del login** (público). Flutter envía `{}`.

    Devuelve `{challenge_id, options, expires_in}` para `PasskeyService.getAssertion`
    (navigator.credentials.get). Sin correo, `allowCredentials` va vacío y el sistema operativo
    ofrece las passkeys descubribles del dispositivo.
    """
    def action():
        check_rate_limit("login", _ip(request))
        return passkey_service.start_authentication(db, payload.correo if payload else None)
    return _run(action)


def login_finish(payload: LoginFinishRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """**Paso 2 del login** (público): recibe la aserción (`AuthenticationResponseJSON`).

    Recupera la clave pública y el `sign_count` (Valkey, o MySQL si no está en caché), verifica con
    `verify_authentication_response`, actualiza el contador en ambas bases y emite la sesión.
    La respuesta es **igual a `/auth/login`** (`accessToken` + `usuario`), así Flutter reutiliza el
    mismo flujo de inicio de sesión. Un 401 hace que la app deje de lanzar la passkey sola.
    """
    def action():
        check_rate_limit("login", _ip(request))
        return passkey_service.finish_authentication(db, payload.challenge_id, payload.credential)
    return _run(action)


# ------------------------------------------------------------------------- rutas

ROUTES = [
    ("/register/start", "/register/options", register_start, ChallengeResponse,
     "Registro de passkey · paso 1: opciones de creación"),
    ("/register/finish", "/register/verify", register_finish, RegisterFinishResponse,
     "Registro de passkey · paso 2: verificar y guardar"),
    ("/login/start", "/login/options", login_start, ChallengeResponse,
     "Login con passkey · paso 1: opciones de autenticación"),
    ("/login/finish", "/login/verify", login_finish, LoginFinishResponse,
     "Login con passkey · paso 2: verificar y emitir sesión"),
]
for main_path, flutter_path, handler, model, summary in ROUTES:
    router.add_api_route(f"/api/v1/auth/passkey{main_path}", handler, methods=["POST"], response_model=model,
                         summary=summary, responses=ERRORS)
    router.add_api_route(f"/auth/passkey{flutter_path}", handler, methods=["POST"], response_model=model,
                         summary=f"{summary} (alias usado por Flutter)", responses=ERRORS)


@router.get("/api/v1/auth/session/validate", response_model=SessionValidateResponse,
            summary="Validar una sesión sólo contra Valkey",
            responses={401: {"description": "Sesión inexistente, expirada o revocada"},
                       503: {"description": "Valkey no disponible"}})
def session_validate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> dict:
    """Comprobación rápida: busca el registro de la sesión en Valkey (`auth:token:<sha256>`) sin tocar
    MySQL. Sirve para tokens emitidos por passkey y por `/auth/login`. Devuelve los segundos restantes."""
    if not credentials:
        raise HTTPException(401, "Token requerido", headers={"WWW-Authenticate": "Bearer"})
    return _run(lambda: validate_session(credentials.credentials))


@router.get("/api/v1/auth/passkey/credentials", response_model=list[PasskeyInfo],
            summary="Listar mis passkeys")
def list_my_passkeys(user: Annotated[Usuario, Depends(current_user)], db: Session = Depends(get_db)) -> list:
    """Passkeys activas del usuario autenticado (sin claves públicas)."""
    return [public_info(r) for r in passkey_store.list_user_credentials(db, int(user.usuario_id))]


@router.delete("/api/v1/auth/passkey/credentials/{passkey_id}", summary="Revocar una de mis passkeys")
def revoke_my_passkey(passkey_id: int, user: Annotated[Usuario, Depends(current_user)],
                      db: Session = Depends(get_db)) -> dict:
    """Desactiva la passkey en MySQL y la elimina de Valkey de inmediato."""
    if not passkey_store.revoke_user_credential(db, int(user.usuario_id), passkey_id):
        raise HTTPException(404, "Passkey no encontrada")
    return {"success": True, "message": "Passkey revocada", "passkey_id": passkey_id}
