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


def revoke_token(token: str, ttl: int = 3600) -> None:
    cache_set_json("auth:revoked:" + hashlib.sha256(token.encode("utf-8")).hexdigest(), True, ttl)
