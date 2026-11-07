"""Ceremonias WebAuthn (registro y autenticación) y sesiones de Passkeys.

Controles de seguridad:
* Challenge aleatorio de 32 bytes, un solo uso, con TTL, ligado al usuario en el registro.
* ``expected_rp_id`` (rpIdHash) y ``expected_origin`` (https://<rp_id> y android:apk-key-hash:...).
* Verificación de usuario obligatoria (biometría/PIN) y passkeys descubribles (residentKey=required).
* ``sign_count`` comparado con el último conocido para detectar autenticadores clonados.
* ``userHandle`` de la aserción comparado con el de la credencial.
* Login sin correo (no revela qué cuentas existen) y rate limit por IP en Valkey.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options, generate_registration_options, options_to_json,
    verify_authentication_response, verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, generate_user_handle
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference, AuthenticatorSelectionCriteria, AuthenticatorTransport,
    PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement,
)

from app.core import cache
from app.core.config import settings
from app.core.security import create_token
from app.models import Rol, Usuario
from app.services.passkey_store import (
    DuplicateCredentialError, PasskeyStore, SignCountConflictError, passkey_store,
)

logger = logging.getLogger(__name__)
SUPPORTED_ALGORITHMS = [COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256]
EXPIRED_MESSAGE = "La solicitud de passkey expiró o ya se usó. Intenta de nuevo."
RATE_LIMIT_PER_MINUTE = 30


@dataclass
class PasskeyError(Exception):
    status_code: int
    message: str


def _b64(data: bytes) -> str:
    return bytes_to_base64url(data)


def _canonical_id(value: Any) -> str:
    """Normaliza un credential id base64url (con o sin relleno) a su forma canónica."""
    if not isinstance(value, str) or not value or len(value) > 1400:
        raise PasskeyError(400, "Credencial de passkey inválida.")
    try:
        return _b64(base64url_to_bytes(value))
    except Exception as exc:  # noqa: BLE001
        raise PasskeyError(400, "Credencial de passkey inválida.") from exc


def _transports(values: list[str] | None) -> list[AuthenticatorTransport]:
    result = []
    for value in values or []:
        try:
            result.append(AuthenticatorTransport(value))
        except ValueError:
            continue
    return result


def _user_active(user: Usuario) -> bool:
    return (user.is_enabled is True and user.account_non_locked is not False
            and user.account_non_expired is not False and user.credentials_non_expired is not False)


def ensure_enabled() -> None:
    if not settings.passkey_rp_id.strip():
        raise PasskeyError(503, "El inicio de sesión con passkey no está configurado en el servidor.")


def check_rate_limit(scope: str, client_ip: str | None) -> None:
    """Máximo RATE_LIMIT_PER_MINUTE peticiones por IP y minuto (sólo si Valkey responde)."""
    client = cache.get_cache_client()
    if client is None or not client_ip:
        return
    key = f"passkey:rate:{scope}:{client_ip}:{int(datetime.now(timezone.utc).timestamp() // 60)}"
    try:
        count = client.incr(key)
        if count == 1:
            client.expire(key, 61)
    except Exception:  # noqa: BLE001
        logger.warning("Valkey no disponible para el rate limit de passkeys", exc_info=True)
        return
    if count > RATE_LIMIT_PER_MINUTE:
        raise PasskeyError(429, "Demasiados intentos. Espera un minuto e intenta de nuevo.")


class PasskeyService:
    def __init__(self, store: PasskeyStore = passkey_store) -> None:
        self.store = store

    # ------------------------------------------------------------------ registro
    def start_registration(self, db: Session, user: Usuario, device_name: str | None) -> dict[str, Any]:
        ensure_enabled()
        info = self.store.get_user_credentials(db, int(user.usuario_id))
        # Identificador opaco y estable del usuario para WebAuthn (no el ID de la BD ni el correo).
        user_handle = info.get("user_handle") or _b64(generate_user_handle())
        display_name = " ".join(p for p in (user.nombres, user.apellidos) if p).strip() or user.correo
        options = generate_registration_options(
            rp_id=settings.passkey_rp_id, rp_name=settings.passkey_rp_name,
            user_id=base64url_to_bytes(user_handle), user_name=user.correo, user_display_name=display_name,
            timeout=settings.passkey_ceremony_timeout_ms,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]),
                                              transports=_transports(c.get("transports")) or None)
                for c in info.get("credentials", [])],
            supported_pub_key_algs=SUPPORTED_ALGORITHMS,
        )
        challenge_id, ttl = self.store.save_challenge(db, "registro", {
            "challenge": _b64(options.challenge), "usuario_id": int(user.usuario_id),
            "user_handle": user_handle, "device_name": (device_name or "")[:60] or None,
        })
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options)), "expires_in": ttl}

    def finish_registration(self, db: Session, user: Usuario, challenge_id: str, credential: dict,
                            device_name: str | None) -> dict[str, Any]:
        ensure_enabled()
        record = self.store.consume_challenge(db, challenge_id, "registro")
        if record is None or int(record.get("usuario_id", -1)) != int(user.usuario_id):
            raise PasskeyError(401, EXPIRED_MESSAGE)
        try:
            verified = verify_registration_response(
                credential=credential, expected_challenge=base64url_to_bytes(record["challenge"]),
                expected_rp_id=settings.passkey_rp_id, expected_origin=settings.passkey_origins,
                require_user_verification=True, supported_pub_key_algs=SUPPORTED_ALGORITHMS,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            logger.info("Registro de passkey rechazado para usuario %s: %s", user.usuario_id, exc)
            raise PasskeyError(400, "No se pudo verificar la passkey.") from exc
        response = credential.get("response") if isinstance(credential.get("response"), dict) else {}
        transports = [t for t in (response.get("transports") or []) if isinstance(t, str)][:6]
        try:
            saved = self.store.save_credential(
                db, usuario_id=int(user.usuario_id), credential_id=_b64(verified.credential_id),
                public_key=_b64(verified.credential_public_key), user_handle=record["user_handle"],
                sign_count=int(verified.sign_count), transports=json.dumps(transports) if transports else None,
                aaguid=str(verified.aaguid) if verified.aaguid else None,
                device_type=getattr(verified.credential_device_type, "value", None),
                backed_up=bool(verified.credential_backed_up),
                device_name=((device_name or record.get("device_name") or "")[:60] or None),
            )
        except DuplicateCredentialError as exc:
            raise PasskeyError(409, "Esta passkey ya está registrada.") from exc
        logger.info("Passkey registrada: usuario=%s passkey_id=%s", user.usuario_id, saved["passkey_id"])
        return {"success": True, "message": "Passkey registrada correctamente", "passkey": public_info(saved)}

    # ------------------------------------------------------------------ autenticación
    def _user_id_for_email(self, db: Session, correo: str) -> int | None:
        """Valkey primero (índice de credenciales del login con contraseña) y luego MySQL."""
        email = correo.strip().lower()
        cached = cache.cache_get_json(cache.credential_cache_key(email))
        if isinstance(cached, dict) and cached.get("usuario_id") is not None:
            return int(cached["usuario_id"])
        return db.scalar(select(Usuario.usuario_id).where(Usuario.correo == email))

    def start_authentication(self, db: Session, correo: str | None = None) -> dict[str, Any]:
        ensure_enabled()
        allowed: list[dict] = []
        if correo:
            user_id = self._user_id_for_email(db, correo)
            if user_id is not None:
                allowed = self.store.get_user_credentials(db, int(user_id)).get("credentials", [])
        options = generate_authentication_options(
            rp_id=settings.passkey_rp_id, timeout=settings.passkey_ceremony_timeout_ms,
            user_verification=UserVerificationRequirement.REQUIRED,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]),
                                              transports=_transports(c.get("transports")) or None)
                for c in allowed],
        )
        challenge_id, ttl = self.store.save_challenge(db, "login", {
            "challenge": _b64(options.challenge),
            "allowed": [c["credential_id"] for c in allowed] if correo else None,
        })
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options)), "expires_in": ttl}

    def finish_authentication(self, db: Session, challenge_id: str, credential: dict) -> dict[str, Any]:
        ensure_enabled()
        record = self.store.consume_challenge(db, challenge_id, "login")
        if record is None:
            raise PasskeyError(401, EXPIRED_MESSAGE)
        credential_id = _canonical_id(credential.get("rawId") or credential.get("id"))
        if record.get("allowed") is not None and credential_id not in record["allowed"]:
            raise PasskeyError(401, "Passkey inválida.")
        stored = self.store.get_credential(db, credential_id)
        if stored is None:
            raise PasskeyError(401, "Esta passkey ya no es válida. Inicia sesión con tu contraseña.")
        response = credential.get("response") if isinstance(credential.get("response"), dict) else {}
        handle = response.get("userHandle")
        if handle and _canonical_id(handle) != stored["user_handle"]:
            raise PasskeyError(401, "Passkey inválida.")
        user = db.get(Usuario, stored["usuario_id"])
        if user is None:
            raise PasskeyError(401, "Esta passkey ya no es válida. Inicia sesión con tu contraseña.")
        if not _user_active(user):
            raise PasskeyError(403, "Cuenta deshabilitada, bloqueada o pendiente de aprobación")
        role = db.get(Rol, user.rol_id) if user.rol_id else None
        role_name = str(role.rol) if role and role.rol else ""
        if not role_name:
            raise PasskeyError(403, "La cuenta no tiene un rol válido asignado")
        try:
            verified = verify_authentication_response(
                credential=credential, expected_challenge=base64url_to_bytes(record["challenge"]),
                expected_rp_id=settings.passkey_rp_id, expected_origin=settings.passkey_origins,
                credential_public_key=base64url_to_bytes(stored["public_key"]),
                credential_current_sign_count=int(stored["sign_count"]),
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            logger.warning("Passkey rechazada: usuario=%s passkey_id=%s motivo=%s",
                           user.usuario_id, stored["passkey_id"], exc)
            raise PasskeyError(401, "Passkey inválida.") from exc
        try:
            self.store.record_usage(db, stored, int(verified.new_sign_count))
        except SignCountConflictError as exc:
            raise PasskeyError(401, "La passkey se usó en paralelo. Intenta de nuevo.") from exc
        logger.info("Login con passkey: usuario=%s passkey_id=%s", user.usuario_id, stored["passkey_id"])
        return issue_passkey_session(user, role_name, credential_id)


def public_info(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in (
        "passkey_id", "credential_id", "device_name", "device_type", "backed_up", "created_at", "last_used_at")}


def issue_passkey_session(user: Usuario, role_name: str, credential_id: str) -> dict[str, Any]:
    """JWT con el mismo formato de /auth/login + registro de sesión en Valkey con TTL."""
    from app.api.v1.endpoints.auth import _user_data  # import diferido: evita ciclo con el router

    ttl = settings.passkey_session_ttl_seconds
    token = create_token(str(user.usuario_id), role_name, ttl_seconds=ttl,
                         extra_claims={"amr": ["pop", "user"], "auth_method": "passkey"})
    stored = cache.cache_set_json(cache.token_cache_key(token), {
        "usuario_id": int(user.usuario_id), "rol": role_name, "auth_method": "passkey",
        "credential_id": credential_id, "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ttl)
    if not stored:
        logger.warning("Valkey no disponible: la sesión de passkey no podrá validarse en /session/validate")
    cache.cache_auth_user(user, role_name)
    return {"accessToken": token, "token_type": "bearer", "expires_in": ttl, "auth_method": "passkey",
            "usuario": _user_data(user, role_name)}


def validate_session(token: str) -> dict[str, Any]:
    """Valida el token sólo contra Valkey (sin MySQL ni verificación criptográfica)."""
    if cache.get_cache_client() is None:
        raise PasskeyError(503, "El almacén de sesiones (Valkey) no está disponible")
    if cache.cache_get_json(cache.revoked_token_cache_key(token)):
        raise PasskeyError(401, "Sesión revocada")
    session = cache.cache_get_json(cache.token_cache_key(token))
    if not isinstance(session, dict) or session.get("usuario_id") is None:
        raise PasskeyError(401, "Sesión inválida o expirada")
    return {"valid": True, "usuario_id": int(session["usuario_id"]), "rol": session.get("rol"),
            "auth_method": session.get("auth_method"), "expires_in": cache.cache_ttl(cache.token_cache_key(token))}


passkey_service = PasskeyService()
