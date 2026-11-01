"""Optional Valkey cache. Set VALKEY_URL to a Layerbase/Valkey connection URI."""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_cache_client():
    if not settings.valkey_url:
        return None
    try:
        import redis
        url = settings.valkey_url.strip()
        if url.startswith("valkey://"):
            url = "redis://" + url[len("valkey://"):]
        elif url.startswith("valkeys://"):
            url = "rediss://" + url[len("valkeys://"):]
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    except Exception:
        logger.exception("No fue posible inicializar el cliente Valkey")
        return None


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
        client.set(key, json.dumps(value, separators=(",", ":")), ex=ttl or settings.valkey_cache_ttl_seconds)
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
