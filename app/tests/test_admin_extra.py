"""Clientes, proveedores, blog, PQRS y reseñas con los contratos de los controladores de Spring."""
from datetime import date, datetime

import pytest

from app.models import (Comentario, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor, Historia,
                        Peticion, Producto, Rol, Usuario)
from app.tests.test_prediction import _seed_admin

HOY = date.today()


@pytest.fixture(autouse=True)
def _sin_cloudinary(monkeypatch):
    """Sin CLOUD_NAME, cloudinary_url devuelve el public_id tal cual: tests independientes del entorno."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "cloud_name", None)


@pytest.fixture
def admin(db_session, seeded_roles):
    db_session.add_all([Rol(rol_id=3, rol="PERSONA_JURIDICA"), Rol(rol_id=4, rol="PROVEEDOR")])
    db_session.commit()
    return _seed_admin(db_session)


CLIENTE = {"tipoIdentificacion": "CC", "numeroIdentificacion": "123", "nombres": "Ana", "apellidos": "Ruiz",
           "telefono": "3001", "correo": "ana@x.co", "direccion": "Calle 1", "password": "Secreta123",
           "imagen": "perfil/ana"}


def test_rutas_requieren_admin(client):
    for metodo, ruta in [("get", "/admin/clientes"), ("get", "/admin/provedores"), ("get", "/admin/blog"),
                         ("get", "/admin/pqrs"), ("get", "/admin/resenna"), ("get", "/admin/principal"),
                         ("post", "/admin/clientes"), ("delete", "/admin/blog/1")]:
        assert getattr(client, metodo)(ruta).status_code == 401, ruta


# --------------------------------------------------------------------------- clientes
def test_crear_cliente_rol_segun_documento_y_sin_password(client, db_session, admin):
    r = client.post("/admin/clientes", headers=admin, json=CLIENTE)
    assert r.status_code == 201 and r.json()["success"] is True and r.json()["mensaje"] == "Usuario creado exitosamente"
    nit = {**CLIENTE, "correo": "bar@x.co", "telefono": "3002", "tipoIdentificacion": "NIT"}
    assert client.post("/admin/clientes", headers=admin, json=nit).status_code == 201
    roles = {u.correo: u.rol_id for u in db_session.query(Usuario).all()}
    assert roles["ana@x.co"] == 2 and roles["bar@x.co"] == 3          # PERSONA_NATURAL / PERSONA_JURIDICA
    guardado = db_session.query(Usuario).filter_by(correo="ana@x.co").one()
    assert guardado.password != "Secreta123"                         # se guarda el hash

    detalle = client.get(f"/admin/clientes/{guardado.usuario_id}", headers=admin)
    assert detalle.status_code == 200 and "password" not in detalle.json()
    assert detalle.json()["clienteId"] == guardado.usuario_id and detalle.json()["tipoIdentificacion"] == "CC"


def test_crear_cliente_validaciones(client, admin):
    assert client.post("/admin/clientes", headers=admin, json={**CLIENTE, "correo": "no-es-correo"}).status_code == 422
    assert client.post("/admin/clientes", headers=admin, json={**CLIENTE, "nombres": "   "}).status_code == 422
    assert client.post("/admin/clientes", headers=admin, json={**CLIENTE, "tipoIdentificacion": "XX"}).status_code == 422
    sin_pass = {k: v for k, v in CLIENTE.items() if k != "password"}
    assert client.post("/admin/clientes", headers=admin, json=sin_pass).status_code == 422
    assert client.post("/admin/clientes", headers=admin, json=CLIENTE).status_code == 201
    dup = client.post("/admin/clientes", headers=admin, json={**CLIENTE, "telefono": "999"})
    assert dup.status_code == 409 and "ya está registrado" in dup.json()["detail"]["mensaje"]


def test_listar_clientes_gasto_ultimo_anio_y_borrado_logico(client, db_session, admin):
    client.post("/admin/clientes", headers=admin, json=CLIENTE)
    u = db_session.query(Usuario).filter_by(correo="ana@x.co").one()
    db_session.add_all([
        Compra(compra_id=1, fecha=datetime.now(), iva=0, subtotal=100, total=100, estado="PAGADO", usuario_id=u.usuario_id),
        Compra(compra_id=2, fecha=datetime.now(), iva=0, subtotal=50, total=50, estado="PENDIENTE", usuario_id=u.usuario_id),
        Compra(compra_id=3, fecha=datetime(HOY.year - 2, 1, 1), iva=0, subtotal=9, total=9, estado="PAGADO",
               usuario_id=u.usuario_id),
    ])
    db_session.commit()
    lista = client.get("/admin/clientes", headers=admin).json()
    assert lista == [{"usuarioId": u.usuario_id, "imagen": "perfil/ana", "nombreCompleto": "Ana Ruiz",
                      "correo": "ana@x.co", "telefono": "3001", "totalGastado": 100.0, "isEnabled": True}]

    t = client.patch(f"/admin/clientes/{u.usuario_id}/disable", headers=admin).json()
    assert t["mensaje"] == "Usuario deshabilitado exitosamente" and t["isEnabled"] is False
    assert client.delete(f"/admin/clientes/{u.usuario_id}", headers=admin).json()["mensaje"] == "Usuario eliminado exitosamente"
    db_session.refresh(u)
    assert u.account_non_locked is False                              # sigue en la BD (historial)
    assert client.get("/admin/clientes", headers=admin).json() == []


def test_actualizar_cliente_password_opcional(client, db_session, admin):
    client.post("/admin/clientes", headers=admin, json=CLIENTE)
    u = db_session.query(Usuario).filter_by(correo="ana@x.co").one()
    hash_original = u.password
    cambios = {**{k: v for k, v in CLIENTE.items() if k != "password"}, "nombres": "Ana María"}
    r = client.put(f"/admin/clientes/{u.usuario_id}", headers=admin, json=cambios)
    assert r.status_code == 200 and r.json()["mensaje"] == "Cliente actualizado exitosamente"
    db_session.refresh(u)
    assert u.nombres == "Ana María" and u.password == hash_original
    assert client.put("/admin/clientes/999", headers=admin, json=cambios).status_code == 404


def test_opciones_formulario(client, admin):
    body = client.get("/admin/clientes/opciones", headers=admin).json()
    assert {"codigo": "NIT", "descripcion": "Número de Identificación Tributaria"} in body["tiposIdentificacion"]
    assert client.get("/admin/provedores/opciones", headers=admin).json() == body


# --------------------------------------------------------------------------- proveedores
PROVEEDOR = {**CLIENTE, "correo": "prov@x.co", "telefono": "3100", "nit": "900123", "razonSocial": "Licores SAS",
             "ciudad": "Cali", "direccionEmpresa": "Cra 5", "telefonoEmpresa": "6021", "correoEmpresa": "ventas@licores.co"}


def _crear_proveedor(client, admin, db_session):
    r = client.post("/admin/provedores", headers=admin, json=PROVEEDOR)
    assert r.status_code == 201, r.text
    return db_session.query(Usuario).filter_by(correo="prov@x.co").one()


def test_crear_y_obtener_proveedor(client, db_session, admin):
    p = _crear_proveedor(client, admin, db_session)
    body = client.get(f"/admin/provedores/{p.usuario_id}", headers=admin).json()
    assert body["razonSocial"] == "Licores SAS" and body["direccionEmpresa"] == "Cra 5" and "password" not in body
    otro = {**PROVEEDOR, "correo": "otro@x.co", "telefono": "3999", "razonSocial": "Otra"}
    r = client.post("/admin/provedores", headers=admin, json=otro)                  # mismo NIT
    assert r.status_code == 409 and "nit" in r.json()["detail"]["mensaje"]


def test_productos_y_factura_de_compra_suma_stock(client, db_session, admin):
    p = _crear_proveedor(client, admin, db_session)
    db_session.add_all([
        Producto(producto_id=1, nombre="Ron", precio=50000, stock=3, activo=True, usuario_id=p.usuario_id,
                 codigo_producto="R1", marca="Viejo"),
        Producto(producto_id=2, nombre="Ajeno", precio=1, stock=1, activo=True, usuario_id=None),
        Producto(producto_id=3, nombre="Apagado", precio=1, stock=1, activo=False, usuario_id=p.usuario_id),
    ])
    db_session.commit()
    productos = client.get(f"/admin/provedores/productos/{p.usuario_id}", headers=admin).json()
    assert productos == [{"id": 1, "nombre": "Ron", "codigoProducto": "R1", "marca": "Viejo", "precio": 50000.0,
                          "stock": 3}]

    factura = {"numeroFactura": "F-1", "fechaEmision": HOY.isoformat(), "totalCompra": 400000,
               "proveedorId": p.usuario_id, "detalles": [{"productoId": 1, "cantidad": 10, "precioCompra": 40000}]}
    r = client.post("/admin/provedores/compras", headers=admin, json=factura)
    assert r.status_code == 201 and r.json()["mensaje"] == "Factura de compra registrada exitosamente"
    assert db_session.get(Producto, 1).stock == 13
    assert db_session.query(DetalleFactura).one().subtotal == 400000           # calculado si no viene

    assert client.post("/admin/provedores/compras", headers=admin, json=factura).status_code == 409   # nº repetido
    ajeno = {**factura, "numeroFactura": "F-2", "detalles": [{"productoId": 2, "cantidad": 1, "precioCompra": 1}]}
    assert client.post("/admin/provedores/compras", headers=admin, json=ajeno).status_code == 404
    assert db_session.get(Producto, 2).stock == 1
    vacia = {**factura, "numeroFactura": "F-3", "detalles": []}
    assert client.post("/admin/provedores/compras", headers=admin, json=vacia).status_code == 422


def test_listar_proveedores_estadisticas(client, db_session, admin):
    p = _crear_proveedor(client, admin, db_session)
    db_session.add_all([
        Producto(producto_id=1, nombre="Ron", precio=100, stock=5, activo=True, usuario_id=p.usuario_id),
        FacturaProveedor(factura_id=1, activo=True, fecha_emision=HOY, total=700, usuario_id=p.usuario_id),
        FacturaProveedor(factura_id=2, activo=False, fecha_emision=HOY, total=999, usuario_id=p.usuario_id),
        Compra(compra_id=1, fecha=datetime.now(), iva=0, subtotal=300, total=300, estado="PAGADO", usuario_id=1),
        DetalleVenta(detalle_venta_id=1, cantidad=3, precio_unitario=100, subtotal=300, compra_id=1, producto_id=1),
    ])
    db_session.commit()
    fila = client.get("/admin/provedores", headers=admin).json()[0]
    assert fila["nombreEmpresa"] == "Licores SAS" and fila["totalGastado"] == 700.0 and fila["totalGanado"] == 300.0


# --------------------------------------------------------------------------- blog
def test_blog_crud(client, db_session, admin):
    nueva = {"imagen": "blog/uno", "titulo": "Cervezas", "descripcion": "Corta", "historiaCompleta": "Larga",
             "activo": True}
    r = client.post("/admin/blog", headers=admin, json=nueva)
    assert r.status_code == 201 and r.json()["mensaje"] == "Historia creada exitosamente"
    hid = r.json()["id"]
    item = client.get(f"/admin/blog/{hid}", headers=admin).json()
    assert item == {"id": hid, "imagen": "blog/uno", "titulo": "Cervezas", "descripcion": "Corta",
                    "historiaCompleta": "Larga", "fecha": HOY.isoformat(), "activo": True}
    assert client.post("/admin/blog", headers=admin, json={**nueva, "imagen": None}).status_code == 422
    assert client.post("/admin/blog", headers=admin, json={**nueva, "titulo": ""}).status_code == 422
    sin_imagen = {k: v for k, v in nueva.items() if k != "imagen"}
    assert client.put(f"/admin/blog/{hid}", headers=admin, json={**sin_imagen, "titulo": "Nuevo"}).status_code == 200
    assert client.get(f"/admin/blog/{hid}", headers=admin).json()["imagen"] == "blog/uno"   # se conserva
    assert client.patch(f"/admin/blog/{hid}/disable", headers=admin).json()["mensaje"] == "Historia deshabilitada exitosamente"
    assert client.delete(f"/admin/blog/{hid}", headers=admin).json()["mensaje"] == "Historia eliminada exitosamente"
    assert client.get(f"/admin/blog/{hid}", headers=admin).status_code == 404


# --------------------------------------------------------------------------- PQRS y reseñas
def test_pqrs(client, db_session, admin):
    db_session.add_all([
        Usuario(usuario_id=20, correo="c@x.co", password="h", nombres="Luis", apellidos="Paz", telefono="1", rol_id=2),
        Peticion(peticion_id=1, activo=True, fecha=HOY, usuario_id=20, asunto="A", mensaje="M", estado="PENDIENTE",
                 tipo="QUEJA"),
        Peticion(peticion_id=2, activo=False, fecha=HOY, usuario_id=20, asunto="B", mensaje="M", estado="PENDIENTE",
                 tipo="QUEJA"),
    ])
    db_session.commit()
    lista = client.get("/admin/pqrs", headers=admin).json()
    assert lista == [{"id": 1, "tipoPeticion": "Queja", "asunto": "A", "mensaje": "M", "fecha": HOY.isoformat(),
                      "estadoPeticion": "Pendiente", "activo": True,
                      "usurarioResponse": {"nombres": "Luis", "apellidos": "Paz", "correo": "c@x.co", "telefono": "1"}}]
    r = client.patch("/admin/pqrs/1/estado", headers=admin, json={"estadoPeticion": "En Proceso"})
    assert r.status_code == 200 and db_session.get(Peticion, 1).estado == "EN_PROCESO"
    assert client.patch("/admin/pqrs/1/estado", headers=admin, json={"estado": "RESUELTO"}).status_code == 200
    assert client.patch("/admin/pqrs/1/estado", headers=admin, json={"estado": "Archivado"}).status_code == 422
    assert client.delete("/admin/pqrs/1", headers=admin).json()["mensaje"] == "Petición eliminada exitosamente"
    assert client.get("/admin/pqrs", headers=admin).json() == []


def test_resennas(client, db_session, admin):
    db_session.add_all([
        Usuario(usuario_id=20, correo="c@x.co", password="h", nombres="Luis", apellidos="Paz", rol_id=2),
        Historia(historia_id=1, fecha=HOY, is_enabled=True, titulo="Post", descripcion="d", historia_completa="h",
                 imagen="i"),
        Comentario(comentario_id=1, activo=True, calificacion=5, fecha=HOY, historia_id=1, usuario_id=20,
                   titulo="Bueno", mensaje="Me gustó"),
    ])
    db_session.commit()
    assert client.get("/admin/resenna", headers=admin).json() == [{
        "id": 1, "titulo": "Bueno", "mensaje": "Me gustó", "calificacion": 5, "fecha": HOY.isoformat(),
        "estado": True, "usuarioResponse": {"nombres": "Luis", "apellidos": "Paz", "correo": "c@x.co"},
        "blogResponse": {"titulo": "Post"}}]
    assert client.patch("/admin/resenna/1/disable", headers=admin).json()["estado"] is False
    assert client.delete("/admin/resenna/1", headers=admin).json()["mensaje"] == "Comentario eliminado exitosamente"
    assert db_session.get(Comentario, 1) is None


# --------------------------------------------------------------------------- principal y fuga de datos
def test_principal_y_pendientes_sin_password(client, db_session, admin):
    db_session.add(Usuario(usuario_id=30, correo="p@x.co", password="hash-secreto", rol_id=2, is_enabled=False))
    db_session.commit()
    principal = client.get("/admin/principal", headers=admin)
    assert principal.status_code == 200
    assert {"estadisticas", "productosMasVendidos", "totalProductos", "ventasTotales"} <= set(principal.json())
    pendientes = client.get("/admin/usuario/pendientes", headers=admin)
    assert pendientes.status_code == 200 and "hash-secreto" not in pendientes.text and "password" not in pendientes.text
