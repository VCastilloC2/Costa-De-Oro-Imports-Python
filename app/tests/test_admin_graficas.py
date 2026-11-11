"""/api/graficas/* con el mismo contrato que DashboardRestController de Spring."""
from datetime import date, datetime

import pytest

from app.api.v1.endpoints.admin_graficas import _JavaRandom, _con_subpicos, _menos_meses
from app.models import Categoria, Compra, DetalleVenta, Empresa, FacturaProveedor, Producto, Rol, Usuario
from app.tests.test_prediction import _seed_admin

HOY = date.today()


def _mes_actual(dia=1):
    return datetime(HOY.year, HOY.month, dia)


@pytest.fixture
def datos(db_session, seeded_roles):
    headers = _seed_admin(db_session)
    db_session.add(Rol(rol_id=3, rol="PERSONA_JURIDICA"))
    db_session.add_all([
        Empresa(empresa_id=1, activo=True, nit="900", telefono="1", correo="e1@x.co", razon_social="Bar Uno",
                ciudad="Bogota", direccion="d"),
        Empresa(empresa_id=2, activo=True, nit="901", telefono="2", correo="e2@x.co", razon_social="Bar Dos",
                ciudad="Ciudad Inexistente", direccion="d"),
    ])
    db_session.add_all([
        Usuario(usuario_id=10, correo="c1@x.co", password="hash-secreto", rol_id=3, empresa_id=1,
                nombres="Ana", apellidos="Ruiz", is_enabled=True),
        Usuario(usuario_id=11, correo="c2@x.co", password="hash-secreto", rol_id=2, empresa_id=2,
                nombres="Luis", apellidos="Paz", is_enabled=True),
    ])
    db_session.add_all([
        Categoria(categoria_id=1, nombre="Cerveza", descripcion="c", activo=True),
        Categoria(categoria_id=2, nombre="Whisky", descripcion="w", activo=True),
        Producto(producto_id=1, nombre="Pilsen", precio=3000, stock=50, activo=True, categoria_id=1,
                 imagen="https://img/pilsen.png"),
        Producto(producto_id=2, nombre="Old Parr", precio=90000, stock=5, activo=True, categoria_id=2),
        Producto(producto_id=3, nombre="Inactivo", precio=1, stock=999, activo=False, categoria_id=2),
    ])
    db_session.add_all([
        Compra(compra_id=1, fecha=_mes_actual(2), iva=0, subtotal=30000, total=30000, estado="PAGADO", usuario_id=10),
        Compra(compra_id=2, fecha=_mes_actual(3), iva=0, subtotal=90000, total=90000, estado="PAGADO", usuario_id=11),
        Compra(compra_id=3, fecha=_mes_actual(4), iva=0, subtotal=5000, total=5000, estado="PENDIENTE", usuario_id=10),
        Compra(compra_id=4, fecha=datetime(HOY.year - 3, 1, 1), iva=0, subtotal=7000, total=7000,
               estado="PAGADO", usuario_id=10),
    ])
    db_session.add_all([
        DetalleVenta(detalle_venta_id=1, cantidad=10, precio_unitario=3000, subtotal=30000, compra_id=1, producto_id=1),
        DetalleVenta(detalle_venta_id=2, cantidad=1, precio_unitario=90000, subtotal=90000, compra_id=2, producto_id=2),
        DetalleVenta(detalle_venta_id=3, cantidad=99, precio_unitario=1, subtotal=99, compra_id=3, producto_id=2),
    ])
    db_session.add(FacturaProveedor(factura_id=1, activo=True, fecha_emision=HOY.replace(day=1), total=20000))
    db_session.commit()
    return headers


def test_todas_requieren_admin(client):
    for ruta in ("dashboard", "ingresos-gastos", "ventas-totales", "stock-compras", "mapa-ventas", "historico-ventas"):
        assert client.get(f"/api/graficas/{ruta}").status_code == 401


def test_dashboard_contrato_y_sin_password(client, datos):
    r = client.get("/api/graficas/dashboard", headers=datos)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"usuario", "urlImagenUsuario", "ingresoAnual", "comprasAnuales", "totalClientes",
                         "estadisticas", "productosMasVendidos", "comprasRecientes"}
    assert "password" not in r.text and "hash-secreto" not in r.text
    assert body["usuario"]["correo"] == "admin@example.com"
    assert body["totalClientes"] == 2                      # PERSONA_JURIDICA + PERSONA_NATURAL (no ADMIN)
    assert body["ingresoAnual"] == 120000.0 and body["comprasAnuales"] == 2   # solo PAGADO del año actual
    top = body["productosMasVendidos"]
    assert [p["nombre"] for p in top] == ["Pilsen", "Old Parr"]  # la compra PENDIENTE no cuenta
    assert top[0] == {"productoId": 1, "nombre": "Pilsen", "imagen": "https://img/pilsen.png",
                      "precio": 3000.0, "totalVentas": 10}
    recientes = body["comprasRecientes"]
    assert recientes[0]["numeroPedido"] == "ORD-0003" and recientes[0]["estado"] == "Pendiente"
    assert recientes[0]["claseEstado"] == "td__estados pendiente" and recientes[0]["nombreCliente"] == "Ana Ruiz"
    est = body["estadisticas"]
    assert {"ingresosTotales", "progresoStock", "variacionBeneficio", "objetivoStock"} <= set(est)
    assert est["stockDisponible"] == 55                    # el producto inactivo no suma


def test_ingresos_gastos_y_ventas_totales(client, datos):
    ig = client.get("/api/graficas/ingresos-gastos", headers=datos).json()
    assert len(ig["categorias"]) == 12 and ig["ingresos"][-1] == 120000.0 and ig["gastos"][-1] == 20000.0
    vt = client.get("/api/graficas/ventas-totales", headers=datos).json()
    assert vt["series"] == [120000.0, 0.0, 5000.0] and vt["totalVentas"] == 125000.0
    assert vt["labels"][0].startswith("Envíos $120,000.00")


def test_stock_compras(client, datos):
    body = client.get("/api/graficas/stock-compras", headers=datos).json()
    assert body == {"categorias": ["Cerveza", "Whisky"], "ventas": [10, 1], "stock": [50, 5]}


def test_mapa_ventas_solo_ciudades_con_coordenadas(client, datos):
    body = client.get("/api/graficas/mapa-ventas", headers=datos).json()
    assert body == {"ventasPorCiudad": [{"ciudad": "Bogota", "ventas": 10, "latitud": 4.7110,
                                         "longitud": -74.0721, "empresasCompradoras": 1}]}


def test_historico_ventas(client, datos):
    body = client.get("/api/graficas/historico-ventas", headers=datos).json()
    assert body["maxVenta"] == 120000.0 and body["minVenta"] == 7000.0
    assert body["categorias"][0] == (HOY.year - 3) * 1000 and body["categorias"][-1] == HOY.year * 1000
    assert len(body["series"]) == 2 + 10                   # 2 años + 10 puntos intermedios


def test_java_random_identico_a_java():
    r = _JavaRandom(42)
    assert r.next_double() == 0.7275636800328681 and r.next_double() == 0.6832234717598454


def test_subpicos_deterministas():
    s1, c1 = _con_subpicos([100.0, 200.0], [2024, 2025])
    s2, _ = _con_subpicos([100.0, 200.0], [2024, 2025])
    assert s1 == s2 and c1[0] == 2024000 and c1[1] == 2024090 and c1[-1] == 2025000


def test_menos_meses_ajusta_fin_de_mes():
    assert _menos_meses(datetime(2026, 8, 31, 10), 6) == datetime(2026, 2, 28, 10)
    assert _menos_meses(datetime(2026, 1, 15), 12) == datetime(2025, 1, 15)
