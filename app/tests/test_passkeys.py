"""Flujo completo de Passkeys con un autenticador WebAuthn por software (firmas ECDSA P-256 reales)
y un Valkey en memoria. Verifica el contrato JSON que consume Flutter."""
import hashlib
import json
import os
import struct
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url as b64
from webauthn.helpers import encode_cbor

from app.core import cache
from app.core.config import settings
from app.core.security import create_token
from app.models import PasskeyChallenge, PasskeyCredencial, Usuario
from app.services import passkey_service as service_module

RP_ID = "costadeoroimports.com"
ORIGIN = f"https://{RP_ID}"
ANDROID_ORIGIN = "android:apk-key-hash:Q2FzdGlsbG9DMlRlc3RLZXlIYXNo"
REGISTER_START = "/api/v1/auth/passkey/register/start"
REGISTER_FINISH = "/api/v1/auth/passkey/register/finish"
LOGIN_START = "/api/v1/auth/passkey/login/start"
LOGIN_FINISH = "/api/v1/auth/passkey/login/finish"


class FakeValkey:
    """Subconjunto de la API de valkey-py usado por la aplicación."""

    def __init__(self):
        self.data, self.expires = {}, {}

    def _live(self, key):
        if key in self.expires and self.expires[key] <= time.monotonic():
            self.data.pop(key, None)
            self.expires.pop(key, None)
        return key in self.data

    def get(self, key):
        return self.data[key] if self._live(key) else None

    def set(self, key, value, ex=None):
        self.data[key] = value
        if ex:
            self.expires[key] = time.monotonic() + ex
        return True

    def getdel(self, key):
        value = self.get(key)
        self.data.pop(key, None)
        self.expires.pop(key, None)
        return value

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)
            self.expires.pop(key, None)

    def ttl(self, key):
        if not self._live(key):
            return -2
        return int(self.expires[key] - time.monotonic()) if key in self.expires else -1

    def incr(self, key):
        self.data[key] = str(int(self.get(key) or 0) + 1)
        return int(self.data[key])

    def expire(self, key, seconds):
        self.expires[key] = time.monotonic() + seconds

    def ping(self):
        return True


class SoftAuthenticator:
    """Autenticador de plataforma simulado (Face ID / huella)."""

    def __init__(self, origin=ORIGIN):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.sign_count = 0
        self.user_handle = None
        self.origin = origin

    def _cose_key(self):
        numbers = self.key.public_key().public_numbers()
        return encode_cbor({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _client_data(self, kind, challenge, origin=None):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin,
                           "crossOrigin": False}).encode()

    def create(self, options):
        self.user_handle = options["user"]["id"]
        client_data = self._client_data("webauthn.create", options["challenge"])
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x01 | 0x04 | 0x40])
                     + struct.pack(">I", self.sign_count) + b"\x00" * 16
                     + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key())
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(client_data), "attestationObject": b64(attestation),
                             "transports": ["internal", "hybrid"]},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}

    def get(self, options, increment=1, origin=None, user_handle=None):
        self.sign_count += increment
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = (hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x01 | 0x04])
                     + struct.pack(">I", self.sign_count))
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data),
                             "signature": b64(signature), "userHandle": user_handle or self.user_handle},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}


@pytest.fixture
def passkeys_on(monkeypatch):
    monkeypatch.setattr(settings, "passkey_rp_id", RP_ID)
    monkeypatch.setattr(settings, "passkey_expected_origins", f"{ORIGIN},{ANDROID_ORIGIN}")


@pytest.fixture
def valkey(monkeypatch):
    fake = FakeValkey()
    monkeypatch.setattr(cache, "get_cache_client", lambda: fake)
    return fake


@pytest.fixture
def user_headers(db_session, seeded_roles):
    db_session.add(Usuario(usuario_id=10, correo="ana@example.com", password="x", nombres="Ana",
                           apellidos="Prueba", rol_id=2, is_enabled=True, account_non_expired=True,
                           account_non_locked=True, credentials_non_expired=True))
    db_session.commit()
    return {"Authorization": f"Bearer {create_token('10', 'PERSONA_NATURAL')}"}


def _register(client, headers, authenticator, device="iOS"):
    start = client.post(REGISTER_START, headers=headers, json={"device_name": device})
    assert start.status_code == 200, start.text
    body = start.json()
    credential = authenticator.create(body["options"])
    return client.post(REGISTER_FINISH, headers=headers,
                       json={"challenge_id": body["challenge_id"], "credential": credential, "device_name": device})


def _login(client, authenticator, start_path=LOGIN_START, finish_path=LOGIN_FINISH, **kwargs):
    start = client.post(start_path, json={})
    assert start.status_code == 200, start.text
    body = start.json()
    assertion = authenticator.get(body["options"], **kwargs)
    return client.post(finish_path, json={"challenge_id": body["challenge_id"], "credential": assertion}), body


def test_full_flow_with_valkey_matches_flutter_contract(client, user_headers, passkeys_on, valkey, db_session):
    start = client.post(REGISTER_START, headers=user_headers, json={"device_name": "iOS"}).json()
    options = start["options"]
    assert set(start) == {"challenge_id", "options", "expires_in"} and start["expires_in"] == 300
    assert options["rp"]["id"] == RP_ID and options["user"]["name"] == "ana@example.com"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert {p["alg"] for p in options["pubKeyCredParams"]} == {-7, -257}
    assert f"passkey:challenge:{start['challenge_id']}" in valkey.data

    authenticator = SoftAuthenticator()
    credential = authenticator.create(options)
    finish = client.post(REGISTER_FINISH, headers=user_headers,
                         json={"challenge_id": start["challenge_id"], "credential": credential, "device_name": "iOS"})
    assert finish.status_code == 200, finish.text
    assert finish.json()["passkey"]["device_name"] == "iOS"
    row = db_session.scalar(select(PasskeyCredencial))
    assert row.usuario_id == 10 and row.sign_count == 0
    assert f"passkey:cred:{row.credential_id}" in valkey.data  # sincronizada en Valkey

    response, login_options = _login(client, authenticator)
    assert login_options["options"]["rpId"] == RP_ID and login_options["options"]["allowCredentials"] == []
    assert login_options["options"]["userVerification"] == "required"
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["auth_method"] == "passkey" and session["token_type"] == "bearer"
    assert session["usuario"]["correo"] == "ana@example.com" and session["usuario"]["rol"] == "PERSONA_NATURAL"

    db_session.refresh(row)
    assert row.sign_count == 1 and row.ultimo_uso is not None
    assert json.loads(valkey.data[f"passkey:cred:{row.credential_id}"])["sign_count"] == 1

    validate = client.get("/api/v1/auth/session/validate", headers={"Authorization": f"Bearer {session['accessToken']}"})
    assert validate.status_code == 200
    assert validate.json()["auth_method"] == "passkey" and validate.json()["expires_in"] > 0
    # El token de passkey funciona en el resto de la API (mismo JWT de /auth/login).
    assert client.get("/perfil", headers={"Authorization": f"Bearer {session['accessToken']}"}).status_code == 200


def test_flutter_alias_routes(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator(origin=ANDROID_ORIGIN)
    start = client.post("/auth/passkey/register/options", headers=user_headers, json={"device_name": "Android"}).json()
    credential = authenticator.create(start["options"])
    verify = client.post("/auth/passkey/register/verify", headers=user_headers,
                         json={"challenge_id": start["challenge_id"], "credential": credential, "device_name": "Android"})
    assert verify.status_code == 200, verify.text
    response, _ = _login(client, authenticator, "/auth/passkey/login/options", "/auth/passkey/login/verify")
    assert response.status_code == 200 and response.json()["accessToken"]


def test_challenge_is_single_use(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    start = client.post(LOGIN_START, json={}).json()
    payload = {"challenge_id": start["challenge_id"], "credential": authenticator.get(start["options"])}
    assert client.post(LOGIN_FINISH, json=payload).status_code == 200
    replay = client.post(LOGIN_FINISH, json=payload)
    assert replay.status_code == 401 and "expiró" in replay.json()["detail"]


def test_cache_miss_falls_back_to_mysql_and_repopulates(client, user_headers, passkeys_on, valkey, db_session):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    key = f"passkey:cred:{b64(authenticator.credential_id)}"
    valkey.delete(key)
    response, _ = _login(client, authenticator)
    assert response.status_code == 200
    assert key in valkey.data


def test_cloned_authenticator_is_rejected(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    assert _login(client, authenticator, increment=5)[0].status_code == 200
    authenticator.sign_count = 1  # un clon con contador atrasado
    assert _login(client, authenticator)[0].status_code == 401


def test_wrong_origin_and_user_handle_are_rejected(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    assert _login(client, authenticator, origin="https://phishing.example")[0].status_code == 401
    assert _login(client, authenticator, user_handle=b64(os.urandom(32)))[0].status_code == 401


def test_without_valkey_challenges_use_mysql(client, user_headers, passkeys_on, monkeypatch, db_session):
    monkeypatch.setattr(cache, "get_cache_client", lambda: None)
    authenticator = SoftAuthenticator()
    start = client.post(REGISTER_START, headers=user_headers, json={}).json()
    assert db_session.get(PasskeyChallenge, start["challenge_id"]) is not None
    finish = client.post(REGISTER_FINISH, headers=user_headers, json={
        "challenge_id": start["challenge_id"], "credential": authenticator.create(start["options"])})
    assert finish.status_code == 200, finish.text
    assert db_session.get(PasskeyChallenge, start["challenge_id"]) is None  # consumido
    response, _ = _login(client, authenticator)
    assert response.status_code == 200
    validate = client.get("/api/v1/auth/session/validate",
                          headers={"Authorization": f"Bearer {response.json()['accessToken']}"})
    assert validate.status_code == 503


def test_second_registration_excludes_existing_passkey(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    options = client.post(REGISTER_START, headers=user_headers, json={}).json()["options"]
    assert [c["id"] for c in options["excludeCredentials"]] == [b64(authenticator.credential_id)]
    assert options["user"]["id"] == authenticator.user_handle  # user handle estable
    assert _register(client, user_headers, authenticator).status_code == 409


def test_revoked_passkey_cannot_login(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    passkeys = client.get("/api/v1/auth/passkey/credentials", headers=user_headers).json()
    assert len(passkeys) == 1 and "public_key" not in passkeys[0]
    revoke = client.delete(f"/api/v1/auth/passkey/credentials/{passkeys[0]['passkey_id']}", headers=user_headers)
    assert revoke.status_code == 200
    assert _login(client, authenticator)[0].status_code == 401


def test_login_start_with_unknown_email_does_not_reveal_accounts(client, user_headers, passkeys_on, valkey):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    known = client.post(LOGIN_START, json={"correo": "ana@example.com"}).json()["options"]
    unknown = client.post(LOGIN_START, json={"correo": "nadie@example.com"}).json()["options"]
    assert [c["id"] for c in known["allowCredentials"]] == [b64(authenticator.credential_id)]
    assert unknown["allowCredentials"] == [] and set(unknown) == set(client.post(LOGIN_START, json={}).json()["options"])


def test_guards(client, user_headers, valkey, monkeypatch):
    monkeypatch.setattr(settings, "passkey_rp_id", "")
    assert client.post(LOGIN_START, json={}).status_code == 503
    monkeypatch.setattr(settings, "passkey_rp_id", RP_ID)
    assert client.post(REGISTER_START, json={}).status_code == 401
    assert client.get("/api/v1/auth/session/validate").status_code == 401
    assert client.get("/api/v1/auth/session/validate", headers={"Authorization": "Bearer x"}).status_code == 401
    monkeypatch.setattr(service_module, "RATE_LIMIT_PER_MINUTE", 2)
    valkey.data.clear()  # la petición con 503 ya contó como intento
    codes = [client.post(LOGIN_START, json={}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_disabled_account_cannot_login(client, user_headers, passkeys_on, valkey, db_session):
    authenticator = SoftAuthenticator()
    assert _register(client, user_headers, authenticator).status_code == 200
    user = db_session.get(Usuario, 10)
    user.is_enabled = False
    db_session.commit()
    assert _login(client, authenticator)[0].status_code == 403
