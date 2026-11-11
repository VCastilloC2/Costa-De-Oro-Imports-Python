"""Gráficas del dashboard consumidas por Spring Boot (Dashboard.js)."""
from datetime import date, datetime

from app.api.v1.endpoints.dashboard_integration import ultimos_meses
from app.models import Compra, FacturaProveedor
from app.prediction import repository
from app.prediction.repository import SCOPE_GENERATE, SCOPE_READ
from app.tests.test_prediction import _seed_admin

URL_IG = "/api/v1/dashboard/ingresos-gastos"
URL_VT = "/api/v1/dashboard/ventas-totales"


def _key(db, scopes):
    _row, raw = repository.create_api_client(db, "spring-dashboard-test", scopes, created_by=None)
    return {"X-API-Key": raw}


def _mes_anterior(hoy: date) -> date:
    return date(hoy.year - 1, 12, 1) if hoy.month == 1 else date(hoy.year, hoy.month - 1, 1)


def _seed(db):
    hoy = date.today()
    previo = _mes_anterior(hoy)
    db.add_all([
        # mes anterior: 100 pagado + 50 pagado; gasto 30
        Compra(compra_id=1, fecha=datetime(previo.year, previo.month, 5), iva=0, subtotal=100, total=100,
               estado="PAGADO", usuario_id=1),
        Compra(compra_id=2, fecha=datetime(previo.year, previo.month, 6), iva=0, subtotal=50, total=50,
               estado="PAGADO", usuario_id=1),
        # mes actual: 200 pagado, 40 cancelado, 10 rechazado, 25 pendiente; gasto 80 (+ uno inactivo)
        Compra(compra_id=3, fecha=datetime(hoy.year, hoy.month, 1), iva=0, subtotal=200, total=200,
               estado="PAGADO", usuario_id=1),
        Compra(compra_id=4, fecha=datetime(hoy.year, hoy.month, 1), iva=0, subtotal=40, total=40,
               estado="CANCELADO", usuario_id=1),
        Compra(compra_id=5, fecha=datetime(hoy.year, hoy.month, 1), iva=0, subtotal=10, total=10,
               estado="RECHAZADO", usuario_id=1),
        Compra(compra_id=6, fecha=datetime(hoy.year, hoy.month, 1), iva=0, subtotal=25, total=25,
               estado="PENDIENTE", usuario_id=1),
        # hace más de 2 años: fuera del rango por defecto
        Compra(compra_id=7, fecha=datetime(hoy.year - 3, 1, 1), iva=0, subtotal=999, total=999,
               estado="PAGADO", usuario_id=1),
        FacturaProveedor(factura_id=1, activo=True, fecha_emision=previo.replace(day=3), total=30),
        FacturaProveedor(factura_id=2, activo=True, fecha_emision=hoy.replace(day=1), total=80),
        FacturaProveedor(factura_id=3, activo=False, fecha_emision=hoy.replace(day=1), total=500),
    ])
    db.commit()


def test_ultimos_meses_cruza_el_anio():
    assert ultimos_meses(3, date(2026, 2, 15)) == [(2025, 12), (2026, 1), (2026, 2)]
    assert ultimos_meses(1, date(2026, 1, 1)) == [(2026, 1)]


def test_requieren_credencial(client):
    assert client.get(URL_IG).status_code == 401
    assert client.get(URL_VT).status_code == 401


def test_requiere_permiso_de_lectura(client, db_session, seeded_roles):
    _seed_admin(db_session)
    assert client.get(URL_IG, headers=_key(db_session, [SCOPE_GENERATE])).status_code == 403


def test_ingresos_gastos_mes_a_mes(client, db_session, seeded_roles):
    _seed_admin(db_session)
    _seed(db_session)
    r = client.get(URL_IG, headers=_key(db_session, [SCOPE_READ]), params={"meses": 12})
    assert r.status_code == 200
    data = r.json()
    assert len(data["categorias"]) == len(data["ingresos"]) == len(data["gastos"]) == 12
    hoy = date.today()
    assert data["categorias"][-1].endswith(str(hoy.year))
    assert data["ingresos"][-2:] == [150.0, 200.0]       # solo PAGADO
    assert data["gastos"][-2:] == [30.0, 80.0]           # solo facturas activas
    assert data["ingresos"][:-2] == [0.0] * 10           # meses sin movimientos en 0
    assert data["totalIngresos"] == 350.0 and data["totalGastos"] == 110.0


def test_ventas_totales_por_estado(client, db_session, seeded_roles):
    _seed_admin(db_session)
    _seed(db_session)
    r = client.get(URL_VT, headers=_key(db_session, [SCOPE_READ]))
    assert r.status_code == 200
    data = r.json()
    assert data["series"] == [350.0, 50.0, 25.0]         # Envíos, Reembolsos, Pedidos
    assert data["totalVentas"] == 425.0
    assert data["labels"][0].startswith("Envíos $350.00 (82%)")


def test_meses_fuera_de_rango_es_422(client, db_session, seeded_roles):
    _seed_admin(db_session)
    assert client.get(URL_IG, headers=_key(db_session, [SCOPE_READ]), params={"meses": 0}).status_code == 422
