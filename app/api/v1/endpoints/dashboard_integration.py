"""Datos de las gráficas del dashboard de Spring Boot (``Dashboard.js``).

* ``GET /api/v1/dashboard/ingresos-gastos``: ingresos (compras PAGADAS) y gastos (facturas de
  proveedor activas) mes a mes, con todos los meses del rango aunque no tengan movimientos.
* ``GET /api/v1/dashboard/ventas-totales``: reparto de las compras por estado para la dona.

Los JSON reproducen exactamente ``GraficaIngresosGastosResponse`` y ``VentasTotalesResponse``
de Spring, así ``Dashboard.js`` no cambia.

Autenticación (igual que ``/api/prediccion``): ``X-API-Key`` con permiso ``predictions:read``
(llamadas desde Spring) o ``Authorization: Bearer <JWT>`` de ADMIN (Swagger, Flutter...).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.api.deps import prediction_access
from app.core.database import get_db
from app.models import Compra, FacturaProveedor
from app.prediction.repository import SCOPE_READ

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard (gráficas)"])

MESES_ES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")

# Agrupación de estados de compra en los segmentos de la dona (mismo criterio que GraficaServiceImpl).
SEGMENTOS_VENTAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Envíos", ("PAGADO",)),
    ("Reembolsos", ("CANCELADO", "RECHAZADO")),
    ("Pedidos", ("PENDIENTE",)),
)


class IngresosGastosResponse(BaseModel):
    """Espejo de ``GraficaIngresosGastosResponse`` (Java) + totales del periodo."""

    categorias: list[str]
    ingresos: list[float]
    gastos: list[float]
    totalIngresos: float
    totalGastos: float


class VentasTotalesItem(BaseModel):
    estado: str
    nombre: str
    monto: float
    pedidos: int
    montoAnterior: float


class VentasTotalesResponse(BaseModel):
    items: list[VentasTotalesItem]
    totalMonto: float


MesesParam = Annotated[int, Query(ge=1, le=120, description="Meses hacia atrás incluyendo el actual")]


def ultimos_meses(meses: int, hoy: date | None = None) -> list[tuple[int, int]]:
    """Lista ``(año, mes)`` de los últimos ``meses`` meses, del más antiguo al actual."""
    hoy = hoy or date.today()
    indice = hoy.year * 12 + (hoy.month - 1)
    return [(i // 12, i % 12 + 1) for i in range(indice - meses + 1, indice + 1)]


def _sumas_mensuales(db: Session, fecha_col, total_col, condicion, desde, hasta=None) -> dict[tuple[int, int], float]:
    anio = extract("year", fecha_col)
    mes = extract("month", fecha_col)
    filas = db.execute(
        select(anio, mes, func.coalesce(func.sum(total_col), 0))
        .where(condicion, fecha_col >= desde, *([fecha_col <= hasta] if hasta is not None else []))
        .group_by(anio, mes)
    ).all()
    return {(int(a), int(m)): float(t) for a, m, t in filas}


def calcular_ingresos_gastos(db: Session, meses: int = 12, hoy: date | None = None) -> IngresosGastosResponse:
    """Ingresos (compras PAGADAS) y gastos (facturas activas) de los últimos ``meses`` meses, mes a mes."""
    periodos = ultimos_meses(meses, hoy)
    desde_fecha = date(periodos[0][0], periodos[0][1], 1)
    desde_dt = datetime.combine(desde_fecha, datetime.min.time())

    ingresos = _sumas_mensuales(db, Compra.fecha, Compra.total, Compra.estado == "PAGADO", desde_dt,
                                 datetime.combine(hoy or date.today(), datetime.max.time()))
    gastos = _sumas_mensuales(db, FacturaProveedor.fecha_emision, FacturaProveedor.total,
                              FacturaProveedor.activo.is_(True), desde_fecha)

    serie_ingresos = [round(ingresos.get(p, 0.0), 2) for p in periodos]
    serie_gastos = [round(gastos.get(p, 0.0), 2) for p in periodos]
    return IngresosGastosResponse(
        categorias=[f"{MESES_ES[m - 1]} {a}" for a, m in periodos],
        ingresos=serie_ingresos,
        gastos=serie_gastos,
        totalIngresos=round(sum(serie_ingresos), 2),
        totalGastos=round(sum(serie_gastos), 2),
    )


def calcular_ventas_totales(db: Session, meses: int = 12, hoy: date | None = None) -> VentasTotalesResponse:
    """Totales y pedidos por estado para el rango seleccionado y el rango previo comparable."""
    hoy = hoy or date.today()
    anio, mes = ultimos_meses(meses, hoy)[0]
    desde = datetime(anio, mes, 1)
    anterior_inicio_idx = anio * 12 + mes - 1 - meses
    anterior_desde = datetime(anterior_inicio_idx // 12, anterior_inicio_idx % 12 + 1, 1)
    fin = datetime.combine(hoy, datetime.max.time())
    filas = db.execute(
        select(Compra.estado, func.coalesce(func.sum(Compra.total), 0), func.count(Compra.compra_id))
        .where(Compra.fecha >= desde, Compra.fecha <= fin)
        .group_by(Compra.estado)
    ).all()
    previo = db.execute(
        select(Compra.estado, func.coalesce(func.sum(Compra.total), 0))
        .where(Compra.fecha >= anterior_desde, Compra.fecha < desde)
        .group_by(Compra.estado)
    ).all()
    actuales = {str(e): (float(m or 0), int(n or 0)) for e, m, n in filas if e is not None}
    anteriores = {str(e): float(m or 0) for e, m in previo if e is not None}
    items = []
    for estado, nombre, estados in (
        ("PAGADO", "Cobradas", ("PAGADO",)),
        ("CANCELADO_RECHAZADO", "No cobradas", ("CANCELADO", "RECHAZADO")),
        ("PENDIENTE", "Pendientes", ("PENDIENTE",)),
    ):
        monto = round(sum(actuales.get(e, (0, 0))[0] for e in estados), 2)
        pedidos = sum(actuales.get(e, (0, 0))[1] for e in estados)
        monto_anterior = round(sum(anteriores.get(e, 0) for e in estados), 2)
        items.append(VentasTotalesItem(estado=estado, nombre=nombre, monto=monto, pedidos=pedidos,
                                      montoAnterior=monto_anterior))
    return VentasTotalesResponse(
        items=items, totalMonto=round(sum(item.monto for item in items), 2),
    )


@router.get("/ingresos-gastos", response_model=IngresosGastosResponse,
            summary="Ingresos y gastos totales mes a mes")
def ingresos_gastos(
    request: Request,
    principal: Annotated[dict, Depends(prediction_access(SCOPE_READ))],
    db: Annotated[Session, Depends(get_db)],
    meses: MesesParam = 12,
) -> IngresosGastosResponse:
    logger.info("dashboard ingresos-gastos meses=%s by=%s requestId=%s",
                meses, principal["name"], request.headers.get("X-Request-Id", "-"))
    return calcular_ingresos_gastos(db, meses)


@router.get("/ventas-totales", response_model=VentasTotalesResponse,
            summary="Ventas por estado (Envíos, Reembolsos, Pedidos) para la dona")
def ventas_totales(
    request: Request,
    principal: Annotated[dict, Depends(prediction_access(SCOPE_READ))],
    db: Annotated[Session, Depends(get_db)],
    meses: MesesParam = 12,
) -> VentasTotalesResponse:
    logger.info("dashboard ventas-totales meses=%s by=%s requestId=%s",
                meses, principal["name"], request.headers.get("X-Request-Id", "-"))
    return calcular_ventas_totales(db, meses)
