"""Límite de peticiones por ventana de tiempo.

Usa Valkey (contador compartido por todos los workers). Si Valkey no está configurado o no responde,
usa un contador en memoria del proceso para no dejar el endpoint sin protección.
"""
from __future__ import annotations

import threading
import time

from app.core import cache

_local: dict[str, tuple[int, float]] = {}
_local_lock = threading.Lock()


def _window_key(key: str, window_seconds: int) -> tuple[str, int]:
    bucket = int(time.time() // window_seconds)
    return f"ratelimit:{key}:{bucket}", window_seconds - int(time.time() % window_seconds) + 1


def hit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Registra una petición. Devuelve ``(permitida, segundos_para_reintentar)``."""
    redis_key, retry_after = _window_key(key, window_seconds)
    client = cache.get_cache_client()
    if client is not None:
        try:
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, retry_after)
            return count <= limit, retry_after
        except Exception:  # noqa: BLE001 - Valkey caído: se usa el contador local
            pass
    now = time.monotonic()
    with _local_lock:
        if len(_local) > 10000:
            for stale in [k for k, (_, exp) in _local.items() if exp <= now]:
                _local.pop(stale, None)
        count, expires = _local.get(redis_key, (0, now + retry_after))
        count += 1
        _local[redis_key] = (count, expires)
    return count <= limit, retry_after


def reset_local() -> None:
    """Sólo para pruebas."""
    with _local_lock:
        _local.clear()
