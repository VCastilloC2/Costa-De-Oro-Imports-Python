"""/admin/producto, /admin/categoria y /admin/compra con los contratos de ProductoController,
CategoriaController y CompraController de Spring."""
from datetime import datetime

import pytest

from app.core.media import cloudinary_url
from app.models import (
    Categoria, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor, Producto, Rol, SubCategoria, Usuario,
)
from app.tests.test_prediction import _seed_admin

PRODUCTO_KEYS = {"id", "codigoProducto", "imagen", "nombre", "marca", "pais", "tipo", "precio", "precioRegular",
                 "stock", "descripcion", "activo", "categoriaId", "nombreCategoria", "subcategoriaId",
                 "nombreSubCategoria", "proveedorId", "nombreProveedor", "empresaProveedor"}


@pytest.fixture
def datos(db_session, seeded_roles):
    headers = _seed_admin(db_session)
    db_session.add(Rol(rol_id=6, rol="PROVEEDOR"))
    db_session.add_all([
        Empresa(empresa_id=1, activo=True, nit="900", telefono="1", correo="e1@x.co", razon_social="Distri SA",
                ciudad="Bogota", direccion="d"),
        Empresa(empresa_id=2, activo=False, nit="901", telefono="2", correo="e2@x.co", razon_social="Inactiva SA",
                ciudad="Cali", direccion="d"),
    ])
    db_session.add_all([
        Usuario(usuario_id=20, correo="prov@x.co", password="hash-secreto", rol_id=6, empresa_id=1,
                nombres="Pedro", apellidos="Gomez", is_enabled=True),
        Usuario(usuario_id=21, correo="prov2@x.co", password="hash", rol_id=6, empresa_id=2,
                nombres="Inactivo", apellidos="X", is_enabled=True),
        Usuario(usuario_id=30, correo="cli@x.co", password="hash", rol_id=2, nombres="Ana", apellidos="Ruiz",
                telefono="300", direccion="Calle 1", imagen="https://img/ana.png", is_enabled=True),
    ])
    db_session.add_all([
        Categoria(categoria_id=1, nombre="Cerveza", descripcion="c", activo=True, imagen="https://img/cat.png"),
        Categoria(categoria_id=2, nombre="Vino", descripcion="v", activo=False),
        Categoria(categoria_id=3, nombre="Vacia", descripcion="sin productos", activo=True),
    ])
    db_session.add_all([
        SubCategoria(subcategoria_id=1, nombre="Lager", categoria_id=1),
        SubCategoria(subcategoria_id=2, nombre="IPA", categoria_id=1),
        SubCategoria(subcategoria_id=3, nombre="Tinto", categoria_id=2),
        SubCategoria(subcategoria_id=4, nombre="Suelta", categoria_id=3),
    ])
    db_session.add_all([
        Producto(producto_id=1, codigo_producto="P-1", nombre="Pilsen", marca="Bavaria", pais="Colombia",
                 tipo="UNIDAD", precio=3000, precio_regular=3500, stock=50, descripcion="d", activo=True,
                 categoria_id=1, subcategoria_id=1, usuario_id=20, imagen="https://img/pilsen.png"),
        Producto(producto_id=2, codigo_producto="P-2", nombre="Sin ventas", marca="M", pais="Peru", tipo="CAJA",
                 precio=10, precio_regular=12, stock=1, descripcion="d", activo=True, categoria_id=1,
                 subcategoria_id=2, usuario_id=20),
    ])
    db_session.add(Compra(compra_id=7, fecha=datetime(2025, 5, 2, 10, 30), iva=570, subtotal=3000, total=3570,
                          estado="PENDIENTE", metodo_pago="MERCADO_PAGO", usuario_id=30, cupon_descuento=None))
    db_session.add(Compra(compra_id=8, fecha=datetime(2025, 6, 1), iva=0, subtotal=1, total=1, estado="PAGADO",
                          metodo_pago="NEQUI", usuario_id=20))
    db_session.add(DetalleVenta(detalle_venta_id=1, cantidad=1, precio_unitario=3000, subtotal=3000, compra_id=7,
                                producto_id=1))
    db_session.commit()
    return headers


def _producto_payload(**cambios):
    base = {"codigoProducto": "P-NEW", "imagen": "productos/img_1", "nombre": "Club Colombia", "marca": "Bavaria",
            "pais": "Colombia", "tipo": "PACK", "precioRegular": 12000, "precio": 10000, "stock": 5,
            "descripcion": "Six pack", "activo": True, "categoriaId": 1, "subCategoriaId": 2, "proveedorId": 20}
    base.update(cambios)
    return base


def _categoria_payload(**cambios):
    base = {"nombre": "Ron", "descripcion": "Rones", "activo": True, "imagen": "categorias/ron",
            "subcategorias": ["Blanco", "Añejo"]}
    base.update(cambios)
    return base


# --- seguridad --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/admin/producto"), ("get", "/admin/producto/1"), ("get", "/admin/producto/opciones"),
    ("get", "/admin/producto/subcategorias/1"), ("post", "/admin/producto"), ("put", "/admin/producto/1"),
    ("patch", "/admin/producto/1/disable"), ("delete", "/admin/producto/1"),
    ("get", "/admin/categoria"), ("get", "/admin/categoria/1"), ("post", "/admin/categoria"),
    ("put", "/admin/categoria/1"), ("patch", "/admin/categoria/1/disable"), ("delete", "/admin/categoria/1"),
    ("get", "/admin/compra"), ("get", "/admin/compra/7"), ("patch", "/admin/compra/7/estado"),
])
def test_requieren_admin(client, metodo, ruta):
    assert getattr(client, metodo)(ruta).status_code == 401


# --- producto ---------------------------------------------------------------------------------------------------------
def test_listar_productos_contrato(client, datos):
    r = client.get("/admin/producto", headers=datos)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2 and set(body[0]) == PRODUCTO_KEYS
    assert body[0] == {
        "id": 1, "codigoProducto": "P-1", "imagen": "https://img/pilsen.png", "nombre": "Pilsen", "marca": "Bavaria",
        "pais": "Colombia", "tipo": "UNIDAD", "precio": 3000.0, "precioRegular": 3500.0, "stock": 50,
        "descripcion": "d", "activo": True, "categoriaId": 1, "nombreCategoria": "Cerveza", "subcategoriaId": 1,
        "nombreSubCategoria": "Lager", "proveedorId": 20, "nombreProveedor": "PedroGomez",
        "empresaProveedor": "Distri SA",
    }
    assert "hash-secreto" not in r.text


def test_obtener_producto_y_404(client, datos):
    assert client.get("/admin/producto/2", headers=datos).json()["nombreSubCategoria"] == "IPA"
    r = client.get("/admin/producto/999", headers=datos)
    assert r.status_code == 404
    assert r.json() == {"mensaje": "error: El producto con id: 999 no existe", "success": False}


def test_opciones_y_subcategorias(client, datos):
    body = client.get("/admin/producto/opciones", headers=datos).json()
    assert body["tiposProducto"] == ["UNIDAD", "CAJA", "PACK", "COMBO"]
    assert body["categoriaList"] == [{"id": 1, "nombre": "Cerveza"}, {"id": 3, "nombre": "Vacia"}]
    # Solo proveedores con empresa activa (findByRol_NameAndEmpresa_ActivoTrue)
    assert body["proveedorList"] == [{"id": 20, "nombreEmpresa": "Distri SA", "nombreUsuario": "Pedro Gomez"}]

    subs = client.get("/admin/producto/subcategorias/1", headers=datos).json()
    assert subs == [{"id": 1, "nombre": "Lager", "categoriaId": 1}, {"id": 2, "nombre": "IPA", "categoriaId": 1}]
    assert client.get("/admin/producto/subcategorias/2", headers=datos).json() == []  # categoría inactiva


def test_crear_producto(client, datos, db_session):
    r = client.post("/admin/producto", json=_producto_payload(), headers=datos)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mensaje"] == "Producto creado exitosamente" and body["success"] is True
    creado = client.get(f"/admin/producto/{body['id']}", headers=datos).json()
    assert creado["tipo"] == "PACK" and creado["subcategoriaId"] == 2 and creado["imagen"] == cloudinary_url("productos/img_1")

    # snake_case también se acepta
    snake = {"codigo_producto": "P-SNAKE", "nombre": "x", "marca": "m", "pais": "p", "tipo": "COMBO",
             "precio_regular": 1, "precio": 1, "stock": 0, "descripcion": "d", "categoria_id": 1,
             "sub_categoria_id": 1, "proveedor_id": 20}
    r = client.post("/admin/producto", json=snake, headers=datos)
    assert r.status_code == 201, r.text
    assert client.get(f"/admin/producto/{r.json()['id']}", headers=datos).json()["activo"] is False


@pytest.mark.parametrize("cambios", [
    {"nombre": "   "}, {"codigoProducto": ""}, {"precio": 0}, {"precioRegular": -1}, {"stock": -1},
    {"stock": 1.5}, {"tipo": "BOTELLA"}, {"categoriaId": None}, {"descripcion": None},
])
def test_crear_producto_invalido_422(client, datos, cambios):
    r = client.post("/admin/producto", json=_producto_payload(**cambios), headers=datos)
    assert r.status_code == 422


def test_crear_producto_reglas_de_negocio(client, datos):
    r = client.post("/admin/producto", json=_producto_payload(subCategoriaId=3), headers=datos)
    assert r.status_code == 422
    assert r.json() == {"mensaje": "La subcategoria seleccionada no pertenece a la categoría Cerveza",
                        "success": False}
    r = client.post("/admin/producto", json=_producto_payload(proveedorId=999), headers=datos)
    assert r.status_code == 422 and r.json()["mensaje"] == "El proveedor con id: 999 no existe"
    r = client.post("/admin/producto", json=_producto_payload(categoriaId=999), headers=datos)
    assert r.status_code == 422
    r = client.post("/admin/producto", json=_producto_payload(codigoProducto="P-1"), headers=datos)
    assert r.status_code == 409 and r.json()["success"] is False


def test_actualizar_producto(client, datos):
    payload = _producto_payload(codigoProducto="P-1", nombre="Pilsen 2", imagen=None, subCategoriaId=2)
    r = client.put("/admin/producto/1", json=payload, headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Producto actualizado exitosamente", "success": True}
    p = client.get("/admin/producto/1", headers=datos).json()
    assert p["nombre"] == "Pilsen 2" and p["subcategoriaId"] == 2
    assert p["imagen"] == "https://img/pilsen.png"  # sin imagen nueva se conserva la actual

    # PATCH (antes el genérico sin validación) ahora valida igual que PUT
    assert client.patch("/admin/producto/1", json={"nombre": "solo nombre"}, headers=datos).status_code == 422
    assert client.put("/admin/producto/1", json=_producto_payload(precio=-5), headers=datos).status_code == 422
    assert client.put("/admin/producto/999", json=_producto_payload(), headers=datos).status_code == 404
    r = client.put("/admin/producto/2", json=_producto_payload(codigoProducto="P-1"), headers=datos)
    assert r.status_code == 409


def test_toggle_producto(client, datos):
    r = client.patch("/admin/producto/1/disable", headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Producto deshabilitado exitosamente", "success": True, "id": 1, "activo": False}
    r = client.patch("/admin/producto/1/disable", headers=datos)
    assert r.json()["mensaje"] == "Producto Habilitado exitosamente" and r.json()["activo"] is True
    assert client.patch("/admin/producto/999/disable", headers=datos).status_code == 404


def test_eliminar_producto(client, datos, db_session):
    # Con ventas: no se puede borrar (FK sin cascade en Spring)
    r = client.delete("/admin/producto/1", headers=datos)
    assert r.status_code == 409 and r.json()["success"] is False
    assert db_session.get(Producto, 1) is not None

    r = client.delete("/admin/producto/2", headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Producto eliminado exitosamente", "success": True}
    assert client.get("/admin/producto/2", headers=datos).status_code == 404
    assert client.delete("/admin/producto/2", headers=datos).status_code == 404


def test_eliminar_producto_con_factura_409(client, datos, db_session):
    db_session.add(FacturaProveedor(factura_id=1, activo=True, total=10))
    db_session.add(DetalleFactura(detalle_factura_id=1, cantidad=1, precio_compra=10, subtotal=10, factura_id=1,
                                  producto_id=2))
    db_session.commit()
    assert client.delete("/admin/producto/2", headers=datos).status_code == 409


# --- categoría --------------------------------------------------------------------------------------------------------
def test_listar_categorias_contrato(client, datos):
    body = client.get("/admin/categoria", headers=datos).json()
    assert [c["id"] for c in body] == [1, 2, 3]
    assert body[0] == {"id": 1, "imagen": "https://img/cat.png", "nombre": "Cerveza", "descripcion": "c",
                       "activo": True, "totalProductos": 2,
                       "subcategorias": [{"id": 1, "nombre": "Lager"}, {"id": 2, "nombre": "IPA"}]}
    assert body[1]["activo"] is False and body[1]["totalProductos"] == 0


def test_obtener_categoria_404(client, datos):
    assert client.get("/admin/categoria/3", headers=datos).json()["subcategorias"] == [{"id": 4, "nombre": "Suelta"}]
    r = client.get("/admin/categoria/999", headers=datos)
    assert r.status_code == 404
    assert r.json() == {"mensaje": "La categoria con id: 999 no existe o ha sido eliminada", "success": False}


def test_crear_categoria(client, datos):
    r = client.post("/admin/categoria", json=_categoria_payload(), headers=datos)
    assert r.status_code == 201, r.text
    assert r.json()["mensaje"] == "Categoria creada exitosamente" and r.json()["success"] is True
    c = client.get(f"/admin/categoria/{r.json()['id']}", headers=datos).json()
    assert [s["nombre"] for s in c["subcategorias"]] == ["Blanco", "Añejo"] and c["totalProductos"] == 0
    # nombre único
    assert client.post("/admin/categoria", json=_categoria_payload(), headers=datos).status_code == 409


@pytest.mark.parametrize("cambios", [
    {"nombre": " "}, {"descripcion": ""}, {"subcategorias": []}, {"subcategorias": ["ok", "  "]},
    {"subcategorias": None}, {"nombre": "x" * 176},
])
def test_crear_categoria_invalida_422(client, datos, cambios):
    assert client.post("/admin/categoria", json=_categoria_payload(**cambios), headers=datos).status_code == 422


def test_actualizar_categoria(client, datos):
    # Se mantiene Lager (id 1, con producto), se quita IPA (tiene producto 2) -> 409
    r = client.put("/admin/categoria/1", json=_categoria_payload(nombre="Cerveza", subcategorias=["Lager"]),
                   headers=datos)
    assert r.status_code == 409 and "IPA" in r.json()["mensaje"]

    r = client.put("/admin/categoria/1", json=_categoria_payload(nombre="Cervezas", imagen=None,
                                                                 subcategorias=["Lager", "IPA", "Stout"]),
                   headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Categoria actualizada exitosamente", "success": True}
    c = client.get("/admin/categoria/1", headers=datos).json()
    assert c["nombre"] == "Cervezas" and c["imagen"] == "https://img/cat.png"
    assert [(s["id"], s["nombre"]) for s in c["subcategorias"]][:2] == [(1, "Lager"), (2, "IPA")]
    assert c["subcategorias"][2]["nombre"] == "Stout"

    # Subcategoría sin productos se puede quitar
    r = client.put("/admin/categoria/3", json=_categoria_payload(nombre="Vacia", subcategorias=["Nueva"]),
                   headers=datos)
    assert r.status_code == 200
    assert [s["nombre"] for s in client.get("/admin/categoria/3", headers=datos).json()["subcategorias"]] == ["Nueva"]

    assert client.put("/admin/categoria/999", json=_categoria_payload(), headers=datos).status_code == 404
    assert client.put("/admin/categoria/3", json=_categoria_payload(nombre="Vino"), headers=datos).status_code == 409
    assert client.patch("/admin/categoria/3", json={"activo": False}, headers=datos).status_code == 422


def test_toggle_categoria(client, datos):
    r = client.patch("/admin/categoria/2/disable", headers=datos)
    assert r.json() == {"mensaje": "Categoría habilitada exitosamente", "success": True, "id": 2, "activo": True}
    r = client.patch("/admin/categoria/2/disable", headers=datos)
    assert r.json()["mensaje"] == "Categoría deshabilitada exitosamente"
    assert client.patch("/admin/categoria/999/disable", headers=datos).status_code == 404


def test_eliminar_categoria(client, datos, db_session):
    r = client.delete("/admin/categoria/1", headers=datos)
    assert r.status_code == 409
    assert r.json() == {"mensaje": "No es posible eliminar una categoria con productos", "success": False}

    r = client.delete("/admin/categoria/3", headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "categoria eliminada exitosamente", "success": True}
    assert db_session.get(SubCategoria, 4) is None          # subcategorías borradas en cascada
    assert client.get("/admin/categoria/3", headers=datos).status_code == 404
    assert client.delete("/admin/categoria/3", headers=datos).status_code == 404


# --- compra -----------------------------------------------------------------------------------------------------------
def test_listar_compras_contrato(client, datos):
    body = client.get("/admin/compra", headers=datos).json()
    assert [c["compraId"] for c in body] == [8, 7]           # fecha desc
    assert body[1] == {"compraId": 7, "numeroOrden": "ORD-0007", "usuarioNombreCompleto": "Ana Ruiz",
                       "usuarioImagenUrl": "https://img/ana.png", "metodoPago": "Mercado Pago", "total": 3570.0,
                       "fecha": "2025-05-02T10:30:00", "estado": "Pendiente"}
    assert body[0]["metodoPago"] == "Nequi" and body[0]["estado"] == "Pagado"
    assert [c["compraId"] for c in client.get("/admin/compra?offset=1&limit=1", headers=datos).json()] == [7]


def test_detalle_compra_contrato(client, datos):
    r = client.get("/admin/compra/7", headers=datos)
    assert r.status_code == 200
    assert r.json() == {
        "compraId": 7, "numeroOrden": "#FC0007", "metodoPago": "Mercado Pago", "subtotal": 3000.0,
        "cuponDescuento": None, "iva": 570.0, "total": 3570.0, "fecha": "2025-05-02T10:30:00", "estado": "Pendiente",
        "usuarioId": 30, "usuarioNombreCompleto": "Ana Ruiz", "usuarioCorreo": "cli@x.co", "usuarioTelefono": "300",
        "usuarioDireccion": "Calle 1", "ciudadEmpresa": "",
        "productos": [{"productoId": 1, "nombre": "Pilsen", "imagen": "https://img/pilsen.png", "marca": "Bavaria",
                       "tipo": "UNIDAD", "precioUnitario": 3000.0, "cantidad": 1, "subtotal": 3000.0}],
    }
    assert client.get("/admin/compra/8", headers=datos).json()["ciudadEmpresa"] == "Bogota"
    r = client.get("/admin/compra/999", headers=datos)
    assert r.status_code == 404 and r.json() == {"mensaje": "La compra con id: 999 no existe.", "success": False}


def test_cambiar_estado_compra(client, datos, db_session):
    r = client.patch("/admin/compra/7/estado", json={"estado": "pagado"}, headers=datos)
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Estado cambiado exitosamente", "success": True, "id": 7, "estado": "PAGADO"}
    assert client.get("/admin/compra/7", headers=datos).json()["estado"] == "Pagado"

    assert client.patch("/admin/compra/7/estado", json={"estado": "ENVIADO"}, headers=datos).status_code == 422
    assert client.patch("/admin/compra/7/estado", json={}, headers=datos).status_code == 422
    assert client.patch("/admin/compra/999/estado", json={"estado": "PAGADO"}, headers=datos).status_code == 404
