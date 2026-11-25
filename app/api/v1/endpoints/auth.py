"""Password and OAuth authentication endpoints."""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
import hmac
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, security
from app.core.cache import (
    cache_auth_credentials, cache_auth_user, cache_delete, cache_get_json, cache_set_json,
    cache_pop_json, cache_set_json_if_absent, cache_ttl, credential_cache_key, revoke_token, token_cache_key, user_cache_key,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_token, hash_password, verify_password, is_bcrypt_hash
from app.models import BiometricCredential, Empresa, Rol, Usuario
from app.schemas import LoginRequest, OAuthLoginRequest, RegisterRequest, UserResponse
from app.services.email_service import gmail_is_configured, send_login_notice, send_password_reset, send_welcome

router = APIRouter(tags=["Autenticación"])
logger = logging.getLogger(__name__)

RESET_CODE_TTL = 600
RESET_RESEND_TTL = 60
DEFAULT_USER_IMAGE = "gestion-ventas/perfil-usuario/perfil-user"


class PasswordResetRequest(BaseModel):
    correo: EmailStr


class PasswordResetVerifyRequest(PasswordResetRequest):
    codigo: str = Field(pattern=r"^\d{5}$")


class PasswordResetCompleteRequest(PasswordResetVerifyRequest):
    nueva_contrasena: str = Field(min_length=5, max_length=128)


class BiometricRegisterRequest(BaseModel):
    device_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-fA-F0-9]+$")
    device_secret: str = Field(min_length=32, max_length=128)
    device_name: str | None = Field(None, max_length=60)


class BiometricLoginRequest(BiometricRegisterRequest):
    correo: EmailStr


def _reset_email_key(correo: str) -> str:
    digest = hashlib.sha256(correo.strip().lower().encode("utf-8")).hexdigest()
    return f"auth:password-reset:{digest}"


def _email_already_registered(db: Session, correo: str) -> bool:
    """Check the normalized email in Valkey and authoritative MySQL storage."""
    email = correo.strip().lower()
    if cache_get_json(credential_cache_key(email)):
        return True
    return db.scalar(select(Usuario.usuario_id).where(Usuario.correo == email)) is not None


def _reset_code_hash(correo: str, codigo: str) -> str:
    key = (settings.jwt_secret_ecommerce or "").encode("utf-8")
    return hmac.new(key, f"{correo.strip().lower()}:{codigo}".encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_reset_code() -> str:
    return f"{secrets.randbelow(100000):05d}"


def _valid_reset_code(correo: str, codigo: str) -> bool:
    key = _reset_email_key(correo)
    stored = cache_get_json(key)
    valid = bool(stored) and secrets.compare_digest(
        str(stored.get("hash", "")), _reset_code_hash(correo, codigo)
    )
    if not valid and stored:
        attempts = int(stored.get("attempts", 0)) + 1
        if attempts >= 5:
            cache_delete(key)
        else:
            cache_set_json(key, {**stored, "attempts": attempts}, cache_ttl(key) or 1)
    return valid


@router.post("/auth/password/forgot")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Envía un código de cinco dígitos; la respuesta no revela si existe el correo."""
    correo = str(payload.correo).strip().lower()
    ip = request.client.host if request.client else "unknown"
    ip_key = "auth:password-reset:ip:" + hashlib.sha256(ip.encode("utf-8")).hexdigest()
    if not cache_set_json_if_absent(ip_key, True, RESET_RESEND_TTL):
        raise HTTPException(429, "Espera un minuto antes de solicitar otra recuperación")
    resend_key = f"{_reset_email_key(correo)}:resend"
    if not cache_set_json_if_absent(resend_key, True, RESET_RESEND_TTL):
        raise HTTPException(429, "Espera un minuto antes de solicitar otra recuperación")
    if not (settings.valkey_url and gmail_is_configured()):
        cache_delete(resend_key)
        raise HTTPException(503, "El servicio de recuperación no está configurado")
    user = db.scalar(select(Usuario).where(Usuario.correo == correo))
    if not user or not _user_active(user):
        return {"mensaje": "Si el correo está registrado, recibirás un código de recuperación."}
    codigo = _generate_reset_code()
    if not cache_set_json(_reset_email_key(correo), {"hash": _reset_code_hash(correo, codigo), "attempts": 0}, RESET_CODE_TTL):
        cache_delete(resend_key)
        logger.error("No fue posible almacenar el código de recuperación")
        raise HTTPException(503, "No fue posible preparar la recuperación. Inténtalo de nuevo más tarde.")
    try:
        send_password_reset(correo, user.nombres or "", codigo)
    except Exception:
        cache_delete(_reset_email_key(correo))
        cache_delete(resend_key)
        logger.exception("No fue posible enviar el código de recuperación")
        raise HTTPException(502, "No fue posible enviar el correo de recuperación. Inténtalo de nuevo más tarde.")
    return {"mensaje": "Si el correo está registrado, recibirás un código de recuperación."}


@router.post("/auth/password/verify")
def verify_password_reset_code(payload: PasswordResetVerifyRequest) -> dict:
    correo = str(payload.correo).strip().lower()
    if not _valid_reset_code(correo, payload.codigo):
        raise HTTPException(400, "El código es inválido o venció")
    return {"valido": True}


@router.post("/auth/password/reset")
def complete_password_reset(payload: PasswordResetCompleteRequest, db: Session = Depends(get_db)) -> dict:
    correo = str(payload.correo).strip().lower()
    key = _reset_email_key(correo)
    if not _valid_reset_code(correo, payload.codigo):
        raise HTTPException(400, "El código es inválido o venció")
    user = db.scalar(select(Usuario).where(Usuario.correo == correo))
    if not user:
        cache_delete(key)
        raise HTTPException(400, "El código es inválido o venció")
    available, consumed = cache_pop_json(key)
    if not available or not isinstance(consumed, dict) or not secrets.compare_digest(str(consumed.get("hash", "")), _reset_code_hash(correo, payload.codigo)):
        raise HTTPException(400, "El código es inválido o venció")
    user.password = hash_password(payload.nueva_contrasena)
    db.commit()
    cache_delete(f"{key}:resend")
    cache_delete(credential_cache_key(correo))
    cache_auth_credentials(correo, user.usuario_id, user.password)
    cache_delete(user_cache_key(user.usuario_id))
    return {"mensaje": "La contraseña se restableció correctamente"}


def _user_active(user: Usuario) -> bool:
    return all((
        user.is_enabled is True,
        user.account_non_expired is True,
        user.account_non_locked is True,
        user.credentials_non_expired is True,
    ))


def _user_data(user: Usuario, role_name: str) -> dict:
    return {
        "usuario_id": user.usuario_id,
        "correo": user.correo,
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "telefono": user.telefono,
        "imagen": user.imagen,
        "rol": role_name,
    }


def _schedule_login_notice(background_tasks: BackgroundTasks, user: Usuario, request: Request) -> None:
    occurred_at = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M %Z")
    name = f"{user.nombres or ''} {user.apellidos or ''}".strip()
    background_tasks.add_task(send_login_notice, user.correo, name, occurred_at, request.headers.get("user-agent"), None)


def _issue_token(user: Usuario, role_name: str, cached_password_hash: str | None = None) -> dict:
    token = create_token(str(user.usuario_id), role_name)
    user_id = int(user.usuario_id)
    user_fields = (
        "usuario_id", "account_non_expired", "account_non_locked", "credentials_non_expired",
        "is_enabled", "empresa_id", "rol_id", "numero_identificacion", "telefono", "correo",
        "direccion", "apellidos", "nombres", "imagen", "tipo_identificacion",
    )
    user_snapshot = {field: getattr(user, field, None) for field in user_fields}
    cache_set_json(
        user_cache_key(user_id),
        {"usuario": user_snapshot, "rol": role_name},
        settings.valkey_auth_ttl_seconds,
    )
    password_hash = getattr(user, "password", None) or cached_password_hash
    if password_hash and is_bcrypt_hash(password_hash):
        cache_set_json(
            credential_cache_key(user.correo),
            {"usuario_id": user_id, "password_hash": password_hash},
            settings.valkey_auth_ttl_seconds,
        )
    cache_set_json(token_cache_key(token), {"usuario_id": user_id, "rol": role_name}, 3600)
    return {"accessToken": token, "token_type": "bearer", "expires_in": 3600, "usuario": _user_data(user, role_name)}


def _role(db: Session, role_name: str) -> Rol:
    role = db.scalar(select(Rol).where(Rol.rol == role_name))
    if not role:
        raise HTTPException(409, f"El rol {role_name} no existe en la base de datos")
    return role


@router.post("/auth/login")
def login(payload: LoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    email = str(payload.correo).lower().strip()
    cached_credentials = cache_get_json(credential_cache_key(email))
    user = None
    used_cached_credentials = False
    if cached_credentials and is_bcrypt_hash(cached_credentials.get("password_hash")):
        candidate_hash = cached_credentials["password_hash"]
        if verify_password(payload.password, candidate_hash):
            cached_user = cache_get_json(user_cache_key(int(cached_credentials["usuario_id"])))
            if cached_user and isinstance(cached_user.get("usuario"), dict):
                user = Usuario(**cached_user["usuario"])
                # The profile snapshot intentionally omits the password. Keep the
                # verified hash on this transient model so the common validation
                # below can validate both DB and cache backed users consistently.
                user.password = candidate_hash
                user._cached_role = cached_user.get("rol", "")
                used_cached_credentials = True
    if user is None:
        # A cache entry may outlive a password update (or belong to a damaged
        # cache). MySQL is authoritative; a stale cache must not lock out login.
        user = db.scalar(select(Usuario).where(Usuario.correo == email))
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(401, "Credenciales inválidas")
    if not _user_active(user):
        raise HTTPException(403, "Cuenta deshabilitada, bloqueada o pendiente de aprobación")
    cached_role = getattr(user, "_cached_role", None)
    if cached_role is not None:
        role_name = str(cached_role)
    else:
        role = db.get(Rol, user.rol_id) if user.rol_id else None
        role_name = str(role.rol) if role and role.rol else ""
    if not role_name:
        raise HTTPException(403, "La cuenta no tiene un rol válido asignado")
    if not used_cached_credentials and not is_bcrypt_hash(user.password):
        user.password = hash_password(payload.password)
        db.commit()
    _schedule_login_notice(background_tasks, user, request)
    return _issue_token(
        user,
        role_name,
        cached_credentials.get("password_hash") if used_cached_credentials and cached_credentials else None,
    )


def _biometric_key(user_id: int, device_id: str) -> str:
    return f"auth:biometric:{user_id}:{device_id}"


@router.post("/auth/biometric/register")
def register_biometric(payload: BiometricRegisterRequest, user: Usuario = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Vincula un secreto aleatorio del dispositivo tras una sesión autenticada. No recibe biometría."""
    digest = hashlib.sha256(payload.device_secret.encode()).hexdigest()
    record = db.scalar(select(BiometricCredential).where(
        BiometricCredential.usuario_id == user.usuario_id,
        BiometricCredential.device_id == payload.device_id,
    ))
    if record:
        record.secret_hash, record.device_name, record.active = digest, payload.device_name, True
    else:
        db.add(BiometricCredential(usuario_id=user.usuario_id, device_id=payload.device_id,
                                   secret_hash=digest, device_name=payload.device_name, active=True))
    db.commit()
    cache_set_json(_biometric_key(int(user.usuario_id), payload.device_id), {"secret_hash": digest}, 31536000)
    return {"success": True, "message": "Biometría del dispositivo vinculada"}


@router.get("/auth/biometric/devices")
def list_biometric_devices(user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    """Lista los dispositivos vinculados a la cuenta; nunca devuelve secretos biométricos."""
    rows = db.scalars(select(BiometricCredential).where(
        BiometricCredential.usuario_id == user.usuario_id,
        BiometricCredential.active.is_(True),
    ).order_by(BiometricCredential.created_at.desc())).all()
    return [{
        "credential_id": row.credential_id,
        "device_id": row.device_id,
        "device_name": row.device_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]


@router.delete("/auth/biometric/devices/{credential_id}")
def revoke_biometric_device(credential_id: int, user: Usuario = Depends(current_user),
                            db: Session = Depends(get_db)):
    """Revoca un dispositivo biométrico propio y elimina su secreto almacenado en caché."""
    row = db.scalar(select(BiometricCredential).where(
        BiometricCredential.credential_id == credential_id,
        BiometricCredential.usuario_id == user.usuario_id,
        BiometricCredential.active.is_(True),
    ))
    if row is None:
        raise HTTPException(404, "Dispositivo biométrico no encontrado")
    row.active = False
    db.commit()
    cache_delete(_biometric_key(int(user.usuario_id), row.device_id))
    return {"success": True, "message": "Dispositivo biométrico revocado", "credential_id": credential_id}


@router.post("/auth/biometric/login")
def login_biometric(payload: BiometricLoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    """Verifica el secreto del dispositivo (tras desbloqueo biométrico local) y crea sesión."""
    email = str(payload.correo).strip().lower()
    user = db.scalar(select(Usuario).where(Usuario.correo == email))
    if not user or not _user_active(user):
        raise HTTPException(401, "Credenciales biométricas inválidas")
    key = _biometric_key(int(user.usuario_id), payload.device_id)
    cached = cache_get_json(key)
    stored = cached.get("secret_hash") if isinstance(cached, dict) else None
    if not stored:
        credential = db.scalar(select(BiometricCredential).where(
            BiometricCredential.usuario_id == user.usuario_id,
            BiometricCredential.device_id == payload.device_id,
            BiometricCredential.active.is_(True),
        ))
        stored = credential.secret_hash if credential else None
    candidate = hashlib.sha256(payload.device_secret.encode()).hexdigest()
    if not stored or not hmac.compare_digest(str(stored), candidate):
        raise HTTPException(401, "Credenciales biométricas inválidas")
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    if not role or not role.rol:
        raise HTTPException(403, "La cuenta no tiene un rol válido asignado")
    cache_set_json(key, {"secret_hash": stored}, 31536000)
    _schedule_login_notice(background_tasks, user, request)
    return {**_issue_token(user, str(role.rol)), "auth_method": "device_biometric"}

@router.post("/auth/registro", status_code=201, response_model=UserResponse)
def register(payload: RegisterRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    email = str(payload.correo).lower().strip()
    if _email_already_registered(db, email):
        raise HTTPException(409, "El correo ya está registrado")
    role_name = (payload.rol or "PERSONA_NATURAL").upper()
    role = _role(db, role_name)
    user = Usuario(
        correo=email, password=hash_password(payload.password), nombres=payload.nombres,
        apellidos=payload.apellidos, telefono=payload.telefono, direccion=payload.direccion,
        tipo_identificacion=payload.tipo_identificacion, numero_identificacion=payload.numero_identificacion,
        imagen=DEFAULT_USER_IMAGE, rol_id=role.rol_id, is_enabled=True, account_non_expired=True,
        account_non_locked=True, credentials_non_expired=True,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(409, "No fue posible registrar el usuario; revisa correo, teléfono e identificación") from exc
    cache_auth_user(user, role_name)
    cache_auth_credentials(user.correo, int(user.usuario_id), user.password)
    company = db.get(Empresa, user.empresa_id) if user.empresa_id else None
    background_tasks.add_task(send_welcome, email, f"{user.nombres} {user.apellidos}".strip(), role_name, company.razon_social if company else None)
    return user

def _oauth_claims(provider: str, id_token: str) -> dict:
    provider = provider.lower()
    if provider == "google":
        issuer = ["accounts.google.com", "https://accounts.google.com"]
        client_ids = [item.strip() for item in (settings.google_allowed_client_ids or settings.google_client_id or "").split(",") if item.strip()]
        jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    elif provider == "apple":
        issuer = "https://appleid.apple.com"
        client_ids = [item.strip() for item in (settings.apple_allowed_client_ids or "").split(",") if item.strip()]
        jwks_url = "https://appleid.apple.com/auth/keys"
    else:
        raise HTTPException(404, "Proveedor OAuth no soportado")
    if not client_ids:
        raise HTTPException(503, f"No hay audiencia OAuth configurada para {provider}")
    try:
        jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, timeout=5)
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, signing_key.key, algorithms=["RS256"], audience=client_ids, issuer=issuer)
    except Exception as exc:
        if provider == "google":
            try:
                unverified = jwt.decode(id_token, options={"verify_signature": False, "verify_aud": False})
            except Exception:
                unverified = {}
            # Never log the bearer token or email; these claims help distinguish
            # wrong OAuth audience/issuer from expiration or JWKS network errors.
            logger.warning(
                "Google ID token rechazado (%s): aud=%s iss=%s exp=%s configured_audiences=%s",
                type(exc).__name__, unverified.get("aud"), unverified.get("iss"),
                unverified.get("exp"), client_ids,
            )
        raise HTTPException(401, "Token OAuth inválido o expirado") from exc
    verified = claims.get("email_verified")
    if verified not in (True, "true", "True", 1):
        raise HTTPException(401, "El proveedor no confirmó el correo")
    if not claims.get("email"):
        raise HTTPException(401, "El token OAuth no contiene un correo")
    return claims

@router.post("/auth/google")
def google_login(payload: OAuthLoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    return oauth_login("google", payload, db, background_tasks, request)

@router.post("/auth/apple")
def apple_login(payload: OAuthLoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    return oauth_login("apple", payload, db, background_tasks, request)


@router.post("/auth/apple/callback", include_in_schema=False)
async def apple_android_callback(request: Request):
    """Relay Apple's form POST back to sign_in_with_apple on Android.

    The app still validates the returned identity token against Apple before
    creating a session. The destination package is fixed by server config.
    """
    package_name = settings.apple_android_package_name.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+", package_name):
        raise HTTPException(503, "APPLE_ANDROID_PACKAGE_NAME no está configurado correctamente")

    body = (await request.body()).decode("utf-8", errors="replace")
    fields = parse_qsl(body, keep_blank_values=True)
    if not fields:
        raise HTTPException(400, "Apple no devolvió credenciales de autorización")

    callback_query = urlencode(fields)
    app_url = (
        f"intent://callback?{callback_query}"
        f"#Intent;package={package_name};scheme=signinwithapple;end"
    )
    return RedirectResponse(app_url, status_code=303)

def oauth_login(provider: str, payload: OAuthLoginRequest, db: Session, background_tasks: BackgroundTasks | None = None, request: Request | None = None) -> dict:
    claims = _oauth_claims(provider, payload.id_token)
    email = str(claims["email"]).lower().strip()
    if payload.correo and str(payload.correo).lower().strip() != email:
        raise HTTPException(422, "El correo del registro debe coincidir con el correo verificado por OAuth")
    user = db.scalar(select(Usuario).where(Usuario.correo == email))
    created = False
    if user is None:
        # The provider's verified identity supplies the account email. Profile
        # fields are optional because Apple/Google do not always return them.
        provider_name = str(claims.get("name") or "").strip()
        given_name = str(claims.get("given_name") or "").strip()
        family_name = str(claims.get("family_name") or "").strip()
        names = provider_name or " ".join(part for part in (given_name, family_name) if part)
        names = names or (payload.nombres or "").strip() or None
        surnames = (payload.apellidos or "").strip() or None
        if not surnames and given_name and family_name and not provider_name:
            names, surnames = given_name, family_name

        role = _role(db, "PERSONA_NATURAL")
        user = Usuario(
            correo=email,
            # Social-only users can set a password later through password recovery.
            password=hash_password(payload.password) if payload.password else None,
            nombres=names,
            apellidos=surnames,
            telefono=(payload.telefono or "").strip() or None,
            tipo_identificacion=payload.tipo_identificacion,
            numero_identificacion=(payload.numero_identificacion or "").strip() or None,
            imagen=DEFAULT_USER_IMAGE,
            rol_id=role.rol_id,
            is_enabled=True,
            account_non_expired=True,
            account_non_locked=True,
            credentials_non_expired=True,
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
            created = True
        except Exception as exc:
            db.rollback()
            # If two first-time OAuth requests race, use the account created by
            # the winning request instead of returning a duplicate-email error.
            user = db.scalar(select(Usuario).where(Usuario.correo == email))
            if user is None:
                raise HTTPException(409, "No fue posible registrar la cuenta social") from exc

    if not _user_active(user):
        raise HTTPException(403, "Cuenta deshabilitada, bloqueada o pendiente de aprobación")
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    if not role or not role.rol:
        raise HTTPException(403, "La cuenta no tiene un rol válido asignado")
    if background_tasks:
        if created:
            background_tasks.add_task(send_welcome, email, f"{user.nombres or ''} {user.apellidos or ''}".strip(), str(role.rol))
        if request:
            _schedule_login_notice(background_tasks, user, request)
    return _issue_token(user, str(role.rol))


@router.post("/auth/logout")
def logout(
    credentials=Depends(security),
):
    # Logout is idempotent: clients can clear a stale/expired session too.
    # A valid presented token is still revoked immediately when possible.
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, settings.jwt_secret_ecommerce, algorithms=["HS256"], options={"verify_signature": False})
            ttl = max(1, int(payload.get("exp", time.time() + 3600) - time.time()))
            revoke_token(credentials.credentials, ttl)
        except Exception:
            pass
    return {"success": True, "mensaje": "Sesión cerrada"}

@router.get("/auth/catalogos")
def catalogs():
    return {
        "tiposIdentificacion": ["CC", "CE", "DE", "NIT", "PP", "TE", "TI"],
        "sectores": ["BAR", "CAFE", "CATERING", "HOTEL", "NIGHTCLUB", "RESTAURANT"],
        "rolesRegistro": ["INVITADO", "PERSONA_CONTACTO", "PERSONA_JURIDICA", "PERSONA_NATURAL", "PROVEEDOR"],
        "nota": "Las cuentas creadas por registro público se activan automáticamente. ADMIN solo puede crearse desde la administración.",
    }
