"""Reportes de administración (equivalente a GenerarReporteRestController de Spring).

Port 1:1 de ``GenerarReporteRestController`` + ``GenerarReporteServiceImpl`` +
``ReportesNativeRepository`` (SQL nativo MySQL). Cada endpoint responde
``{<lista>: [...], "totalGeneral": {...}, "anio": <año actual>}`` con las mismas
claves camelCase que Jackson genera a partir de los records de Spring.

Notas de fidelidad (ver también los docstrings de cada endpoint):

* El filtro de año es siempre el año actual del servidor (``Year.now()``) y
  ``YEAR(col) = :anio`` se traduce a ``extract('year', col)`` (MySQL y SQLite).
* Solo cuentan compras con ``estado = 'PAGADO'``.
* Se conservan los mismos JOIN que el SQL de Spring, incluidos los que multiplican
  filas (rentabilidad y cuentas por pagar), para que los números coincidan.
* En MySQL ``detalle_venta.subtotal`` y ``detalle_factura.*`` son INT, así que
  ``subtotal * 0.19`` es DECIMAL exacto (escala 2) y una división entre DECIMAL de
  escala 0 se redondea a 4 decimales (``div_precision_increment``). Se replica con
  ``round(x, 2)`` y ``Decimal.quantize`` respectivamente. ``compra.subtotal/total``
  son DOUBLE en MySQL y se devuelven sin redondear.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, distinct, extract, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.core.media import cloudinary_url
from app.dependencies import admin_user
from app.models.entities import (
    Categoria,
    Compra,
    DetalleFactura,
    DetalleVenta,
    Empresa,
    FacturaProveedor,
    Producto,
    Rol,
    Usuario,
)

router = APIRouter(prefix="/api/reportes", tags=["Administración"], dependencies=[Depends(admin_user)])

ESTADO_PAGADO = "PAGADO"
IVA = 0.19
IVA_TOTAL = 1.19


# ---------------------------------------------------------------- helpers

def _anio() -> int:
    """Equivalente a ``java.time.Year.now().getValue()``."""
    return date.today().year


def _money(value: Any) -> float:
    """BigDecimal de Spring -> float; NULL -> 0.0 (como ``BigDecimal.ZERO``)."""
    return float(value) if value is not None else 0.0


def _money2(value: Any) -> float:
    """Para ``SUM(int * 0.19)``: en MySQL es DECIMAL exacto con escala 2."""
    return round(float(value), 2) if value is not None else 0.0


def _count(value: Any) -> int:
    return int(value) if value is not None else 0


def _nullable_money(value: Any) -> float | None:
    return float(value) if value is not None else None


def _nullable_count(value: Any) -> int | None:
    return int(value) if value is not None else None


def _iso_datetime(value: Any) -> str | None:
    """Formato de Jackson para ``LocalDateTime`` (ISO_LOCAL_DATE_TIME).

    Siempre incluye segundos; la fracción solo si no es cero y sin ceros finales
    (``2026-03-01T10:00:00``, ``2026-03-01T10:00:00.5``).
    """
    if value is None:
        return None
    if isinstance(value, str):  # defensivo: algunos drivers devuelven texto
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += "." + f"{value.microsecond:06d}".rstrip("0")
    return text


def _mysql_div_pct(numerator: Any, denominator: Any) -> float:
    """``(num / den) * 100`` con la semántica DECIMAL de MySQL.

    Ambos operandos son DECIMAL de escala 0 (sumas de columnas INT), así que MySQL
    redondea el cociente a 4 decimales (half-up) antes de multiplicar por 100.
    """
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q * 100)


def _nombre_completo(u) -> Any:
    """``CONCAT(u.nombres, ' ', COALESCE(u.apellidos, ''))`` (NULL si nombres es NULL).

    El operador ``+`` sobre String compila a ``concat()`` en MySQL y a ``||`` en
    SQLite; ambos devuelven NULL si algún operando es NULL, igual que MySQL CONCAT.
    """
    return u.nombres + literal(" ") + func.coalesce(u.apellidos, "")


def _pagado_en(anio: int, compra=Compra):
    return and_(extract("year", compra.fecha) == anio, compra.estado == ESTADO_PAGADO)


def _total_general_ventas(row) -> dict:
    """``TotalGeneralResponse(valorBrutoTotal, impuestoCargoTotal, totalGeneral)``."""
    return {
        "valorBrutoTotal": _money(row[0]),
        "impuestoCargoTotal": _money(row[1]),
        "totalGeneral": _money(row[2]),
    }


def _total_general_ventas_detalle(db: Session, anio: int) -> dict:
    """Totales sobre ``detalle_venta`` (ventas-producto y ventas-cliente-producto)."""
    row = db.execute(
        select(
            func.sum(DetalleVenta.subtotal),
            func.sum(DetalleVenta.subtotal * IVA),
            func.sum(DetalleVenta.subtotal * IVA_TOTAL),
        )
        .select_from(DetalleVenta)
        .join(Compra, DetalleVenta.compra_id == Compra.compra_id)
        .where(_pagado_en(anio))
    ).one()
    return {
        "valorBrutoTotal": _money(row[0]),
        "impuestoCargoTotal": _money2(row[1]),
        "totalGeneral": _money2(row[2]),
    }


# ---------------------------------------------------------------- endpoints

@router.get("/ventas-clientes")
def ventas_por_clientes(db: Session = Depends(get_db)) -> dict:
    """Ventas por cliente del año actual (solo compras PAGADO).

    Fila: ``identificacion`` = COALESCE(empresa.nit, usuario.numero_identificacion),
    ``cliente`` = CONCAT(nombres, ' ', COALESCE(apellidos, '')),
    ``numeroComprobantes`` = COUNT(DISTINCT compra_id), ``valorBruto`` = SUM(subtotal),
    ``impuestoCargo`` = SUM(iva), ``total`` = SUM(total). Orden: total DESC.
    """
    anio = _anio()
    u, e, c = Usuario, Empresa, Compra
    total = func.sum(c.total)
    rows = db.execute(
        select(
            func.coalesce(e.nit, u.numero_identificacion).label("identificacion"),
            _nombre_completo(u).label("cliente"),
            func.count(distinct(c.compra_id)).label("numeroComprobantes"),
            func.sum(c.subtotal).label("valorBruto"),
            func.sum(c.iva).label("impuestoCargo"),
            total.label("total"),
        )
        .select_from(c)
        .join(u, c.usuario_id == u.usuario_id)
        .outerjoin(e, u.empresa_id == e.empresa_id)
        .where(_pagado_en(anio))
        .group_by(u.usuario_id, e.nit, u.numero_identificacion, u.nombres, u.apellidos)
        .order_by(total.desc())
    ).all()
    ventas = [
        {
            "identificacion": r.identificacion,
            "cliente": r.cliente,
            "numeroComprobantes": _nullable_count(r.numeroComprobantes),
            "valorBruto": _nullable_money(r.valorBruto),
            "impuestoCargo": _nullable_money(r.impuestoCargo),
            "total": _nullable_money(r.total),
        }
        for r in rows
    ]
    totales = db.execute(
        select(func.sum(c.subtotal), func.sum(c.iva), func.sum(c.total)).where(_pagado_en(anio))
    ).one()
    return {"ventasClientes": ventas, "totalGeneral": _total_general_ventas(totales), "anio": anio}


@router.get("/ventas-productos")
@router.get("/ventas-producto", include_in_schema=False)
def ventas_por_producto(db: Session = Depends(get_db)) -> dict:
    """Ventas por producto del año actual (detalle_venta de compras PAGADO).

    ``referenciaFabrica`` = COALESCE(razon_social de la empresa del proveedor,
    'Sin proveedor'); ``valorBruto`` = SUM(dv.subtotal); ``impuestoCargo`` =
    SUM(dv.subtotal * 0.19); ``total`` = SUM(dv.subtotal * 1.19). Orden: total DESC.
    El IVA se calcula fijo al 19 % sobre el detalle (no usa compra.iva), igual que Spring.
    """
    anio = _anio()
    p, dv, c = Producto, DetalleVenta, Compra
    u_prov = aliased(Usuario)
    e = aliased(Empresa)
    total = func.sum(dv.subtotal * IVA_TOTAL)
    rows = db.execute(
        select(
            p.codigo_producto.label("codigoProducto"),
            p.nombre.label("nombreProducto"),
            p.imagen.label("imagen"),
            func.coalesce(e.razon_social, "Sin proveedor").label("referenciaFabrica"),
            func.sum(dv.cantidad).label("cantidadVendida"),
            func.sum(dv.subtotal).label("valorBruto"),
            func.sum(dv.subtotal * IVA).label("impuestoCargo"),
            total.label("total"),
        )
        .select_from(dv)
        .join(p, dv.producto_id == p.producto_id)
        .join(c, dv.compra_id == c.compra_id)
        .outerjoin(u_prov, p.usuario_id == u_prov.usuario_id)
        .outerjoin(e, u_prov.empresa_id == e.empresa_id)
        .where(_pagado_en(anio))
        .group_by(p.producto_id, p.codigo_producto, p.nombre, p.imagen, e.razon_social)
        .order_by(total.desc())
    ).all()
    ventas = [
        {
            "codigoProducto": r.codigoProducto,
            "nombreProducto": r.nombreProducto,
            "imagen": cloudinary_url(r.imagen),
            "referenciaFabrica": r.referenciaFabrica,
            "cantidadVendida": _nullable_count(r.cantidadVendida),
            "valorBruto": _nullable_money(r.valorBruto),
            "impuestoCargo": _money2(r.impuestoCargo) if r.impuestoCargo is not None else None,
            "total": _money2(r.total) if r.total is not None else None,
        }
        for r in rows
    ]
    return {
        "ventasProducto": ventas,
        "totalGeneral": _total_general_ventas_detalle(db, anio),
        "anio": anio,
    }


@router.get("/pedidos-recientes")
def pedidos_recientes(db: Session = Depends(get_db)) -> dict:
    """Pedidos recientes con cliente, producto, fecha, total y estado para el panel."""
    filas = db.execute(
        select(Compra, Usuario.nombres, Usuario.apellidos, Producto.nombre)
        .outerjoin(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .outerjoin(DetalleVenta, DetalleVenta.compra_id == Compra.compra_id)
        .outerjoin(Producto, Producto.producto_id == DetalleVenta.producto_id)
        .order_by(Compra.fecha.desc(), Compra.compra_id.desc())
    ).all()
    pedidos: dict[int, dict] = {}
    for compra, nombres, apellidos, producto in filas:
        pedido = pedidos.setdefault(compra.compra_id, {
            "compraId": compra.compra_id,
            "numeroPedido": f"FC{compra.compra_id:04d}",
            "cliente": f"{nombres or ''} {apellidos or ''}".strip(),
            "producto": producto,
            "fecha": _iso_datetime(compra.fecha),
            "total": _money(compra.total),
            "estado": compra.estado,
        })
        if not pedido["producto"] and producto:
            pedido["producto"] = producto
    return {"pedidosRecientes": sorted(pedidos.values(), key=lambda p: p["fecha"] or "", reverse=True)[:10]}


@router.get("/ventas-cliente-producto")
def ventas_por_cliente_producto(db: Session = Depends(get_db)) -> dict:
    """Ventas por cliente y producto del año actual (compras PAGADO).

    ``cliente`` = COALESCE(empresa_cliente.razon_social, CONCAT(nombres, ' ',
    COALESCE(apellidos, ''))). Mismas fórmulas de IVA que ventas-producto.
    Orden: cliente ASC, nombreProducto ASC.
    """
    anio = _anio()
    p, dv, c = Producto, DetalleVenta, Compra
    u_cli = aliased(Usuario)
    e_cli = aliased(Empresa)
    u_prov = aliased(Usuario)
    e_prov = aliased(Empresa)
    cliente = func.coalesce(e_cli.razon_social, _nombre_completo(u_cli))
    rows = db.execute(
        select(
            func.coalesce(e_cli.nit, u_cli.numero_identificacion).label("identificacion"),
            cliente.label("cliente"),
            p.codigo_producto.label("codigoProducto"),
            p.nombre.label("nombreProducto"),
            func.coalesce(e_prov.razon_social, "Sin proveedor").label("referenciaFabrica"),
            func.sum(dv.cantidad).label("cantidadVendida"),
            func.sum(dv.subtotal).label("valorBruto"),
            func.sum(dv.subtotal * IVA).label("impuestoCargo"),
            func.sum(dv.subtotal * IVA_TOTAL).label("total"),
        )
        .select_from(dv)
        .join(p, dv.producto_id == p.producto_id)
        .join(c, dv.compra_id == c.compra_id)
        .join(u_cli, c.usuario_id == u_cli.usuario_id)
        .outerjoin(e_cli, u_cli.empresa_id == e_cli.empresa_id)
        .outerjoin(u_prov, p.usuario_id == u_prov.usuario_id)
        .outerjoin(e_prov, u_prov.empresa_id == e_prov.empresa_id)
        .where(_pagado_en(anio))
        .group_by(
            u_cli.usuario_id, e_cli.nit, u_cli.numero_identificacion,
            e_cli.razon_social, u_cli.nombres, u_cli.apellidos,
            p.producto_id, p.codigo_producto, p.nombre, e_prov.razon_social,
        )
        .order_by(cliente.asc(), p.nombre.asc())
    ).all()
    ventas = [
        {
            "identificacion": r.identificacion,
            "cliente": r.cliente,
            "codigoProducto": r.codigoProducto,
            "nombreProducto": r.nombreProducto,
            "referenciaFabrica": r.referenciaFabrica,
            "cantidadVendida": _nullable_count(r.cantidadVendida),
            "valorBruto": _nullable_money(r.valorBruto),
            "impuestoCargo": _money2(r.impuestoCargo) if r.impuestoCargo is not None else None,
            "total": _money2(r.total) if r.total is not None else None,
        }
        for r in rows
    ]
    return {
        "ventasClienteProducto": ventas,
        "totalGeneral": _total_general_ventas_detalle(db, anio),
        "anio": anio,
    }


@router.get("/rentabilidad-producto")
def rentabilidad_por_producto(db: Session = Depends(get_db)) -> dict:
    """Rentabilidad por producto del año actual (compras PAGADO).

    Fórmulas (idénticas al SQL de Spring):

    * ``ventasBrutasTotales`` = SUM(dv.subtotal)
    * ``costosTotales`` = COALESCE(SUM(df.precio_compra * df.cantidad), 0)
    * ``utilidadPesos`` = ventasBrutasTotales - costosTotales
    * ``porcentajeUtilidad`` = utilidad / ventas * 100 si ventas > 0, si no 0
    * ``porcentajeRentabilidad`` = utilidad / costos * 100 si costos > 0, si no 0

    Los porcentajes usan aritmética DECIMAL de MySQL (cociente redondeado a 4
    decimales y luego * 100). Se mantiene el ``LEFT JOIN detalle_factura`` por
    producto **sin** filtro de fecha: cada línea de venta se multiplica por el número
    de líneas de factura del producto y viceversa (comportamiento real de Spring).
    ``INNER JOIN categoria`` excluye productos sin categoría. Orden: utilidadPesos DESC.

    ``totalGeneral`` = {ventasBrutasTotales, costosTotales} con su propio SQL, que no
    une producto ni categoría (incluye productos sin categoría).
    """
    anio = _anio()
    p, dv, df, fp, cat = Producto, DetalleVenta, DetalleFactura, FacturaProveedor, Categoria
    comp = aliased(Compra)
    u_prov = aliased(Usuario)
    e_prov = aliased(Empresa)
    ventas = func.sum(dv.subtotal)
    costos = func.coalesce(func.sum(df.precio_compra * df.cantidad), 0)
    utilidad = ventas - costos
    rows = db.execute(
        select(
            p.tipo.label("tipo"),
            p.codigo_producto.label("codigoProducto"),
            p.nombre.label("nombreProducto"),
            func.coalesce(e_prov.razon_social, "Sin proveedor").label("referenciaFabrica"),
            cat.nombre.label("categoria"),
            func.sum(dv.cantidad).label("cantidadVendida"),
            ventas.label("ventasBrutasTotales"),
            costos.label("costosTotales"),
            utilidad.label("utilidadPesos"),
        )
        .select_from(dv)
        .join(p, dv.producto_id == p.producto_id)
        .join(comp, dv.compra_id == comp.compra_id)
        .join(cat, p.categoria_id == cat.categoria_id)
        .outerjoin(u_prov, p.usuario_id == u_prov.usuario_id)
        .outerjoin(e_prov, u_prov.empresa_id == e_prov.empresa_id)
        .outerjoin(df, p.producto_id == df.producto_id)
        .outerjoin(fp, df.factura_id == fp.factura_id)
        .where(_pagado_en(anio, comp))
        .group_by(p.producto_id, p.tipo, p.codigo_producto, p.nombre, e_prov.razon_social, cat.nombre)
        .order_by(utilidad.desc())
    ).all()

    items = []
    for r in rows:
        v = int(r.ventasBrutasTotales or 0)
        k = int(r.costosTotales or 0)
        items.append({
            "tipo": r.tipo,
            "codigoProducto": r.codigoProducto,
            "nombreProducto": r.nombreProducto,
            "referenciaFabrica": r.referenciaFabrica,
            "categoria": r.categoria,
            "cantidadVendida": _nullable_count(r.cantidadVendida),
            "ventasBrutasTotales": _nullable_money(r.ventasBrutasTotales),
            "costosTotales": _nullable_money(r.costosTotales),
            "utilidadPesos": _nullable_money(r.utilidadPesos),
            "porcentajeUtilidad": _mysql_div_pct(v - k, v) if v > 0 else 0.0,
            "porcentajeRentabilidad": _mysql_div_pct(v - k, k) if k > 0 else 0.0,
        })

    totales = db.execute(
        select(func.sum(dv.subtotal), func.coalesce(func.sum(df.precio_compra * df.cantidad), 0))
        .select_from(dv)
        .join(comp, dv.compra_id == comp.compra_id)
        .outerjoin(df, dv.producto_id == df.producto_id)
        .outerjoin(fp, df.factura_id == fp.factura_id)
        .where(_pagado_en(anio, comp))
    ).one()
    total_general = {"ventasBrutasTotales": _money(totales[0]), "costosTotales": _money(totales[1])}
    return {"rentabilidadProducto": items, "totalGeneral": total_general, "anio": anio}


def _proveedor_filters():
    """``u.rol_id IN (SELECT rol_id FROM rol WHERE rol = 'PROVEEDOR') AND u.is_enabled = 1``."""
    return and_(
        Usuario.rol_id.in_(select(Rol.rol_id).where(Rol.rol == "PROVEEDOR")),
        Usuario.is_enabled == True,  # noqa: E712 - compila a "= 1" / "= true"
    )


@router.get("/cuentas-pagar")
def cuentas_por_pagar(db: Session = Depends(get_db)) -> dict:
    """Proveedores activos (rol PROVEEDOR, is_enabled = 1) con su actividad del año.

    ``facturasRegistradas``/``totalFacturado`` usan facturas con
    YEAR(fecha_emision) = año actual (sin filtrar ``activo``, como Spring);
    ``comprasRealizadas`` cuenta compras PAGADO del propio usuario en el año.
    Se conservan los LEFT JOIN de Spring (producto × factura × compra), por lo que
    ``totalFacturado`` = COALESCE(SUM(fp.total), 0) queda multiplicado por el
    producto cartesiano de esas uniones exactamente como en MySQL.
    Orden: totalFacturado DESC.
    """
    anio = _anio()
    u, e, p, fp, comp = Usuario, Empresa, Producto, FacturaProveedor, aliased(Compra)
    total_facturado = func.coalesce(func.sum(fp.total), 0)
    rows = db.execute(
        select(
            func.coalesce(e.nit, u.numero_identificacion).label("identificacion"),
            func.coalesce(e.razon_social, _nombre_completo(u)).label("proveedor"),
            func.coalesce(e.ciudad, "Sin ciudad").label("ciudad"),
            func.coalesce(e.direccion, u.direccion, "Sin dirección").label("sucursal"),
            func.count(distinct(p.producto_id)).label("productosSuministrados"),
            func.count(distinct(fp.factura_id)).label("facturasRegistradas"),
            total_facturado.label("totalFacturado"),
            func.count(distinct(comp.compra_id)).label("comprasRealizadas"),
        )
        .select_from(u)
        .outerjoin(e, u.empresa_id == e.empresa_id)
        .outerjoin(p, u.usuario_id == p.usuario_id)
        .outerjoin(fp, and_(u.usuario_id == fp.usuario_id, extract("year", fp.fecha_emision) == anio))
        .outerjoin(comp, and_(u.usuario_id == comp.usuario_id, _pagado_en(anio, comp)))
        .where(_proveedor_filters())
        .group_by(
            u.usuario_id, e.nit, u.numero_identificacion, e.razon_social, u.nombres, u.apellidos,
            e.ciudad, e.direccion, u.direccion,
        )
        .order_by(total_facturado.desc())
    ).all()
    cuentas = [
        {
            "identificacion": r.identificacion,
            "proveedor": r.proveedor,
            "ciudad": r.ciudad,
            "sucursal": r.sucursal,
            "productosSuministrados": _nullable_count(r.productosSuministrados),
            "facturasRegistradas": _nullable_count(r.facturasRegistradas),
            "totalFacturado": _nullable_money(r.totalFacturado),
            "comprasRealizadas": _nullable_count(r.comprasRealizadas),
        }
        for r in rows
    ]
    totales = db.execute(
        select(
            func.count(distinct(u.usuario_id)),
            func.count(distinct(p.producto_id)),
            func.coalesce(func.sum(fp.total), 0),
            func.count(distinct(comp.compra_id)),
        )
        .select_from(u)
        .outerjoin(p, u.usuario_id == p.usuario_id)
        .outerjoin(fp, and_(u.usuario_id == fp.usuario_id, extract("year", fp.fecha_emision) == anio))
        .outerjoin(comp, and_(u.usuario_id == comp.usuario_id, _pagado_en(anio, comp)))
        .where(_proveedor_filters())
    ).one()
    total_general = {
        "totalProveedores": _count(totales[0]),
        "totalProductos": _count(totales[1]),
        "totalFacturadoAnual": _money(totales[2]),
        "totalCompras": _count(totales[3]),
    }
    return {"cuentasPagar": cuentas, "totalGeneral": total_general, "anio": anio}


@router.get("/reporte-compras")
def reporte_compras(db: Session = Depends(get_db)) -> dict:
    """Compras por cliente del año actual (compras PAGADO).

    ``totalSubtotal`` = SUM(subtotal), ``totalIva`` = SUM(subtotal * 0.19),
    ``totalComprado`` = SUM(subtotal * 1.19) (IVA fijo 19 %, no usa compra.iva/total),
    ``promedioCompra`` = AVG(total), ``ultimaCompra`` = MAX(fecha) en ISO-8601.
    Igual que Spring, ``metodo_pago`` forma parte del GROUP BY: un cliente que pagó
    con varios métodos aparece en una fila por método (``metodoPagoFrecuente``).
    Orden: totalComprado DESC.
    """
    anio = _anio()
    u, e, c = Usuario, Empresa, Compra
    total_comprado = func.sum(c.subtotal * IVA_TOTAL)
    rows = db.execute(
        select(
            func.coalesce(e.nit, u.numero_identificacion).label("identificacion"),
            func.coalesce(e.razon_social, _nombre_completo(u)).label("cliente"),
            func.coalesce(e.ciudad, "Sin ciudad").label("ciudad"),
            func.coalesce(e.direccion, u.direccion, "Sin dirección").label("sucursal"),
            func.count(distinct(c.compra_id)).label("totalCompras"),
            func.sum(c.subtotal).label("totalSubtotal"),
            func.sum(c.subtotal * IVA).label("totalIva"),
            total_comprado.label("totalComprado"),
            func.avg(c.total).label("promedioCompra"),
            func.max(c.fecha).label("ultimaCompra"),
            c.metodo_pago.label("metodoPagoFrecuente"),
        )
        .select_from(c)
        .join(u, c.usuario_id == u.usuario_id)
        .outerjoin(e, u.empresa_id == e.empresa_id)
        .where(_pagado_en(anio))
        .group_by(
            u.usuario_id, e.nit, u.numero_identificacion, e.razon_social,
            u.nombres, u.apellidos, e.ciudad, e.direccion, u.direccion, c.metodo_pago,
        )
        .order_by(total_comprado.desc())
    ).all()
    compras = [
        {
            "identificacion": r.identificacion,
            "cliente": r.cliente,
            "ciudad": r.ciudad,
            "sucursal": r.sucursal,
            "totalCompras": _nullable_count(r.totalCompras),
            "totalSubtotal": _nullable_money(r.totalSubtotal),
            "totalIva": _nullable_money(r.totalIva),
            "totalComprado": _nullable_money(r.totalComprado),
            "promedioCompra": _nullable_money(r.promedioCompra),
            "ultimaCompra": _iso_datetime(r.ultimaCompra),
            "metodoPagoFrecuente": r.metodoPagoFrecuente,
        }
        for r in rows
    ]
    totales = db.execute(
        select(
            func.count(distinct(c.compra_id)),
            func.count(distinct(c.usuario_id)),
            func.sum(c.subtotal),
            func.sum(c.subtotal * IVA),
            func.sum(c.subtotal * IVA_TOTAL),
            func.avg(c.total),
        ).where(_pagado_en(anio))
    ).one()
    total_general = {
        "totalCompras": _count(totales[0]),
        "totalClientes": _count(totales[1]),
        "totalSubtotal": _money(totales[2]),
        "totalIva": _money(totales[3]),
        "totalComprado": _money(totales[4]),
        "promedioCompra": _money(totales[5]),
    }
    return {"reporteCompras": compras, "totalGeneral": total_general, "anio": anio}
