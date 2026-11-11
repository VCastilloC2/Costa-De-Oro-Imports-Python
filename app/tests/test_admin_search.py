"""Paridad de GET /api/search/universal con SearchController/SearchServiceImpl de Spring."""
import json
from datetime import date

import pytest

from app.core.config import settings
from app.models.entities import Categoria, Empresa, Historia, Producto, Rol, Usuario
from app.tests.test_prediction import _seed_admin

URL = "/api/search/universal"
ITEM_KEYS = {"id", "type", "titulo", "subtitulo", "descripcion", "imagen", "icono", "url", "badge", "badgeClass"}
RESPONSE_KEYS = {"productos", "categorias", "clientes", "proveedores", "blog", "totalResults", "query", "success", "message"}


@pytest.fixture
def headers(db_session, seeded_roles):
    db_session.add(Rol(rol_id=3, rol="PROVEEDOR"))
    db_session.commit()
    return _seed_admin(db_session)


@pytest.fixture
def seeded(db_session, headers, monkeypatch):
    monkeypatch.setattr(settings, "cloud_name", "democloud")
    db = db_session
    db.add_all([
        Producto(producto_id=10, nombre="Cerveza Club Colombia", marca="Bavaria", pais="Colombia",
                 descripcion="x" * 150, precio=5000, stock=5, activo=True, codigo_producto="COD-10",
                 imagen="productos/club"),
        Producto(producto_id=11, nombre="Lager Roja", marca="CLUB Premium", pais=None, descripcion=None,
                 precio=4000, stock=0, activo=True, codigo_producto="COD-11",
                 imagen="https://cdn.example.com/roja.png"),
        Producto(producto_id=12, nombre="Club Inactiva", marca="Bavaria", pais="Colombia",
                 precio=1, stock=1, activo=False, codigo_producto="COD-12"),
        Producto(producto_id=13, nombre="Otra", marca="Marca", pais="Peru", descripcion="nada que ver",
                 precio=1, stock=1, activo=True, codigo_producto="COD-13"),
    ])
    db.add_all([
        Categoria(categoria_id=1, nombre="Cervezas Club", descripcion="Categoría club", imagen=None, activo=False),
        Categoria(categoria_id=2, nombre="Vinos", descripcion="club en descripción no cuenta"),
    ])
    db.add(Empresa(empresa_id=1, nit="900", telefono="111", correo="e@x.com", razon_social="Club Distribuciones SAS",
                   ciudad="Bogotá", direccion="Calle 1"))
    db.add(Empresa(empresa_id=2, nit="901", telefono="112", correo="e2@x.com", razon_social="Sin Coincidencia",
                   ciudad="Bogotá", direccion="Calle 2"))
    db.add_all([
        Usuario(usuario_id=20, correo="ana.club@example.com", nombres="Ana", apellidos="Pérez", telefono="300",
                password="$2a$10$secret-hash", rol_id=2, account_non_locked=True),
        Usuario(usuario_id=21, correo="bloqueado@example.com", nombres="Club", apellidos="Bloqueado",
                password="hash", rol_id=2, account_non_locked=False),
        Usuario(usuario_id=22, correo="prov@example.com", nombres="Pedro", apellidos="Prov", telefono="301",
                password="hash2", rol_id=3, account_non_locked=True, empresa_id=1),
        Usuario(usuario_id=23, correo="club.prov@example.com", nombres="Clubber", apellidos=None,
                password="hash3", rol_id=3, account_non_locked=True, empresa_id=None),
        Usuario(usuario_id=24, correo="club2@example.com", nombres="Luis", apellidos="Club",
                password="hash4", rol_id=3, account_non_locked=True, empresa_id=2),
    ])
    db.add_all([
        Historia(historia_id=1, fecha=date(2024, 1, 1), is_enabled=True, titulo="Historia del CLUB",
                 descripcion="Texto", historia_completa="...", imagen="blog/club.jpg"),
        Historia(historia_id=2, fecha=date(2024, 1, 2), is_enabled=False, titulo="Club oculto",
                 descripcion="Texto", historia_completa="...", imagen="blog/x.jpg"),
    ])
    db.commit()
    return headers


def test_publica_sin_datos_personales_para_anonimos(client, seeded):
    """Como SecurityConfig de Spring: pública para catálogo/blog; clientes y proveedores solo ADMIN.

    Corrige la fuga de Spring: allí un anónimo sin ``tipo`` recibía clientes y proveedores.
    """
    for headers in ({}, {"Authorization": "Bearer token-invalido"}):
        body = client.get(URL, params={"q": "club"}, headers=headers).json()
        assert body["success"] is True
        assert body["productos"] and body["categorias"] and body["blog"]
        assert body["clientes"] == [] and body["proveedores"] == []
        assert "ana.club@example.com" not in str(body)


@pytest.mark.parametrize("tipo", ["clientes", "PROVEEDORES"])
def test_tipos_privados_no_autorizados_sin_admin(client, seeded, tipo):
    body = client.get(URL, params={"q": "club", "tipo": tipo}).json()
    assert body["success"] is False and body["message"] == "No autorizado" and body["totalResults"] == 0


def test_no_admin_autenticado_tampoco_ve_clientes(client, seeded, db_session):
    from app.core.security import create_token
    cliente = {"Authorization": f"Bearer {create_token('20', 'PERSONA_NATURAL')}"}
    db_session.get(Usuario, 20).is_enabled = True
    db_session.commit()
    body = client.get(URL, params={"q": "club"}, headers=cliente).json()
    assert body["clientes"] == [] and body["proveedores"] == [] and body["productos"]


def test_full_contract_and_matching(client, seeded):
    res = client.get(URL, params={"q": "cLuB"}, headers=seeded)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == RESPONSE_KEYS
    assert body["success"] is True
    assert body["message"] == "Búsqueda completada"
    assert body["query"] == "cLuB"
    for group in ("productos", "categorias", "clientes", "proveedores", "blog"):
        for item in body[group]:
            assert set(item) == ITEM_KEYS

    productos = body["productos"]
    assert [p["id"] for p in productos] == [10, 11]  # inactiva excluida, orden por id
    p10, p11 = productos
    assert p10 == {
        "id": 10, "type": "producto", "titulo": "Cerveza Club Colombia", "subtitulo": "Bavaria - Colombia",
        "descripcion": "x" * 100 + "...",
        "imagen": "https://res.cloudinary.com/democloud/image/upload/productos/club",
        "icono": None, "url": "/ver?id=COD-10", "badge": "En Stock", "badgeClass": "badge-success",
    }
    assert p11["subtitulo"] == "CLUB Premium - null"  # concatenación Java con null
    assert p11["descripcion"] == ""
    assert p11["imagen"] == "https://cdn.example.com/roja.png"
    assert (p11["badge"], p11["badgeClass"]) == ("Agotado", "badge-danger")

    # Categorías: solo por nombre, sin filtrar activo (igual que Spring)
    assert body["categorias"] == [{
        "id": 1, "type": "categoria", "titulo": "Cervezas Club", "subtitulo": "Categoría",
        "descripcion": "Categoría club", "imagen": None, "icono": "ri-list-unordered",
        "url": "/productos?categoria=1", "badge": "Categoría", "badgeClass": "badge-info",
    }]

    # Clientes: correo coincide, bloqueado excluido, admin excluido por rol
    assert body["clientes"] == [{
        "id": 20, "type": "cliente", "titulo": "Ana Pérez", "subtitulo": "ana.club@example.com",
        "descripcion": "Teléfono: 300", "imagen": None, "icono": "ri-user-line",
        "url": "/admin/clientes/20", "badge": "Cliente", "badgeClass": "badge-primary",
    }]

    # Proveedores: razón social / apellidos; sin empresa -> excluido (INNER JOIN implícito de JPQL)
    proveedores = body["proveedores"]
    assert [p["id"] for p in proveedores] == [22, 24]
    assert proveedores[0]["titulo"] == "Club Distribuciones SAS"
    assert proveedores[0]["descripcion"] == "Teléfono: 301"
    assert proveedores[0]["url"] == "/admin/proveedores/22"
    assert (proveedores[0]["badge"], proveedores[0]["badgeClass"], proveedores[0]["icono"]) == (
        "Proveedor", "badge-warning", "ri-store-2-line")
    assert proveedores[1]["titulo"] == "Sin Coincidencia"
    assert proveedores[1]["descripcion"] == "Teléfono: "

    assert body["blog"] == [{
        "id": 1, "type": "blog", "titulo": "Historia del CLUB", "subtitulo": "Artículo de Blog",
        "descripcion": "Texto", "imagen": "https://res.cloudinary.com/democloud/image/upload/blog/club.jpg",
        "icono": "ri-news-line", "url": "/blog/info?id=1", "badge": "Blog", "badgeClass": "badge-secondary",
    }]
    assert body["totalResults"] == 2 + 1 + 1 + 2 + 1


def test_no_password_anywhere(client, seeded):
    raw = client.get(URL, params={"q": "example"}, headers=seeded).text
    assert "password" not in raw.lower()
    for secret in ("$2a$10$secret-hash", "hash2", "hash3", "hash4"):
        assert secret not in raw
    assert json.loads(raw)["clientes"]


def test_tipo_filter_case_insensitive(client, seeded):
    body = client.get(URL, params={"q": "club", "tipo": "PROVEEDORES"}, headers=seeded).json()
    assert body["success"] is True
    assert body["productos"] == body["categorias"] == body["clientes"] == body["blog"] == []
    assert len(body["proveedores"]) == 2
    assert body["totalResults"] == 2

    unknown = client.get(URL, params={"q": "club", "tipo": "otro"}, headers=seeded).json()
    assert unknown["success"] is True and unknown["totalResults"] == 0


@pytest.mark.parametrize("limit,expected", [(1, 1), (0, 1), (-5, 1), (500, 2)])
def test_limit_clamped_per_type(client, seeded, limit, expected):
    body = client.get(URL, params={"q": "club", "tipo": "productos", "limit": limit}, headers=seeded).json()
    assert len(body["productos"]) == expected


def test_limit_max_50(client, db_session, headers):
    db_session.add_all([Categoria(categoria_id=i, nombre=f"Cat club {i}", descripcion="d") for i in range(1, 61)])
    db_session.commit()
    body = client.get(URL, params={"q": "club", "limit": 999}, headers=headers).json()
    assert len(body["categorias"]) == 50
    default = client.get(URL, params={"q": "club"}, headers=headers).json()
    assert len(default["categorias"]) == 10


@pytest.mark.parametrize("params,query", [({}, None), ({"q": ""}, ""), ({"q": "   "}, "   "), ({"q": " a "}, " a ")])
def test_short_or_empty_query(client, headers, params, query):
    res = client.get(URL, params=params, headers=headers)
    assert res.status_code == 200
    assert res.json() == {
        "productos": [], "categorias": [], "clientes": [], "proveedores": [], "blog": [],
        "totalResults": 0, "query": query, "success": False,
        "message": "El término de búsqueda debe tener al menos 2 caracteres",
    }


def test_query_too_long(client, headers):
    body = client.get(URL, params={"q": "a" * 101}, headers=headers).json()
    assert body["success"] is False
    assert body["totalResults"] == 0
    assert len(body["query"]) == 100


def test_wildcards_literal_in_containing_queries(client, seeded):
    body = client.get(URL, params={"q": "%%", "tipo": "productos"}, headers=seeded).json()
    assert body["success"] is True and body["productos"] == []
