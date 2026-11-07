"""Contratos JSON de Passkeys (WebAuthn) entre FastAPI y la app Flutter.

Los objetos ``options`` y ``credential`` siguen el formato JSON estándar de WebAuthn Level 3
(``PublicKeyCredentialCreationOptionsJSON``, ``RegistrationResponseJSON``, etc.), con todos los
binarios codificados en base64url sin relleno. Es exactamente lo que producen ``options_to_json`` de
py_webauthn y ``toJson()`` del paquete ``passkeys`` de Flutter.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CREATION_OPTIONS_EXAMPLE = {
    "rp": {"name": "Costa de Oro Imports", "id": "costadeoroimports.com"},
    "user": {"id": "q2VZbXkx...base64url", "name": "ana@example.com", "displayName": "Ana Prueba"},
    "challenge": "rNw4m2pW...base64url-32-bytes",
    "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -257}],
    "timeout": 120000,
    "excludeCredentials": [{"id": "AbCd...base64url", "type": "public-key", "transports": ["internal"]}],
    "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True,
                               "userVerification": "required"},
    "attestation": "none",
}
REQUEST_OPTIONS_EXAMPLE = {
    "rpId": "costadeoroimports.com",
    "challenge": "Zk9pQ3Vs...base64url-32-bytes",
    "timeout": 120000,
    "allowCredentials": [],
    "userVerification": "required",
}
REGISTRATION_CREDENTIAL_EXAMPLE = {
    "id": "AbCd...base64url", "rawId": "AbCd...base64url", "type": "public-key",
    "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uY3JlYXRlIi4uLn0",
                 "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10oGhhdXRoRGF0YVi...",
                 "transports": ["internal", "hybrid"]},
    "clientExtensionResults": {}, "authenticatorAttachment": "platform",
}
AUTHENTICATION_CREDENTIAL_EXAMPLE = {
    "id": "AbCd...base64url", "rawId": "AbCd...base64url", "type": "public-key",
    "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uZ2V0Ii4uLn0",
                 "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_krrmihjLHmVzzuoMdl2MFAAAAAQ",
                 "signature": "MEUCIQ...base64url", "userHandle": "q2VZbXkx...base64url"},
    "clientExtensionResults": {}, "authenticatorAttachment": "platform",
}


class RegisterStartRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"device_name": "iOS"}})
    device_name: str | None = Field(None, max_length=60, description="Nombre del dispositivo (iOS, Android…)")


class LoginStartRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{}, {"correo": "ana@example.com"}]})
    correo: str | None = Field(
        None, max_length=100,
        description="Opcional. Flutter envía {} (passkeys descubribles). Si se envía, se limita "
                    "allowCredentials a las passkeys de esa cuenta; un correo desconocido produce la misma "
                    "respuesta para no revelar qué cuentas existen.")


class ChallengeResponse(BaseModel):
    """Respuesta de register/start y login/start. Flutter lee ``challenge_id`` y ``options``."""
    challenge_id: str = Field(description="Identificador opaco del challenge; reenviarlo en /finish")
    options: dict[str, Any] = Field(description="PublicKeyCredential{Creation|Request}OptionsJSON de WebAuthn")
    expires_in: int = Field(description="Segundos de validez del challenge (un solo uso)")


class RegisterFinishRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "challenge_id": "3f6c1b7e2a9d4c0f8e1a5b2c7d9e0f11", "credential": REGISTRATION_CREDENTIAL_EXAMPLE,
        "device_name": "iOS"}})
    challenge_id: str = Field(min_length=8, max_length=64)
    credential: dict[str, Any] = Field(description="RegistrationResponseJSON devuelto por el autenticador")
    device_name: str | None = Field(None, max_length=60)


class LoginFinishRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "challenge_id": "9a1d3c5e7f2b4a6c8e0d1f3b5a7c9e11", "credential": AUTHENTICATION_CREDENTIAL_EXAMPLE}})
    challenge_id: str = Field(min_length=8, max_length=64)
    credential: dict[str, Any] = Field(description="AuthenticationResponseJSON (assertion) del autenticador")


class PasskeyInfo(BaseModel):
    passkey_id: int
    credential_id: str
    device_name: str | None
    device_type: str | None
    backed_up: bool
    created_at: str | None
    last_used_at: str | None


class RegisterFinishResponse(BaseModel):
    success: bool = True
    message: str
    passkey: PasskeyInfo


class SessionUser(BaseModel):
    """Mismo objeto ``usuario`` que devuelve /auth/login (lo lee UserModel.fromJson en Flutter)."""
    usuario_id: int
    correo: str
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    rol: str


class LoginFinishResponse(BaseModel):
    """Igual que /auth/login para que Flutter reutilice ``_authenticate``."""
    model_config = ConfigDict(json_schema_extra={"example": {
        "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "token_type": "bearer", "expires_in": 3600,
        "auth_method": "passkey",
        "usuario": {"usuario_id": 10, "correo": "ana@example.com", "nombres": "Ana", "apellidos": "Prueba",
                    "telefono": "3005550000", "rol": "PERSONA_NATURAL"}}})
    accessToken: str
    token_type: str = "bearer"
    expires_in: int
    auth_method: str = "passkey"
    usuario: SessionUser


class SessionValidateResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "valid": True, "usuario_id": 10, "rol": "PERSONA_NATURAL", "auth_method": "passkey", "expires_in": 3412}})
    valid: bool
    usuario_id: int
    rol: str | None = None
    auth_method: str | None = Field(None, description="passkey | password | null si se desconoce")
    expires_in: int | None = Field(None, description="Segundos restantes de la sesión en Valkey")
