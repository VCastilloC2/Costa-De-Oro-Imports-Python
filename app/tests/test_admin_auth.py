"""Acceso servicio-a-servicio (Spring) a las rutas de administración: X-API-Key + X-Admin-Email."""
import pytest

from app.models import Usuario
from app.prediction import repository
from app.tests.test_prediction import _seed_admin

BLOG = {"imagen": "blog/x", "titulo": "T", "descripcion": "D", "historiaCompleta": "H", "activo": True}


def _key(db, *scopes):
    _row, raw = repository.create_api_client(db, "spring-admin", list(scopes), created_by=None)
    return raw


@pytest.fixture
def base(db_session, seeded_roles):
    _seed_admin(db_session)                       # admin@example.com, rol ADMIN
    db_session.add(Usuario(usuario_id=2, correo="cliente@example.com", password="h", rol_id=2, is_enabled=True,
                           account_non_expired=True, account_non_locked=True, credentials_non_expired=True))
    db_session.commit()
    return db_session


def _h(key, email="admin@example.com"):
    headers = {"X-API-Key": key}
    if email:
        headers["X-Admin-Email"] = email
    return headers


def test_lectura_con_admin_read(client, base):
    key = _key(base, repository.SCOPE_ADMIN_READ)
    assert client.get("/admin/blog", headers=_h(key)).status_code == 200
    assert client.get("/admin/blog", headers=_h(key, "ADMIN@example.com")).status_code == 200   # sin mayúsculas


def test_escritura_requiere_admin_write(client, base):
    solo_lectura = _key(base, repository.SCOPE_ADMIN_READ)
    assert client.post("/admin/blog", headers=_h(solo_lectura), json=BLOG).status_code == 403
    escritura = _key(base, repository.SCOPE_ADMIN_WRITE)
    assert client.post("/admin/blog", headers=_h(escritura), json=BLOG).status_code == 201
    assert client.get("/admin/blog", headers=_h(escritura)).status_code == 200     # write implica read


def test_clave_de_predicciones_no_sirve_para_admin(client, base):
    key = _key(base, repository.SCOPE_READ, repository.SCOPE_GENERATE)
    assert client.get("/admin/blog", headers=_h(key)).status_code == 403


@pytest.mark.parametrize("email,status", [(None, 401), ("cliente@example.com", 403), ("nadie@example.com", 403)])
def test_admin_email_obligatorio_y_debe_ser_admin(client, base, email, status):
    key = _key(base, repository.SCOPE_ADMIN_WRITE)
    assert client.get("/admin/blog", headers=_h(key, email)).status_code == status


def test_clave_invalida_o_revocada(client, base):
    assert client.get("/admin/blog", headers=_h("cdo_pk_falsa")).status_code == 401
    row, raw = repository.create_api_client(base, "revocada", [repository.SCOPE_ADMIN_WRITE], created_by=None)
    row.activo = False
    base.commit()
    assert client.get("/admin/blog", headers=_h(raw)).status_code == 401


def test_dashboard_usa_el_admin_de_la_cabecera(client, base):
    key = _key(base, repository.SCOPE_ADMIN_READ)
    body = client.get("/api/graficas/dashboard", headers=_h(key)).json()
    assert body["usuario"]["correo"] == "admin@example.com"


def test_sin_credenciales_401(client, base):
    assert client.get("/admin/blog").status_code == 401


def test_busqueda_con_clave_de_servicio_incluye_clientes_solo_con_admin_email(client, base):
    key = _key(base, repository.SCOPE_ADMIN_READ)
    params = {"q": "cliente", "tipo": "clientes"}
    anonimo_via_spring = client.get("/api/search/universal", params=params, headers={"X-API-Key": key}).json()
    assert anonimo_via_spring["message"] == "No autorizado"
    admin_via_spring = client.get("/api/search/universal", params=params, headers=_h(key)).json()
    assert admin_via_spring["success"] is True
