"""City-level location lookup through the Nominatim proxy."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.core import rate_limit
from app.core.config import settings
from app.services.nominatim_service import (
    ATTRIBUTION,
    NominatimRateLimited,
    NominatimUnavailable,
    search_colombian_cities,
)

router = APIRouter(tags=["Ubicación"])


@router.get("/api/ubicacion/ciudades", summary="Buscar una ciudad colombiana y obtener coordenadas")
def search_cities(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=80,
                            pattern=r"^[A-Za-zÀ-ÖØ-öø-ÿ\s.'-]+$",
                            description="Solo nombre de ciudad o municipio; no enviar direcciones particulares")],
    departamento: Annotated[str | None, Query(max_length=80, pattern=r"^[A-Za-zÀ-ÖØ-öø-ÿ\s.'-]+$")] = None,
) -> dict:
    """Búsqueda explícita de ciudad. No usar para autocompletar mientras se escribe."""
    if not settings.nominatim_enabled:
        raise HTTPException(503, "La búsqueda de ciudades está desactivada")
    ip = request.client.host if request.client else "desconocida"
    allowed, retry_after = rate_limit.hit(f"nominatim:client:{ip}", 10, 60)
    if not allowed:
        raise HTTPException(429, "Demasiadas búsquedas de ciudades. Intenta más tarde.",
                            headers={"Retry-After": str(retry_after)})
    try:
        results = search_colombian_cities(q, departamento)
    except NominatimRateLimited as exc:
        raise HTTPException(429, "La búsqueda está limitada temporalmente. Intenta en un segundo.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc
    except NominatimUnavailable as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from exc
    return {
        "resultados": results,
        "atribucion": ATTRIBUTION,
        "licencia": "ODbL",
    }
