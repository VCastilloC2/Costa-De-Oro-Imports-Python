"""Optional Valkey cache. Set VALKEY_URL to a Layerbase/Valkey connection URI."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from functools import lru_cache
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_cache_client():
    if not settings.valkey_url:
        return None
    try:
        import redis
        url = settings.valkey_url.strip()
        # Layerbase Quick Connect supplies rediss://; keep TLS enabled.
        if url.startswith("valkey://"):
            url = "redis://" + url[len("valkey://"):]
        elif url.startswith("valkeys://"):
            url = "rediss://" + url[len("valkeys://"):]
        parsed = urlsplit(url)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("VALKEY_URL debe usar redis:// o rediss:// e incluir un host")
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            # Layerbase's free Valkey can sleep; allow its documented wake-up window.
            socket_connect_timeout=5,
            socket_timeout=2,
            health_check_interval=30,
        )
    except Exception as exc:
        # Do not log the connection URL because it contains the database password.
        logger.error("No fue posible inicializar Valkey (%s)", type(exc).__name__)
        return None


def cache_health() -> dict[str, Any]:
    """Check the remote Valkey connection without exposing its URL or credentials."""
    if not settings.valkey_url:
        return {"status": "not_configured", "provider": "valkey"}
    client = get_cache_client()
    if client is None:
        return {"status": "unavailable", "provider": "valkey"}
    started = perf_counter()
    probe_key = f"health:write_probe:{secrets.token_hex(16)}"
    probe_value = secrets.token_urlsafe(16)
    try:
        client.ping()
        if not client.set(probe_key, probe_value, ex=15):
            raise RuntimeError("Valkey no confirmó la escritura de prueba")
        if client.get(probe_key) != probe_value:
            raise RuntimeError("Valkey no devolvió la clave de prueba")
        return {
            "status": "ok",
            "provider": "valkey",
            "write_test": True,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        logger.warning("La comprobación de Valkey falló (%s)", type(exc).__name__)
        return {"status": "unavailable", "provider": "valkey", "write_test": False}
    finally:
        try:
            client.delete(probe_key)
        except Exception:
            # The probe also expires automatically after 15 seconds.
            logger.warning("No se pudo eliminar la clave temporal de comprobación Valkey")


def cache_get_json(key: str) -> Any | None:
    client = get_cache_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        logger.warning("Valkey no disponible al leer una clave de caché", exc_info=True)
        return None


def cache_set_json(key: str, value: Any, ttl: int | None = None) -> bool:
    client = get_cache_client()
    if client is None:
        return False
    try:
        client.set(
            key,
            json.dumps(value, separators=(",", ":")),
            ex=ttl if ttl is not None else settings.valkey_cache_ttl_seconds,
        )
        return True
    except Exception:
        logger.warning("Valkey no disponible al escribir caché", exc_info=True)
        return False


def cache_delete(key: str) -> None:
    client = get_cache_client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        logger.warning("Valkey no disponible al invalidar caché", exc_info=True)


def token_cache_key(token: str) -> str:
    return "auth:token:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def user_cache_key(user_id: int) -> str:
    return f"auth:user:{user_id}"


def credential_cache_key(email: str) -> str:
    normalized = email.strip().lower()
    return "auth:credential:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cache_auth_user(user: Any, role_name: str, ttl: int | None = None) -> bool:
    """Cache the profile and authorization flags, never the password."""
    fields = (
        "usuario_id", "account_non_expired", "account_non_locked", "credentials_non_expired",
        "is_enabled", "empresa_id", "rol_id", "numero_identificacion", "telefono", "correo",
        "direccion", "apellidos", "nombres", "imagen", "tipo_identificacion",
    )
    snapshot = {field: getattr(user, field, None) for field in fields}
    return cache_set_json(
        user_cache_key(int(user.usuario_id)),
        {"usuario": snapshot, "rol": role_name},
        ttl if ttl is not None else settings.valkey_auth_ttl_seconds,
    )


def cache_auth_credentials(email: str, user_id: int, password_hash: str | None) -> bool:
    """Store a BCrypt hash for login lookup; never store or log a plaintext password."""
    if not password_hash or not password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    return cache_set_json(
        credential_cache_key(email),
        {"usuario_id": int(user_id), "password_hash": password_hash},
        settings.valkey_auth_ttl_seconds,
    )


def cache_auth_token(token: str, user_id: int, role_name: str, ttl: int) -> bool:
    """Cache only a digest-keyed session record, not the bearer token itself."""
    return cache_set_json(
        token_cache_key(token),
        {"usuario_id": int(user_id), "rol": role_name},
        max(1, int(ttl)),
    )


def revoked_token_cache_key(token: str) -> str:
    return "auth:revoked:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def revoke_token(token: str, ttl: int = 3600) -> None:
    cache_delete(token_cache_key(token))
    cache_set_json(revoked_token_cache_key(token), True, max(1, int(ttl)))
