"""Gráficas del dashboard de administración (equivalente a ``DashboardRestController`` de Spring).

Mismas rutas y mismo JSON que ``/api/graficas/*`` en Spring (``GraficaServiceImpl``), para que
``Dashboard.js`` funcione igual contra cualquiera de los dos backends. Diferencia deliberada:
``/dashboard`` NO devuelve el hash de la contraseña del usuario (Spring serializaba la entidad
``Usuario`` completa).
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.dashboard_integration import (
    IngresosGastosResponse, VentasTotalesResponse, calcular_ingresos_gastos, calcular_ventas_totales,
)
from app.core.database import get_db
from app.core.media import cloudinary_url
from app.dependencies import admin_user
from app.models import (Categoria, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor,
                        Producto, Rol, Usuario)

router = APIRouter(prefix="/api/graficas", tags=["Administración"], dependencies=[Depends(admin_user)])

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


def _semestre(db: Session, col_fecha, col_total, activo, anio: int, meses: tuple[int, int]) -> float:
    return _suma(db, col_total, activo, extract("year", col_fecha) == anio,
                 extract("month", col_fecha).between(*meses))


def _progreso(actual: float, proyeccion: float) -> int:
    if proyeccion == 0:
        return 0
    return int(min(max(actual / proyeccion * 100, 0), 100))


def _variacion(actual: float, anterior: float) -> float:
    return 0.0 if anterior == 0 else (actual - anterior) / anterior * 100


def estadisticas_generales(db: Session, hoy: date | None = None) -> dict:
    """``GraficaServiceImpl.obtenerEstadisticasGenerales``: semestre actual (ene-jun) vs. jul-dic del año anterior."""
    anio = (hoy or date.today()).year
    pagado, activa = Compra.estado == "PAGADO", FacturaProveedor.activo.is_(True)
    ingresos = _semestre(db, Compra.fecha, Compra.total, pagado, anio, (1, 6))
    gastos = _semestre(db, FacturaProveedor.fecha_emision, FacturaProveedor.total, activa, anio, (1, 6))
    stock = int(db.scalar(select(func.coalesce(func.sum(Producto.stock), 0)).where(Producto.activo.is_(True))) or 0)
    beneficio = ingresos - gastos

    ingresos_ant = _semestre(db, Compra.fecha, Compra.total, pagado, anio - 1, (7, 12))
    gastos_ant = _semestre(db, FacturaProveedor.fecha_emision, FacturaProveedor.total, activa, anio - 1, (7, 12))
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
    pagado_este_anio = (Compra.estado == "PAGADO", extract("year", Compra.fecha) == anio)
    pagado_anio_anterior = (Compra.estado == "PAGADO", extract("year", Compra.fecha) == anio - 1)
    clientes_anio_anterior = db.scalar(
        select(func.count(func.distinct(Compra.usuario_id)))
        .select_from(Compra)
        .join(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .where(*pagado_anio_anterior, Rol.rol.in_(ROLES_CLIENTE))
    ) or 0
    return {
        "usuario": _usuario_publico(usuario, db),
        "urlImagenUsuario": cloudinary_url(usuario.imagen),
        "ingresoAnual": _suma(db, Compra.total, *pagado_este_anio),
        "comprasAnuales": int(db.scalar(select(func.count()).select_from(Compra).where(*pagado_este_anio)) or 0),
        "comprasAnioAnterior": int(db.scalar(select(func.count()).select_from(Compra).where(*pagado_anio_anterior)) or 0),
        # No hay fecha de alta de usuario en el modelo; se informa clientes activos (con compra pagada)
        # durante el año previo, que es el único indicador histórico fiable disponible.
        "clientesAnioAnterior": int(clientes_anio_anterior),
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
class _JavaRandom:
    """``java.util.Random`` (LCG de 48 bits) para reproducir exactamente la serie de Spring."""

    _MULT, _ADD, _MASK = 0x5DEECE66D, 0xB, (1 << 48) - 1

    def __init__(self, seed: int) -> None:
        self._seed = (seed ^ self._MULT) & self._MASK

    def _next(self, bits: int) -> int:
        self._seed = (self._seed * self._MULT + self._ADD) & self._MASK
        return self._seed >> (48 - bits)

    def next_double(self) -> float:
        return ((self._next(26) << 27) + self._next(27)) * (1.0 / (1 << 53))


def _con_subpicos(series: list[float], anios: list[int]) -> tuple[list[float], list[int]]:
    """``generarDatosConSubpicos``: 10 puntos interpolados con ±7,5 % de variación entre cada par de años.

    OJO: son puntos SINTÉTICOS (decorativos), igual que en Spring; los valores reales son los años exactos.
    """
    rnd = _JavaRandom(12345)
    out_series, out_cats = [], []
    for i, (valor, anio) in enumerate(zip(series, anios)):
        out_series.append(valor)
        out_cats.append(anio * 1000)
        if i < len(series) - 1:
            siguiente = series[i + 1]
            for j in range(1, 11):
                progresion = j / 11.0
                intermedio = anio + progresion
                interpolado = valor + (siguiente - valor) * progresion
                con_subpico = interpolado + (rnd.next_double() * 0.15 - 0.075) * valor
                con_subpico = max(con_subpico * 0.8, min(con_subpico * 1.2, con_subpico))
                out_series.append(con_subpico)
                out_cats.append(int(intermedio * 1000))
    return out_series, out_cats


@router.get("/historico-ventas", summary="Ventas pagadas por año (con puntos intermedios decorativos)")
def historico_ventas(db: DB) -> dict:
    anio = extract("year", Compra.fecha)
    filas = db.execute(
        select(anio, func.sum(Compra.total))
        .where(Compra.estado == "PAGADO", Compra.fecha.is_not(None))
        .group_by(anio)
        .order_by(anio)
    ).all()
    anios = [int(a) for a, _ in filas]
    series = [float(t or 0) for _, t in filas]
    maximo = max(series, default=0.0)
    maximo = max(maximo, 0.0)
    minimo = min(series) if series else 0.0
    promedio = sum(series) / len(series) if series else 0.0
    if len(series) > 1:
        series, anios = _con_subpicos(series, anios)
    return {"series": series, "categorias": anios, "maxVenta": maximo, "minVenta": minimo,
            "promedioVentas": promedio}
