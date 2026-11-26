"""Gráficas del dashboard de administración (equivalente a ``DashboardRestController`` de Spring).

Mismas rutas y mismo JSON que ``/api/graficas/*`` en Spring (``GraficaServiceImpl``), para que
``Dashboard.js`` funcione igual contra cualquiera de los dos backends. Diferencia deliberada:
``/dashboard`` NO devuelve el hash de la contraseña del usuario (Spring serializaba la entidad
``Usuario`` completa).
"""
from __future__ import annotations

import threading
import time
import unicodedata
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, case, extract, func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.dashboard_integration import (
    IngresosGastosResponse, VentasTotalesResponse, calcular_ingresos_gastos, calcular_ventas_totales,
)
from app.core.cache import cache_get_json, cache_set_json
from app.core.database import get_db
from app.core.media import cloudinary_url
from app.dependencies import admin_user
from app.models import (Categoria, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor,
                        Producto, Rol, Usuario)
from app.services.sales_report_export import build_sales_pdf, build_sales_xlsx

router = APIRouter(prefix="/api/graficas", tags=["Administración"], dependencies=[Depends(admin_user)])

_DASHBOARD_BUNDLE_TTL_SECONDS = 30
_dashboard_bundle_lock = threading.Lock()
_dashboard_bundle_local: dict[int, tuple[float, dict]] = {}

DB = Annotated[Session, Depends(get_db)]

ROLES_CLIENTE = ("PERSONA_CONTACTO", "PERSONA_JURIDICA", "PERSONA_NATURAL")
DESCRIPCION_ESTADO = {"PENDIENTE": "Pendiente", "PAGADO": "Pagado", "CANCELADO": "Cancelado", "RECHAZADO": "Rechazado"}
CLASE_ESTADO = {"PAGADO": "td__estados completado", "PENDIENTE": "td__estados pendiente",
                "CANCELADO": "td__estados cancelado"}

# Mismas coordenadas que GraficaServiceImpl.coordenadasCiudades
COORDENADAS_CIUDADES: dict[str, tuple[float, float]] = {
    "Bogotá": (4.7110, -74.0721), "Medellín": (6.2442, -75.5812), "Cali": (3.4516, -76.5320),
    "Barranquilla": (10.9639, -74.7964), "Cartagena": (10.3910, -75.4794),
    "Bucaramanga": (7.1193, -73.1227), "Cúcuta": (7.8939, -72.5078), "Pereira": (4.8087, -75.6906),
    "Santa Marta": (11.2408, -74.1990), "Manizales": (5.0703, -75.5138), "Armenia": (4.5370, -75.6751),
    "Villavicencio": (4.1420, -73.6266), "Ibagué": (4.4447, -75.2422), "Neiva": (2.9345, -75.2809),
    "Pasto": (1.2136, -77.2811), "Montería": (8.7500, -75.8833), "Valledupar": (10.4631, -73.2532),
    "Sincelejo": (9.3047, -75.3978), "Popayán": (2.4448, -76.6147), "Tunja": (5.5353, -73.3678),
}


def _menos_meses(ahora: datetime, meses: int) -> datetime:
    """Equivalente a ``LocalDateTime.now().minusMonths(n)`` (ajusta el día al último del mes si no existe)."""
    indice = ahora.year * 12 + ahora.month - 1 - meses
    anio, mes = divmod(indice, 12)
    mes += 1
    siguiente = date(anio + (mes == 12), mes % 12 + 1, 1)
    ultimo_dia = (siguiente - date(anio, mes, 1)).days
    return ahora.replace(year=anio, month=mes, day=min(ahora.day, ultimo_dia))


# --------------------------------------------------------------------------- /dashboard
def _suma(db: Session, columna, *condiciones) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(columna), 0)).where(*condiciones)) or 0)


def _progreso(actual: float, proyeccion: float) -> int:
    if proyeccion == 0:
        return 0
    return int(min(max(actual / proyeccion * 100, 0), 100))


def _variacion(actual: float, anterior: float) -> float:
    return 0.0 if anterior == 0 else (actual - anterior) / anterior * 100


def estadisticas_generales(db: Session, hoy: date | None = None) -> dict:
    """``GraficaServiceImpl.obtenerEstadisticasGenerales``: semestre actual (ene-jun) vs. jul-dic del año anterior."""
    anio = (hoy or date.today()).year
    compra_year = extract("year", Compra.fecha)
    compra_month = extract("month", Compra.fecha)
    compras = db.execute(select(
        func.coalesce(func.sum(case((and_(
            Compra.estado == "PAGADO", compra_year == anio,
            compra_month.between(1, 6),
        ), Compra.total), else_=0)), 0).label("ingresos"),
        func.coalesce(func.sum(case((and_(
            Compra.estado == "PAGADO", compra_year == anio - 1,
            compra_month.between(7, 12),
        ), Compra.total), else_=0)), 0).label("ingresos_ant"),
    )).one()
    factura_year = extract("year", FacturaProveedor.fecha_emision)
    factura_month = extract("month", FacturaProveedor.fecha_emision)
    facturas = db.execute(select(
        func.coalesce(func.sum(case((and_(
            FacturaProveedor.activo.is_(True), factura_year == anio,
            factura_month.between(1, 6),
        ), FacturaProveedor.total), else_=0)), 0).label("gastos"),
        func.coalesce(func.sum(case((and_(
            FacturaProveedor.activo.is_(True), factura_year == anio - 1,
            factura_month.between(7, 12),
        ), FacturaProveedor.total), else_=0)), 0).label("gastos_ant"),
    )).one()
    ingresos = float(compras.ingresos or 0)
    ingresos_ant = float(compras.ingresos_ant or 0)
    gastos = float(facturas.gastos or 0)
    gastos_ant = float(facturas.gastos_ant or 0)
    stock = int(db.scalar(select(func.coalesce(func.sum(Producto.stock), 0)).where(Producto.activo.is_(True))) or 0)
    beneficio = ingresos - gastos
    beneficio_ant = ingresos_ant - gastos_ant

    proy_ingresos, proy_gastos, proy_beneficio = ingresos_ant * 1.05, gastos_ant * 1.05, beneficio_ant * 1.05
    objetivo_stock = int(stock * 1.05)
    return {
        "ingresosTotales": ingresos,
        "gastosTotales": gastos,
        "beneficioTotal": beneficio,
        "stockDisponible": stock,
        "proyeccionIngresosAnual": proy_ingresos,
        "proyeccionGastosAnual": proy_gastos,
        "proyeccionBeneficioAnual": proy_beneficio,
        "objetivoStock": objetivo_stock,
        "progresoIngresos": _progreso(ingresos, proy_ingresos),
        "progresoGastos": _progreso(gastos, proy_gastos),
        "progresoBeneficio": _progreso(beneficio, proy_beneficio),
        "progresoStock": _progreso(float(stock), float(objetivo_stock)),
        "variacionIngresos": _variacion(ingresos, ingresos_ant),
        "variacionGastos": _variacion(gastos, gastos_ant),
        "variacionBeneficio": _variacion(beneficio, beneficio_ant),
        "variacionStock": _variacion(float(stock), float(objetivo_stock)),
    }


def top_productos_mas_vendidos(db: Session, limite: int = 4) -> list[dict]:
    total = func.sum(DetalleVenta.cantidad)
    filas = db.execute(
        select(Producto.producto_id, Producto.nombre, Producto.imagen, Producto.precio, total)
        .join(DetalleVenta, DetalleVenta.producto_id == Producto.producto_id)
        .join(Compra, Compra.compra_id == DetalleVenta.compra_id)
        .where(Compra.estado == "PAGADO", Producto.activo.is_(True))
        .group_by(Producto.producto_id, Producto.nombre, Producto.imagen, Producto.precio)
        .order_by(total.desc())
        .limit(limite)
    ).all()
    return [{"productoId": pid, "nombre": nombre, "imagen": cloudinary_url(imagen),
             "precio": float(precio or 0), "totalVentas": int(vendidos or 0)}
            for pid, nombre, imagen, precio, vendidos in filas]


def compras_recientes(db: Session, limite: int = 4) -> list[dict]:
    filas = db.execute(
        select(Compra, Usuario.nombres, Usuario.apellidos)
        .join(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .order_by(Compra.fecha.desc())
        .limit(limite)
    ).all()
    resultado = []
    for compra, nombres, apellidos in filas:
        estado = (compra.estado or "").upper()
        resultado.append({
            "compraId": compra.compra_id,
            "numeroPedido": f"ORD-{compra.compra_id:04d}",
            "nombreCliente": f"{nombres or ''} {apellidos or ''}".strip(),
            "fechaPedido": compra.fecha.isoformat() if compra.fecha else None,
            "total": float(compra.total or 0),
            "estado": DESCRIPCION_ESTADO.get(estado, compra.estado),
            "claseEstado": CLASE_ESTADO.get(estado, "td__estados procesado"),
            "textoEstado": DESCRIPCION_ESTADO.get(estado, "Rechazado"),
        })
    return resultado


def _usuario_publico(usuario: Usuario, db: Session) -> dict:
    """Campos del usuario que serializaba Spring, SIN ``password`` ni flags internos de seguridad."""
    rol = db.get(Rol, usuario.rol_id) if usuario.rol_id else None
    return {
        "usuarioId": usuario.usuario_id,
        "tipoIdentificacion": usuario.tipo_identificacion,
        "numeroIdentificacion": usuario.numero_identificacion,
        "imagen": usuario.imagen,
        "nombres": usuario.nombres,
        "apellidos": usuario.apellidos,
        "telefono": usuario.telefono,
        "correo": usuario.correo,
        "direccion": usuario.direccion,
        "enabled": bool(usuario.is_enabled),
        "rol": rol.rol if rol else None,
    }


@router.get("/dashboard", summary="Tarjetas, estadísticas, top productos y compras recientes")
def dashboard(usuario: Annotated[Usuario, Depends(admin_user)], db: DB) -> dict:
    anio = date.today().year
    year = extract("year", Compra.fecha)
    current_paid = and_(Compra.estado == "PAGADO", year == anio)
    prior_year = year == anio - 1
    prior_paid = and_(Compra.estado == "PAGADO", prior_year)
    purchase_totals = db.execute(
        select(
            func.coalesce(func.sum(case((current_paid, Compra.total), else_=0)), 0)
            .label("ingresoAnual"),
            func.coalesce(func.sum(case((current_paid, 1), else_=0)), 0)
            .label("comprasAnuales"),
            func.coalesce(func.sum(case((prior_year, 1), else_=0)), 0)
            .label("comprasAnioAnterior"),
            func.count(func.distinct(case((
                and_(prior_paid, Rol.rol.in_(ROLES_CLIENTE)), Compra.usuario_id,
            ), else_=None))).label("clientesAnioAnterior"),
        )
        .select_from(Compra)
        .outerjoin(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .outerjoin(Rol, Rol.rol_id == Usuario.rol_id)
    ).one()
    return {
        "usuario": _usuario_publico(usuario, db),
        "urlImagenUsuario": cloudinary_url(usuario.imagen),
        "ingresoAnual": float(purchase_totals.ingresoAnual or 0),
        "comprasAnuales": int(purchase_totals.comprasAnuales or 0),
        "comprasAnioAnterior": int(purchase_totals.comprasAnioAnterior or 0),
        # No hay fecha de alta de usuario en el modelo; se informa clientes activos (con compra pagada)
        # durante el año previo, que es el único indicador histórico fiable disponible.
        "clientesAnioAnterior": int(purchase_totals.clientesAnioAnterior or 0),
        "totalClientes": int(db.scalar(
            select(func.count()).select_from(Usuario).join(Rol, Rol.rol_id == Usuario.rol_id)
            .where(Rol.rol.in_(ROLES_CLIENTE))) or 0),
        "estadisticas": estadisticas_generales(db),
        "productosMasVendidos": top_productos_mas_vendidos(db),
        "comprasRecientes": compras_recientes(db),
    }


# --------------------------------------------------------------------------- ingresos / ventas
@router.get("/ingresos-gastos", response_model=IngresosGastosResponse,
            summary="Ingresos y gastos de los últimos 12 meses, mes a mes")
def ingresos_gastos(db: DB, meses: int = Query(12, ge=1, le=120)) -> IngresosGastosResponse:
    return calcular_ingresos_gastos(db, meses)


@router.get("/ventas-totales", response_model=VentasTotalesResponse,
            summary="Ventas de los últimos 12 meses por estado (dona)")
def ventas_totales(db: DB, meses: int = Query(12, ge=1, le=120)) -> VentasTotalesResponse:
    return calcular_ventas_totales(db, meses)


@router.get("/dashboard-completo", summary="Resumen agregado del dashboard en una sola consulta HTTP")
def dashboard_completo(
    usuario: Annotated[Usuario, Depends(admin_user)],
    db: DB,
) -> dict:
    """Reduce llamadas repetidas desde Flutter con un cache corto por administrador."""
    user_id = int(usuario.usuario_id)
    cache_key = f"dashboard:bundle:v1:{user_id}"
    now = time.monotonic()
    local = _dashboard_bundle_local.get(user_id)
    if local is not None and local[0] > now:
        return local[1]

    with _dashboard_bundle_lock:
        now = time.monotonic()
        local = _dashboard_bundle_local.get(user_id)
        if local is not None and local[0] > now:
            return local[1]
        cached = cache_get_json(cache_key)
        if isinstance(cached, dict):
            _dashboard_bundle_local[user_id] = (
                now + _DASHBOARD_BUNDLE_TTL_SECONDS,
                cached,
            )
            return cached

        result = {
            "dashboard": dashboard(usuario, db),
            "ingresosGastos": calcular_ingresos_gastos(db, 12).model_dump(),
            "ventasTotales": calcular_ventas_totales(db, 12).model_dump(),
        }
        cache_set_json(cache_key, result, _DASHBOARD_BUNDLE_TTL_SECONDS)
        _dashboard_bundle_local[user_id] = (
            time.monotonic() + _DASHBOARD_BUNDLE_TTL_SECONDS,
            result,
        )
        if len(_dashboard_bundle_local) > 256:
            now = time.monotonic()
            expired = [key for key, (expires, _) in _dashboard_bundle_local.items()
                       if expires <= now]
            for key in expired:
                _dashboard_bundle_local.pop(key, None)
            while len(_dashboard_bundle_local) > 256:
                _dashboard_bundle_local.pop(next(iter(_dashboard_bundle_local)))
        return result


@router.get("/ventas-totales/export", summary="Descarga el reporte de ventas totales en PDF o Excel")
def exportar_ventas_totales(
    db: DB,
    formato: str = Query("pdf", alias="format", pattern="^(pdf|xlsx)$"),
    meses: int = Query(12, ge=1, le=120),
) -> Response:
    reporte = calcular_ventas_totales(db, meses)
    if formato == "pdf":
        contenido = build_sales_pdf(reporte, meses)
        media_type = "application/pdf"
        extension = "pdf"
    else:
        contenido = build_sales_xlsx(reporte, meses)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        extension = "xlsx"
    filename = f"ventas_totales_{date.today():%Y%m%d}.{extension}"
    return Response(
        content=contenido,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- stock vs ventas
@router.get("/stock-compras", summary="Unidades vendidas (6 meses) vs. stock disponible por categoría")
def stock_compras(db: DB) -> dict:
    hasta = datetime.now()
    desde = _menos_meses(hasta, 6)
    vendidas = func.sum(DetalleVenta.cantidad)
    ventas = db.execute(
        select(Categoria.nombre, vendidas)
        .select_from(DetalleVenta)
        .join(Compra, Compra.compra_id == DetalleVenta.compra_id)
        .join(Producto, Producto.producto_id == DetalleVenta.producto_id)
        .join(Categoria, Categoria.categoria_id == Producto.categoria_id)
        .where(Compra.fecha >= desde, Compra.estado == "PAGADO")
        .group_by(Categoria.categoria_id, Categoria.nombre)
        .order_by(vendidas.desc())
    ).all()
    disponible = func.sum(Producto.stock)
    stock = db.execute(
        select(Categoria.nombre, disponible)
        .join(Categoria, Categoria.categoria_id == Producto.categoria_id)
        .where(Producto.activo.is_(True))
        .group_by(Categoria.categoria_id, Categoria.nombre)
        .order_by(disponible.desc())
    ).all()
    costo_unitario = func.sum(DetalleFactura.precio_compra * DetalleFactura.cantidad) / func.nullif(
        func.sum(DetalleFactura.cantidad), 0
    )
    costos = db.execute(
        select(Categoria.nombre, costo_unitario)
        .select_from(DetalleFactura)
        .join(FacturaProveedor, FacturaProveedor.factura_id == DetalleFactura.factura_id)
        .join(Producto, Producto.producto_id == DetalleFactura.producto_id)
        .join(Categoria, Categoria.categoria_id == Producto.categoria_id)
        .where(FacturaProveedor.activo.is_(True))
        .group_by(Categoria.categoria_id, Categoria.nombre)
    ).all()
    ventas_map = {nombre: int(v or 0) for nombre, v in ventas}
    stock_map = {nombre: int(v or 0) for nombre, v in stock}
    costo_map = {nombre: float(v) if v is not None else None for nombre, v in costos}
    categorias = list(dict.fromkeys([*ventas_map, *stock_map, *costo_map]))[:10]  # orden: primero ventas, luego stock
    return {
        "categorias": categorias,
        "ventas": [ventas_map.get(c, 0) for c in categorias],
        "stock": [stock_map.get(c, 0) for c in categorias],
        "periodoVentas": {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                          "dias": max((hasta.date() - desde.date()).days, 1)},
        "costoPromedio": [costo_map.get(c) for c in categorias],
        # El esquema no define mínimos de stock; null evita inventar una política comercial.
        "stockMinimo": [None for _ in categorias],
    }


# --------------------------------------------------------------------------- mapa
def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _coordenadas(ciudad: str) -> tuple[str, tuple[float, float]] | None:
    """Coincidencia exacta y luego parcial (en ambos sentidos), como ``encontrarCoordenadas`` de Spring.

    Mejora: compara también sin tildes ("Bogota" encuentra "Bogotá").
    """
    if ciudad in COORDENADAS_CIUDADES:
        return ciudad, COORDENADAS_CIUDADES[ciudad]
    buscada = _sin_tildes(ciudad)
    for nombre, coords in COORDENADAS_CIUDADES.items():
        clave = _sin_tildes(nombre)
        if clave in buscada or buscada in clave:
            return nombre, coords
    return None


@router.get("/mapa-ventas", summary="Unidades vendidas por ciudad de la empresa compradora (12 meses)")
def mapa_ventas(db: DB) -> dict:
    desde = _menos_meses(datetime.now(), 12)
    unidades = func.sum(DetalleVenta.cantidad)
    filas = db.execute(
        select(Empresa.ciudad, unidades, func.count(func.distinct(Empresa.empresa_id)))
        .select_from(Compra)
        .join(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .join(Empresa, Empresa.empresa_id == Usuario.empresa_id)
        .join(DetalleVenta, DetalleVenta.compra_id == Compra.compra_id)
        .where(Compra.fecha >= desde, Compra.estado == "PAGADO",
               Empresa.ciudad.is_not(None), Empresa.ciudad != "")
        .group_by(Empresa.ciudad)
        .order_by(unidades.desc())
    ).all()
    puntos = []
    for ciudad, vendidas, empresas in filas:
        encontrado = _coordenadas(ciudad)
        if encontrado:
            _, (lat, lon) = encontrado
            puntos.append({"ciudad": ciudad, "ventas": int(vendidas or 0), "latitud": lat, "longitud": lon,
                           "empresasCompradoras": int(empresas or 0)})
    puntos.sort(key=lambda p: p["ventas"], reverse=True)
    return {"ventasPorCiudad": puntos[:15]}


# --------------------------------------------------------------------------- histórico
@router.get("/historico-ventas", summary="Ventas anuales 2020–2026")
def historico_ventas(db: DB) -> dict:
    anio = extract("year", Compra.fecha)
    mes = extract("month", Compra.fecha)
    filas = db.execute(
        select(anio, func.sum(Compra.total))
        # Same-period comparison: avoid comparing a partial current year to full prior years.
        .where(Compra.estado == "PAGADO", Compra.fecha.is_not(None), anio.between(2020, 2026),
               mes.between(1, 10))
        .group_by(anio)
        .order_by(anio)
    ).all()
    ventas_por_anio = {int(a): float(total or 0) for a, total in filas}
    years = list(range(2020, 2027))
    categorias = [year * 1000 for year in years]
    series = [ventas_por_anio.get(year, 0.0) for year in years]
    maximo = max(series, default=0.0)
    minimo = min(series) if series else 0.0
    promedio = sum(series) / len(series) if series else 0.0
    return {"series": series, "categorias": categorias, "maxVenta": maximo, "minVenta": minimo,
            "promedioVentas": promedio, "periodoComparado": "enero-octubre"}
