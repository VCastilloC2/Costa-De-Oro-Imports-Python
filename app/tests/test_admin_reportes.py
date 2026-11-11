"""Reportes /api/reportes/* (port de GenerarReporteRestController de Spring)."""
from datetime import date, datetime

import pytest
from pytest import approx

from app.api.v1.endpoints.admin_reportes import _iso_datetime, _mysql_div_pct
from app.models.entities import (
    Categoria, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor, Producto, Rol, Usuario,
)
from app.tests.test_prediction import _seed_admin

BASE = "/api/reportes"
PATHS = [
    "ventas-clientes", "ventas-producto", "ventas-cliente-producto",
    "rentabilidad-producto", "cuentas-pagar", "reporte-compras",
]
Y = date.today().year


def _seed(db):
    db.add(Rol(rol_id=3, rol="PROVEEDOR"))
    db.add_all([
        Empresa(empresa_id=1, nit="900", telefono="1", correo="bar@x.co", razon_social="Bar Uno SAS",
                ciudad="Cali", direccion="Cra 1"),
        Empresa(empresa_id=2, nit="800", telefono="2", correo="prov@x.co", razon_social="Cerveceria Prov",
                ciudad="Bogota", direccion="Cl 2"),
    ])
    db.add_all([
        # cliente natural sin apellidos -> "Ana " (CONCAT con COALESCE(apellidos, ''))
        Usuario(usuario_id=2, correo="ana@x.co", nombres="Ana", numero_identificacion="111",
                direccion="Calle Ana", rol_id=2, is_enabled=True),
        # cliente con empresa
        Usuario(usuario_id=3, correo="luis@x.co", nombres="Luis", apellidos="Diaz", numero_identificacion="222",
                empresa_id=1, rol_id=2, is_enabled=True),
        # proveedor activo con empresa
        Usuario(usuario_id=4, correo="p1@x.co", nombres="Prov", apellidos="Uno", numero_identificacion="444",
                empresa_id=2, rol_id=3, is_enabled=True),
        # proveedor deshabilitado -> excluido de cuentas-pagar
        Usuario(usuario_id=5, correo="p2@x.co", nombres="Off", numero_identificacion="555", rol_id=3, is_enabled=False),
        # proveedor activo sin empresa ni dirección
        Usuario(usuario_id=6, correo="p3@x.co", nombres="Pedro", apellidos="Paz", numero_identificacion="333",
                rol_id=3, is_enabled=True),
    ])
    db.add(Categoria(categoria_id=1, nombre="Cervezas", descripcion="d"))
    db.add_all([
        Producto(producto_id=1, codigo_producto="P1", nombre="Lager", tipo="UNIDAD", precio=1, categoria_id=1, usuario_id=4),
        Producto(producto_id=2, codigo_producto="P2", nombre="Stout", tipo="CAJA", precio=1, categoria_id=1),
        Producto(producto_id=3, codigo_producto="P3", nombre="Sin cat", tipo="PACK", precio=1, usuario_id=6),
        Producto(producto_id=4, codigo_producto="P4", nombre="IPA", tipo="UNIDAD", precio=1, categoria_id=1, usuario_id=4),
    ])
    db.add_all([
        Compra(compra_id=10, usuario_id=2, fecha=datetime(Y, 1, 10, 10), subtotal=100, iva=19, total=119,
               estado="PAGADO", metodo_pago="NEQUI"),
        Compra(compra_id=11, usuario_id=2, fecha=datetime(Y, 2, 10, 12, 30, 15), subtotal=200, iva=38, total=238,
               estado="PAGADO", metodo_pago="NEQUI"),
        Compra(compra_id=12, usuario_id=3, fecha=datetime(Y, 3, 1), subtotal=1000, iva=190, total=1190,
               estado="PAGADO", metodo_pago="PSE"),
        Compra(compra_id=13, usuario_id=3, fecha=datetime(Y, 3, 2), subtotal=50, iva=9.5, total=59.5,
               estado="PAGADO", metodo_pago="NEQUI"),
        Compra(compra_id=17, usuario_id=4, fecha=datetime(Y, 4, 1), subtotal=10, iva=1.9, total=11.9,
               estado="PAGADO", metodo_pago="TRANSFERENCIA"),
        # excluidas: no PAGADO u otro año
        Compra(compra_id=14, usuario_id=2, fecha=datetime(Y, 1, 5), subtotal=5000, iva=950, total=5950,
               estado="PENDIENTE", metodo_pago="NEQUI"),
        Compra(compra_id=15, usuario_id=3, fecha=datetime(Y - 1, 6, 1), subtotal=7000, iva=1330, total=8330,
               estado="PAGADO", metodo_pago="PSE"),
        Compra(compra_id=16, usuario_id=2, fecha=datetime(Y, 1, 6), subtotal=300, iva=57, total=357,
               estado="CANCELADO", metodo_pago="NEQUI"),
        Compra(compra_id=18, usuario_id=4, fecha=datetime(Y, 1, 6), subtotal=40, iva=7.6, total=47.6,
               estado="RECHAZADO", metodo_pago="PSE"),
    ])
    db.add_all([
        DetalleVenta(detalle_venta_id=1, compra_id=10, producto_id=1, cantidad=2, subtotal=100),
        DetalleVenta(detalle_venta_id=2, compra_id=11, producto_id=2, cantidad=1, subtotal=200),
        DetalleVenta(detalle_venta_id=3, compra_id=12, producto_id=1, cantidad=10, subtotal=1000),
        DetalleVenta(detalle_venta_id=4, compra_id=13, producto_id=3, cantidad=1, subtotal=50),
        DetalleVenta(detalle_venta_id=5, compra_id=14, producto_id=1, cantidad=99, subtotal=5000),
        DetalleVenta(detalle_venta_id=6, compra_id=15, producto_id=2, cantidad=70, subtotal=7000),
    ])
    db.add_all([
        FacturaProveedor(factura_id=1, usuario_id=4, activo=True, fecha_emision=date(Y, 1, 2), total=300),
        FacturaProveedor(factura_id=2, usuario_id=4, activo=False, fecha_emision=date(Y, 2, 2), total=100),
        FacturaProveedor(factura_id=3, usuario_id=4, activo=True, fecha_emision=date(Y - 1, 2, 2), total=999),
        FacturaProveedor(factura_id=4, usuario_id=5, activo=True, fecha_emision=date(Y, 2, 2), total=500),
    ])
    db.add_all([
        DetalleFactura(detalle_factura_id=1, factura_id=1, producto_id=1, precio_compra=40, cantidad=10, subtotal=400),
        DetalleFactura(detalle_factura_id=2, factura_id=2, producto_id=1, precio_compra=50, cantidad=2, subtotal=100),
    ])
    db.commit()


@pytest.fixture
def headers(db_session, seeded_roles):
    h = _seed_admin(db_session)
    _seed(db_session)
    return h


def _get(client, headers, path):
    r = client.get(f"{BASE}/{path}", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["anio"] == Y
    return data


@pytest.mark.parametrize("path", PATHS)
def test_requiere_autenticacion(client, path):
    assert client.get(f"{BASE}/{path}").status_code == 401


def test_helpers_semantica_mysql():
    assert _mysql_div_pct(1, 3) == approx(33.33)          # DECIMAL: 0.3333 * 100
    assert _mysql_div_pct(1200, 2200) == approx(54.55)
    assert _iso_datetime(datetime(2026, 3, 1)) == "2026-03-01T00:00:00"
    assert _iso_datetime(datetime(2026, 3, 1, 1, 2, 3, 500000)) == "2026-03-01T01:02:03.5"
    assert _iso_datetime(None) is None


def test_ventas_clientes(client, headers):
    data = _get(client, headers, "ventas-clientes")
    assert set(data) == {"ventasClientes", "totalGeneral", "anio"}
    filas = data["ventasClientes"]
    assert set(filas[0]) == {"identificacion", "cliente", "numeroComprobantes", "valorBruto", "impuestoCargo", "total"}
    assert [(f["identificacion"], f["cliente"], f["numeroComprobantes"]) for f in filas] == [
        ("900", "Luis Diaz", 2), ("111", "Ana ", 2), ("800", "Prov Uno", 1),
    ]
    assert filas[0]["valorBruto"] == approx(1050) and filas[0]["impuestoCargo"] == approx(199.5)
    assert filas[0]["total"] == approx(1249.5)
    assert filas[1]["total"] == approx(357) and isinstance(filas[1]["numeroComprobantes"], int)
    assert data["totalGeneral"] == {
        "valorBrutoTotal": approx(1360), "impuestoCargoTotal": approx(258.4), "totalGeneral": approx(1618.4),
    }


def test_ventas_producto(client, headers):
    data = _get(client, headers, "ventas-producto")
    assert set(data) == {"ventasProducto", "totalGeneral", "anio"}
    assert data["ventasProducto"] == [
        {"codigoProducto": "P1", "nombreProducto": "Lager", "referenciaFabrica": "Cerveceria Prov",
         "cantidadVendida": 12, "valorBruto": 1100.0, "impuestoCargo": 209.0, "total": 1309.0},
        {"codigoProducto": "P2", "nombreProducto": "Stout", "referenciaFabrica": "Sin proveedor",
         "cantidadVendida": 1, "valorBruto": 200.0, "impuestoCargo": 38.0, "total": 238.0},
        {"codigoProducto": "P3", "nombreProducto": "Sin cat", "referenciaFabrica": "Sin proveedor",
         "cantidadVendida": 1, "valorBruto": 50.0, "impuestoCargo": 9.5, "total": 59.5},
    ]
    assert data["totalGeneral"] == {"valorBrutoTotal": 1350.0, "impuestoCargoTotal": 256.5, "totalGeneral": 1606.5}


def test_ventas_cliente_producto(client, headers):
    data = _get(client, headers, "ventas-cliente-producto")
    assert set(data) == {"ventasClienteProducto", "totalGeneral", "anio"}
    filas = data["ventasClienteProducto"]
    assert set(filas[0]) == {"identificacion", "cliente", "codigoProducto", "nombreProducto", "referenciaFabrica",
                             "cantidadVendida", "valorBruto", "impuestoCargo", "total"}
    assert [(f["identificacion"], f["cliente"], f["nombreProducto"], f["cantidadVendida"], f["valorBruto"])
            for f in filas] == [
        ("111", "Ana ", "Lager", 2, 100.0),
        ("111", "Ana ", "Stout", 1, 200.0),
        ("900", "Bar Uno SAS", "Lager", 10, 1000.0),
        ("900", "Bar Uno SAS", "Sin cat", 1, 50.0),
    ]
    assert filas[2]["impuestoCargo"] == 190.0 and filas[2]["total"] == 1190.0
    assert data["totalGeneral"] == {"valorBrutoTotal": 1350.0, "impuestoCargoTotal": 256.5, "totalGeneral": 1606.5}


def test_rentabilidad_producto(client, headers):
    data = _get(client, headers, "rentabilidad-producto")
    assert set(data) == {"rentabilidadProducto", "totalGeneral", "anio"}
    # P1: 2 líneas de venta x 2 líneas de factura (fan-out del LEFT JOIN de Spring)
    # P3 sin categoría queda fuera (INNER JOIN categoria)
    assert data["rentabilidadProducto"] == [
        {"tipo": "UNIDAD", "codigoProducto": "P1", "nombreProducto": "Lager", "referenciaFabrica": "Cerveceria Prov",
         "categoria": "Cervezas", "cantidadVendida": 24, "ventasBrutasTotales": 2200.0, "costosTotales": 1000.0,
         "utilidadPesos": 1200.0, "porcentajeUtilidad": approx(54.55), "porcentajeRentabilidad": approx(120.0)},
        {"tipo": "CAJA", "codigoProducto": "P2", "nombreProducto": "Stout", "referenciaFabrica": "Sin proveedor",
         "categoria": "Cervezas", "cantidadVendida": 1, "ventasBrutasTotales": 200.0, "costosTotales": 0.0,
         "utilidadPesos": 200.0, "porcentajeUtilidad": approx(100.0), "porcentajeRentabilidad": 0.0},
    ]
    # totales: sin join de categoría -> incluye P3 (50)
    assert data["totalGeneral"] == {"ventasBrutasTotales": 2450.0, "costosTotales": 1000.0}


def test_cuentas_pagar(client, headers):
    data = _get(client, headers, "cuentas-pagar")
    assert set(data) == {"cuentasPagar", "totalGeneral", "anio"}
    # Prov 4: 2 productos x 2 facturas del año x 1 compra -> SUM(fp.total) duplicado (800), como en MySQL.
    # Factura inactiva cuenta; factura de otro año y proveedor deshabilitado no.
    assert data["cuentasPagar"] == [
        {"identificacion": "800", "proveedor": "Cerveceria Prov", "ciudad": "Bogota", "sucursal": "Cl 2",
         "productosSuministrados": 2, "facturasRegistradas": 2, "totalFacturado": 800.0, "comprasRealizadas": 1},
        {"identificacion": "333", "proveedor": "Pedro Paz", "ciudad": "Sin ciudad", "sucursal": "Sin dirección",
         "productosSuministrados": 1, "facturasRegistradas": 0, "totalFacturado": 0.0, "comprasRealizadas": 0},
    ]
    assert data["totalGeneral"] == {
        "totalProveedores": 2, "totalProductos": 3, "totalFacturadoAnual": 800.0, "totalCompras": 1,
    }


def test_reporte_compras(client, headers):
    data = _get(client, headers, "reporte-compras")
    assert set(data) == {"reporteCompras", "totalGeneral", "anio"}
    filas = data["reporteCompras"]
    assert set(filas[0]) == {"identificacion", "cliente", "ciudad", "sucursal", "totalCompras", "totalSubtotal",
                             "totalIva", "totalComprado", "promedioCompra", "ultimaCompra", "metodoPagoFrecuente"}
    # metodo_pago está en el GROUP BY: Luis aparece una vez por método
    assert [(f["identificacion"], f["cliente"], f["metodoPagoFrecuente"], f["totalCompras"]) for f in filas] == [
        ("900", "Bar Uno SAS", "PSE", 1), ("111", "Ana ", "NEQUI", 2),
        ("900", "Bar Uno SAS", "NEQUI", 1), ("800", "Cerveceria Prov", "TRANSFERENCIA", 1),
    ]
    ana = filas[1]
    assert (ana["ciudad"], ana["sucursal"]) == ("Sin ciudad", "Calle Ana")
    assert ana["totalSubtotal"] == approx(300) and ana["totalIva"] == approx(57)
    assert ana["totalComprado"] == approx(357) and ana["promedioCompra"] == approx(178.5)
    assert ana["ultimaCompra"] == f"{Y}-02-10T12:30:15"
    assert filas[0]["ultimaCompra"] == f"{Y}-03-01T00:00:00" and filas[0]["sucursal"] == "Cra 1"
    t = data["totalGeneral"]
    assert set(t) == {"totalCompras", "totalClientes", "totalSubtotal", "totalIva", "totalComprado", "promedioCompra"}
    assert (t["totalCompras"], t["totalClientes"]) == (5, 3)
    assert t["totalSubtotal"] == approx(1360) and t["totalIva"] == approx(258.4)
    assert t["totalComprado"] == approx(1618.4) and t["promedioCompra"] == approx(323.68)


def test_sin_datos_devuelve_listas_vacias_y_ceros(client, db_session, seeded_roles):
    h = _seed_admin(db_session)
    data = _get(client, h, "ventas-clientes")
    assert data["ventasClientes"] == []
    assert data["totalGeneral"] == {"valorBrutoTotal": 0.0, "impuestoCargoTotal": 0.0, "totalGeneral": 0.0}
    t = _get(client, h, "reporte-compras")["totalGeneral"]
    assert t["totalCompras"] == 0 and t["promedioCompra"] == 0.0
