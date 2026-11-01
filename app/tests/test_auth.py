import pytest
from sqlalchemy import select

from app.api.v1.endpoints import auth
from app.api import deps
from app.core.cache import token_cache_key, user_cache_key
from app.core.security import create_token
from app.core.security import hash_password, verify_password
from app.models import Usuario


def _create_user(db, role_id=2):
    user = Usuario(
        usuario_id=10,
        correo="persona@example.com",
        password=hash_password("Correcta-Password-123"),
        nombres="Ana",
        apellidos="Prueba",
        telefono="3005550000",
        tipo_identificacion="CC",
        numero_identificacion="12345678",
        rol_id=role_id,
        is_enabled=True,
        account_non_expired=True,
        account_non_locked=True,
        credentials_non_expired=True,
    )
    db.add(user)
    db.commit()
    return user


def test_login_with_email_and_bcrypt_returns_jwt(client, db_session, seeded_roles):
    _create_user(db_session)
    response = client.post("/auth/login", json={"correo": "persona@example.com", "password": "Correcta-Password-123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["usuario"]["rol"] == "PERSONA_NATURAL"
    stored = db_session.get(Usuario, 10).password
    assert stored.startswith("$2a$")
    assert verify_password("Correcta-Password-123", stored)


def test_login_warms_jwt_session_cache(client, db_session, seeded_roles, monkeypatch):
    _create_user(db_session)
    writes = []
    monkeypatch.setattr(auth, "cache_set_json", lambda key, value, ttl=None: writes.append((key, value, ttl)) or True)
    response = client.post("/auth/login", json={"correo": "persona@example.com", "password": "Correcta-Password-123"})
    assert response.status_code == 200
    assert any(key.startswith("auth:token:") and value["rol"] == "PERSONA_NATURAL" for key, value, _ in writes)
    assert any(key.startswith("auth:credential:") and value["password_hash"].startswith("$2a$") for key, value, _ in writes)


def test_jwt_user_validation_uses_valkey_snapshot_without_database_lookup(client, monkeypatch):
    token = create_token("88", "ADMIN")
    user_snapshot = {
        "usuario_id": 88, "account_non_expired": True, "account_non_locked": True,
        "credentials_non_expired": True, "is_enabled": True, "empresa_id": None,
        "rol_id": 1, "numero_identificacion": None, "telefono": None,
        "correo": "cached@example.com", "direccion": None, "apellidos": "Cached",
        "nombres": "Valkey", "imagen": None, "tipo_identificacion": None,
    }
    def cached_value(key):
        if key.startswith("auth:revoked:"):
            return None
        if key == token_cache_key(token):
            return {"usuario_id": 88, "rol": "ADMIN"}
        if key == user_cache_key(88):
            return {"usuario": user_snapshot, "rol": "ADMIN"}
        return None
    monkeypatch.setattr(deps, "cache_get_json", cached_value)
    response = client.get("/perfil", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["correo"] == "cached@example.com"


def test_direct_registration_requires_all_seven_profile_fields(client, seeded_roles):
    response = client.post("/auth/registro", json={"correo": "new@example.com", "password": "Nueva-clave-123"})
    assert response.status_code == 422


def test_direct_registration_stores_bcrypt_hash(client, db_session, seeded_roles):
    response = client.post("/auth/registro", json={
        "tipoIdentificacion": "CC",
        "numeroIdentificacion": "987654321",
        "nombres": "Luis",
        "apellidos": "Cliente",
        "telefono": "3005550001",
        "correo": "luis@example.com",
        "password": "Nueva-clave-123",
    })
    assert response.status_code == 201
    user = db_session.scalar(select(Usuario).where(Usuario.correo == "luis@example.com"))
    assert user.password.startswith("$2a$")


@pytest.mark.parametrize("provider", ["google", "apple"])
def test_social_registration_requires_seven_profile_fields(client, seeded_roles, monkeypatch, provider):
    monkeypatch.setattr(auth, "_oauth_claims", lambda *_: {"email": "social@example.com", "email_verified": True})
    response = client.post(f"/auth/{provider}", json={"id_token": "mock-oauth-id-token-value"})
    assert response.status_code == 422
    assert set(response.json()["detail"]["campos"]) == {
        "tipoIdentificacion", "numeroIdentificacion", "nombres", "apellidos", "telefono", "correo", "password"
    }


@pytest.mark.parametrize("provider", ["google", "apple"])
def test_social_registration_with_all_fields_creates_account(client, db_session, seeded_roles, monkeypatch, provider):
    monkeypatch.setattr(auth, "_oauth_claims", lambda *_: {"email": "social@example.com", "email_verified": True})
    response = client.post(f"/auth/{provider}", json={
        "id_token": "mock-oauth-id-token-value",
        "tipoIdentificacion": "CC",
        "numeroIdentificacion": "99112233",
        "nombres": "Sofia",
        "apellidos": "Social",
        "telefono": "3005550002",
        "correo": "social@example.com",
        "password": "Social-pass-123",
    })
    assert response.status_code == 200
    assert response.json()["usuario"]["correo"] == "social@example.com"
    user = db_session.scalar(select(Usuario).where(Usuario.correo == "social@example.com"))
    assert verify_password("Social-pass-123", user.password)
