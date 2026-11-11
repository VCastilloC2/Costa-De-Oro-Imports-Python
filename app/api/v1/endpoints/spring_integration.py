"""Endpoints servicio-a-servicio consumidos por el backend Spring Boot (``PrediccionApiClient``).

Autenticación: cabecera ``X-API-Key`` con una clave de servicio emitida por un ADMIN
(``POST /api/v1/predictions/clients``). La validación la hace ``prediction_access``:

* la clave se compara por hash (nunca se guarda en claro) y puede revocarse al instante;
* cada clave tiene permisos acotados (``predictions:read`` / ``predictions:generate``);
* cada acceso, permitido o denegado, queda registrado con canal, solicitante e IP.

También acepta ``Authorization: Bearer <JWT>`` de un rol permitido, útil para probar desde Swagger.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import prediction_access
from app.core.database import get_db
from app.prediction.engine import forecast_month, generate_forecast
from app.prediction.repository import SCOPE_GENERATE, SCOPE_READ

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prediccion", tags=["Integración Spring Boot"])


class SolicitudPrediccion(BaseModel):
    """Cuerpo de ``PrediccionApiClient.SolicitudPrediccion`` (Java)."""

    model_config = ConfigDict(extra="forbid")
    anno: int = Field(ge=2019, le=2035)
    mes: int = Field(ge=1, le=12)


class RespuestaPrediccion(BaseModel):
    """Espejo de ``PrediccionApiClient.RespuestaPrediccion`` (Java)."""

    resultado: float | None
    mensaje: str
    success: bool


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id", "-")


@router.get("/datos-grafica", summary="Serie mensual real + predicción para la gráfica de Spring")
def datos_grafica(
    request: Request,
    principal: Annotated[dict, Depends(prediction_access(SCOPE_READ))],
    db: Annotated[Session, Depends(get_db)],
    anios: Annotated[int, Query(ge=1, le=10)] = 6,
    proyeccion_meses: Annotated[int, Query(ge=0, le=24)] = 0,
) -> dict:
    logger.info("spring datos-grafica anios=%s proyeccion=%s by=%s requestId=%s",
                anios, proyeccion_meses, principal["name"], _request_id(request))
    try:
        return generate_forecast(db, years=anios, forecast_months=proyeccion_meses)
    except ValueError as exc:  # datos insuficientes, rango inválido...
        raise HTTPException(422, str(exc)) from exc


@router.post("/generar", response_model=RespuestaPrediccion, summary="Venta prevista para un mes")
def generar(
    payload: SolicitudPrediccion,
    request: Request,
    principal: Annotated[dict, Depends(prediction_access(SCOPE_GENERATE))],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaPrediccion:
    logger.info("spring generar anno=%s mes=%s by=%s requestId=%s",
                payload.anno, payload.mes, principal["name"], _request_id(request))
    try:
        result = forecast_month(db, payload.anno, payload.mes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RespuestaPrediccion(resultado=result["prediccion"], mensaje="Predicción generada", success=True)
