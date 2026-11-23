"""Búsqueda puntual de ciudades colombianas con OpenStreetMap Nominatim.

No enviar direcciones particulares ni coordenadas personales a este servicio.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core import cache
from app.core.config import settings

logger = logging.getLogger(__name__)
ATTRIBUTION = "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright"
_local_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_request_at = 0.0


def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    return f"nominatim:city:v1:{digest}"


def _get_cached(key: str) -> list[dict] | None:
    cached = cache.cache_get_json(key)
    if isinstance(cached, list):
        return cached
    now = time.monotonic()
    with _cache_lock:
        entry = _local_cache.get(key)
        if entry and entry[0] > now:
            return entry[1]
        _local_cache.pop(key, None)
    return None


def _set_cached(key: str, results: list[dict]) -> None:
    cache.cache_set_json(key, results, settings.nominatim_cache_seconds)
    now = time.monotonic()
    with _cache_lock:
        if len(_local_cache) >= 512:
            for stale in [k for k, (expires, _) in _local_cache.items() if expires <= now]:
                _local_cache.pop(stale, None)
            if len(_local_cache) >= 512:
                _local_cache.pop(next(iter(_local_cache)))
        _local_cache[key] = (now + settings.nominatim_cache_seconds, results)


def _reserve_provider_request() -> tuple[bool, int]:
    """Allow at most one uncached call per second (shared through Valkey when configured)."""
    global _last_request_at
    client = cache.get_cache_client()
    if client is not None:
        try:
            allowed = bool(client.set("nominatim:global:request-slot", "1", ex=2, nx=True))
            return allowed, 1
        except Exception:  # noqa: BLE001 - local fallback if Valkey is down
            logger.warning("No se pudo reservar el límite global Nominatim en Valkey", exc_info=True)

    with _rate_lock:
        now = time.monotonic()
        remaining = 1.05 - (now - _last_request_at)
        if remaining > 0:
            return False, max(1, int(remaining + 0.99))
        _last_request_at = now
        return True, 1


def search_colombian_cities(city: str, department: str | None = None) -> list[dict]:
    """Search for a city/municipality only; never geocode a street or house address."""
    query = ", ".join(part.strip() for part in (city, department, "Colombia") if part and part.strip())
    key = _cache_key(query)
    cached = _get_cached(key)
    if cached is not None:
        return cached

    allowed, retry_after = _reserve_provider_request()
    if not allowed:
        raise NominatimRateLimited(retry_after)

    params = urlencode({
        "q": query,
        "format": "jsonv2",
        "countrycodes": "co",
        "featuretype": "city",
        "addressdetails": 1,
        "limit": 5,
        "accept-language": "es",
    })
    base_url = settings.nominatim_base_url.rstrip("/")
    request = Request(
        f"{base_url}/search?{params}",
        headers={"User-Agent": settings.nominatim_user_agent, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=settings.nominatim_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.warning("Nominatim respondió HTTP %s", exc.code)
        raise NominatimUnavailable("El servicio de mapas no está disponible temporalmente.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("No se pudo consultar Nominatim: %s", exc)
        raise NominatimUnavailable("No se pudo consultar el servicio de mapas.") from exc

    results = []
    for item in payload if isinstance(payload, list) else []:
        address = item.get("address") or {}
        city_name = (address.get("city") or address.get("town") or address.get("municipality")
                     or address.get("village") or item.get("name"))
        results.append({
            "nombre": city_name,
            "departamento": address.get("state") or address.get("region"),
            "pais": address.get("country"),
            "latitud": float(item["lat"]),
            "longitud": float(item["lon"]),
            "nombre_completo": item.get("display_name"),
            "osm_type": item.get("osm_type"),
            "osm_id": item.get("osm_id"),
        })
    _set_cached(key, results)
    return results


class NominatimRateLimited(Exception):
    def __init__(self, retry_after: int = 1) -> None:
        self.retry_after = retry_after


class NominatimUnavailable(Exception):
    pass
