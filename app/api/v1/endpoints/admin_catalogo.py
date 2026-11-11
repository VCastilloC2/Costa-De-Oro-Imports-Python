"""Páginas de catálogo y ventas del panel admin (equivalente a ProductoController, CategoriaController
y CompraController de Spring) expuestas como API REST.

Contratos (claves camelCase iguales a como Jackson serializa los records de Spring):

* ``ProductoResponse``, ``CategoriaResponse``, ``CategoriaProductoResponse``, ``SubCategoriaProductoResponse``,
  ``ProveedorProductoResponse``, ``CompraDashboardResponse``, ``DetalleCompraResponse``.
* Mutaciones -> ``BaseResponse`` ``{"mensaje", "success"}`` (+ ``id`` al crear, ``id``/``activo`` al cambiar estado),
  con los mismos mensajes que los ``*ServiceImpl`` de Spring.

Diferencias deliberadas con Spring (ver docstrings de cada endpoint):

* Imágenes: Spring recibe un ``MultipartFile`` y lo sube a Cloudinary. Este repositorio no tiene código de subida,
  así que ``imagen`` es un string (``public_id`` de Cloudinary o URL ya subida). En el update, si ``imagen`` no se
  envía se conserva la actual (Spring la dejaba en ``null`` cuando no se adjuntaba archivo).
* Los errores de negocio que en Spring eran ``BaseResponse(success=false)`` + redirect o una excepción se devuelven
  con el código HTTP adecuado (404/409/422) y el mismo cuerpo ``BaseResponse``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.media import cloudinary_url
from app.dependencies import admin_user
from app.models import (
    Categoria, Compra, DetalleFactura, DetalleVenta, Empresa, Producto, Rol, SubCategoria, Usuario,
)

router = APIRouter(tags=["Administración"], dependencies=[Depends(admin_user)])

DB = Annotated[Session, Depends(get_db)]

# Orden de declaración de los enums de Spring (ETipo.values(), EEstado, EMetodoPago).
TIPOS_PRODUCTO = ("UNIDAD", "CAJA", "PACK", "COMBO")
DESCRIPCION_ESTADO = {"PENDIENTE": "Pendiente", "PAGADO": "Pagado", "CANCELADO": "Cancelado", "RECHAZADO": "Rechazado"}
DESCRIPCION_METODO_PAGO = {
    "MERCADO_PAGO": "Mercado Pago", "TRANSFERENCIA": "Transferencia", "TARJETA_CREDITO": "Tarjeta Credito",
    "TARJETA_DEBITO": "Tarjeta Debito", "PSE": "PSE", "PAYPAL": "PayPal", "NEQUI": "Nequi", "DAVIPLATA": "Daviplata",
}


# ---------------------------------------------------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------------------------------------------------
class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class RequestModel(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


def _not_blank(value: str) -> str:
    """Equivalente a ``@NotBlank``: rechaza vacío o solo espacios."""
    if value is None or not value.strip():
        raise ValueError("no debe estar vacío")
    return value.strip()


class BaseResponse(CamelModel):
    mensaje: str
    success: bool


class CreatedResponse(BaseResponse):
    id: int


class EstadoActivoResponse(BaseResponse):
    id: int
    activo: bool


class EstadoCompraResponse(BaseResponse):
    id: int
    estado: str


# --- Producto ---
class ProductoCreateRequest(RequestModel):
    """``ProductoCreateRequest`` de Spring. ``imagen`` es un public_id/URL (no multipart)."""
    codigo_producto: str = Field(max_length=255)
    imagen: str | None = Field(default=None, max_length=255)
    nombre: str = Field(max_length=255)
    marca: str = Field(max_length=255)
    pais: str = Field(max_length=255)
    tipo: Literal["UNIDAD", "CAJA", "PACK", "COMBO"]
    precio_regular: float = Field(gt=0)
    precio: float = Field(gt=0)
    stock: int = Field(ge=0)
    descripcion: str = Field(max_length=700)
    activo: bool = False
    categoria_id: int = Field(gt=0)
    sub_categoria_id: int = Field(gt=0, validation_alias=AliasChoices(
        "subCategoriaId", "subcategoriaId", "sub_categoria_id", "subcategoria_id"))
    proveedor_id: int = Field(gt=0)

    @field_validator("codigo_producto", "nombre", "marca", "pais", "descripcion")
    @classmethod
    def _no_vacios(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("imagen")
    @classmethod
    def _imagen(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ProductoResponse(CamelModel):
    id: int
    codigo_producto: str | None
    imagen: str | None
    nombre: str | None
    marca: str | None
    pais: str | None
    tipo: str | None
    precio: float
    precio_regular: float
    stock: int
    descripcion: str | None
    activo: bool
    categoria_id: int | None
    nombre_categoria: str | None
    subcategoria_id: int | None
    nombre_sub_categoria: str | None
    proveedor_id: int | None
    nombre_proveedor: str | None
    empresa_proveedor: str | None


class CategoriaProductoResponse(CamelModel):
    id: int
    nombre: str


class SubCategoriaProductoResponse(CamelModel):
    id: int
    nombre: str | None
    categoria_id: int


class ProveedorProductoResponse(CamelModel):
    id: int
    nombre_empresa: str
    nombre_usuario: str


class ProductoOpcionesResponse(CamelModel):
    """Datos que Spring pone en el Model de ``create-producto`` / ``update-producto``."""
    tipos_producto: list[str]
    categoria_list: list[CategoriaProductoResponse]
    proveedor_list: list[ProveedorProductoResponse]


# --- Categoría ---
class CategoriaCreateRequest(RequestModel):
    """``CategoriaCreateRequest`` de Spring (incluye la lista de nombres de subcategorías)."""
    imagen: str | None = Field(default=None, max_length=255)
    nombre: str = Field(max_length=175)
    descripcion: str = Field(max_length=500)
    activo: bool = False
    subcategorias: list[Annotated[str, Field(max_length=255)]] = Field(min_length=1)

    @field_validator("nombre", "descripcion")
    @classmethod
    def _no_vacios(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("imagen")
    @classmethod
    def _imagen(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("subcategorias")
    @classmethod
    def _subcategorias(cls, value: list[str]) -> list[str]:
        limpias: list[str] = []
        for nombre in value:
            nombre = _not_blank(nombre)
            if nombre not in limpias:
                limpias.append(nombre)
        return limpias


class SubCategoriaResponse(CamelModel):
    id: int
    nombre: str | None


class CategoriaResponse(CamelModel):
    id: int
    imagen: str | None
    nombre: str
    descripcion: str
    activo: bool
    total_productos: int
    subcategorias: list[SubCategoriaResponse]


# --- Compra ---
class CompraDashboardResponse(CamelModel):
    compra_id: int
    numero_orden: str
    usuario_nombre_completo: str
    usuario_imagen_url: str | None
    metodo_pago: str | None
    total: float
    fecha: datetime | None
    estado: str | None


class DetalleProductoResponse(CamelModel):
    producto_id: int | None
    nombre: str | None
    imagen: str | None
    marca: str | None
    tipo: str | None
    precio_unitario: float
    cantidad: int
    subtotal: float


class DetalleCompraResponse(CamelModel):
    compra_id: int
    numero_orden: str
    metodo_pago: str | None
    subtotal: float
    cupon_descuento: str | None
    iva: float
    total: float
    fecha: datetime | None
    estado: str | None
    usuario_id: int | None
    usuario_nombre_completo: str | None
    usuario_correo: str | None
    usuario_telefono: str | None
    usuario_direccion: str | None
    ciudad_empresa: str
    productos: list[DetalleProductoResponse]


class CambiarEstadoCompraRequest(RequestModel):
    """Spring recibe ``?estado=`` y lo mapea sin distinguir mayúsculas (``mapearStringAEstado``)."""
    estado: str

    @field_validator("estado")
    @classmethod
    def _estado(cls, value: str) -> str:
        normalizado = (value or "").strip().upper()
        if normalizado not in DESCRIPCION_ESTADO:
            raise ValueError(f"Estado Invalido {value}")
        return normalizado


# ---------------------------------------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------------------------------------
def _fail(status: int, mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"mensaje": mensaje, "success": False})


ERRORES = {404: {"model": BaseResponse}, 409: {"model": BaseResponse}}


def _commit(db: Session) -> bool:
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _nombre(nombres: str | None, apellidos: str | None, sep: str = " ") -> str:
    # Java concatena null como "null"; aquí se omiten los nulos.
    return sep.join(p for p in (nombres, apellidos) if p) if sep else f"{nombres or ''}{apellidos or ''}"


# ---------------------------------------------------------------------------------------------------------------------
# Producto (/admin/producto)
# ---------------------------------------------------------------------------------------------------------------------
def _productos_response(db: Session, productos: list[Producto]) -> list[ProductoResponse]:
    cat_ids = {p.categoria_id for p in productos if p.categoria_id}
    sub_ids = {p.subcategoria_id for p in productos if p.subcategoria_id}
    prov_ids = {p.usuario_id for p in productos if p.usuario_id}
    categorias = {c.categoria_id: c for c in db.scalars(select(Categoria).where(Categoria.categoria_id.in_(cat_ids)))} \
        if cat_ids else {}
    subs = {s.subcategoria_id: s for s in db.scalars(select(SubCategoria).where(SubCategoria.subcategoria_id.in_(sub_ids)))} \
        if sub_ids else {}
    proveedores: dict[int, tuple[Usuario, str | None]] = {}
    if prov_ids:
        filas = db.execute(select(Usuario, Empresa.razon_social)
                           .outerjoin(Empresa, Empresa.empresa_id == Usuario.empresa_id)
                           .where(Usuario.usuario_id.in_(prov_ids))).all()
        proveedores = {u.usuario_id: (u, razon) for u, razon in filas}
    salida = []
    for p in productos:
        cat = categorias.get(p.categoria_id)
        sub = subs.get(p.subcategoria_id)
        prov, empresa = proveedores.get(p.usuario_id, (None, None))
        salida.append(ProductoResponse(
            id=p.producto_id, codigo_producto=p.codigo_producto, imagen=cloudinary_url(p.imagen), nombre=p.nombre,
            marca=p.marca, pais=p.pais, tipo=p.tipo, precio=float(p.precio or 0),
            precio_regular=float(p.precio_regular or 0), stock=int(p.stock or 0), descripcion=p.descripcion,
            activo=bool(p.activo), categoria_id=cat.categoria_id if cat else None,
            nombre_categoria=cat.nombre if cat else None, subcategoria_id=sub.subcategoria_id if sub else None,
            nombre_sub_categoria=sub.nombre if sub else None, proveedor_id=prov.usuario_id if prov else None,
            # Spring concatena nombres + apellidos SIN espacio (ProductoServiceImpl.toResponse).
            nombre_proveedor=_nombre(prov.nombres, prov.apellidos, sep="") if prov else None,
            empresa_proveedor=empresa,
        ))
    return salida


def _producto_no_existe(item_id: int) -> JSONResponse:
    return _fail(404, f"error: El producto con id: {item_id} no existe")


def _validar_relaciones_producto(db: Session, data: ProductoCreateRequest) -> JSONResponse | None:
    categoria = db.get(Categoria, data.categoria_id)
    if not categoria:
        return _fail(422, f"La categoria con id: {data.categoria_id} no exite")
    sub = db.get(SubCategoria, data.sub_categoria_id)
    if not sub:
        return _fail(422, f"La subcategoria con id: {data.sub_categoria_id} no existe")
    if sub.categoria_id != data.categoria_id:
        return _fail(422, f"La subcategoria seleccionada no pertenece a la categoría {categoria.nombre}")
    if not db.get(Usuario, data.proveedor_id):
        return _fail(422, f"El proveedor con id: {data.proveedor_id} no existe")
    return None


def _codigo_duplicado(db: Session, codigo: str, excluir: int | None = None) -> JSONResponse | None:
    stmt = select(Producto.producto_id).where(Producto.codigo_producto == codigo)
    if excluir is not None:
        stmt = stmt.where(Producto.producto_id != excluir)
    if db.scalar(stmt.limit(1)) is not None:
        return _fail(409, f"Ya existe un producto con el código {codigo}")
    return None


def _aplicar_producto(producto: Producto, data: ProductoCreateRequest) -> None:
    producto.codigo_producto = data.codigo_producto
    producto.nombre = data.nombre
    producto.marca = data.marca
    producto.pais = data.pais
    producto.tipo = data.tipo
    producto.precio_regular = data.precio_regular
    producto.precio = data.precio
    producto.stock = data.stock
    producto.descripcion = data.descripcion
    producto.activo = data.activo
    producto.categoria_id = data.categoria_id
    producto.subcategoria_id = data.sub_categoria_id
    producto.usuario_id = data.proveedor_id


@router.get("/admin/producto", response_model=list[ProductoResponse],
            summary="Productos (activos e inactivos) — productoService.getProductos()")
def listar_productos(db: DB):
    productos = list(db.scalars(select(Producto).order_by(Producto.producto_id)))
    return _productos_response(db, productos)


@router.get("/admin/producto/opciones", response_model=ProductoOpcionesResponse,
            summary="Datos del formulario crear/editar producto (tipos, categorías y proveedores activos)")
def opciones_producto(db: DB):
    categorias = db.scalars(select(Categoria).where(Categoria.activo.is_(True)).order_by(Categoria.categoria_id))
    proveedores = db.execute(
        select(Usuario, Empresa.razon_social)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .join(Empresa, Empresa.empresa_id == Usuario.empresa_id)
        .where(Rol.rol == "PROVEEDOR", Empresa.activo.is_(True))
        .order_by(Usuario.usuario_id)
    ).all()
    return ProductoOpcionesResponse(
        tipos_producto=list(TIPOS_PRODUCTO),
        categoria_list=[CategoriaProductoResponse(id=c.categoria_id, nombre=c.nombre) for c in categorias],
        proveedor_list=[ProveedorProductoResponse(id=u.usuario_id, nombre_empresa=razon or "Sin empresa",
                                                  nombre_usuario=_nombre(u.nombres, u.apellidos))
                        for u, razon in proveedores],
    )


@router.get("/admin/producto/subcategorias/{categoria_id}", response_model=list[SubCategoriaProductoResponse],
            summary="Subcategorías de una categoría activa — getSubCategoriasActivasByCategoriaId")
def subcategorias_por_categoria(categoria_id: int, db: DB):
    filas = db.scalars(
        select(SubCategoria)
        .join(Categoria, Categoria.categoria_id == SubCategoria.categoria_id)
        .where(SubCategoria.categoria_id == categoria_id, Categoria.activo.is_(True))
        .order_by(SubCategoria.subcategoria_id)
    )
    return [SubCategoriaProductoResponse(id=s.subcategoria_id, nombre=s.nombre, categoria_id=s.categoria_id)
            for s in filas]


@router.get("/admin/producto/{item_id}", response_model=ProductoResponse, responses=ERRORES,
            summary="Producto por id — getProductoResponseById")
def obtener_producto(item_id: int, db: DB):
    producto = db.get(Producto, item_id)
    if not producto:
        return _producto_no_existe(item_id)
    return _productos_response(db, [producto])[0]


@router.post("/admin/producto", status_code=201, response_model=CreatedResponse,
             responses={409: {"model": BaseResponse}, 422: {"model": BaseResponse}},
             summary="Crear producto — createProducto")
def crear_producto(data: ProductoCreateRequest, db: DB):
    error = _validar_relaciones_producto(db, data) or _codigo_duplicado(db, data.codigo_producto)
    if error:
        return error
    producto = Producto(imagen=data.imagen)
    _aplicar_producto(producto, data)
    db.add(producto)
    if not _commit(db):
        return _fail(409, "No se pudo crear el producto: viola una restricción de integridad")
    return CreatedResponse(mensaje="Producto creado exitosamente", success=True, id=producto.producto_id)


def _actualizar_producto(item_id: int, data: ProductoCreateRequest, db: Session):
    producto = db.get(Producto, item_id)
    if not producto:
        return _producto_no_existe(item_id)
    error = _validar_relaciones_producto(db, data) or _codigo_duplicado(db, data.codigo_producto, excluir=item_id)
    if error:
        return error
    _aplicar_producto(producto, data)
    if data.imagen is not None:
        producto.imagen = data.imagen
    if not _commit(db):
        return _fail(409, "No se pudo actualizar el producto: viola una restricción de integridad")
    return BaseResponse(mensaje="Producto actualizado exitosamente", success=True)


@router.put("/admin/producto/{item_id}", response_model=BaseResponse,
            responses={**ERRORES, 422: {"model": BaseResponse}}, summary="Actualizar producto — updateProducto")
def actualizar_producto(item_id: int, data: ProductoCreateRequest, db: DB):
    return _actualizar_producto(item_id, data, db)


@router.patch("/admin/producto/{item_id}", response_model=BaseResponse,
              responses={**ERRORES, 422: {"model": BaseResponse}},
              summary="Alias de PUT (reemplaza el PATCH genérico sin validación; requiere el cuerpo completo)")
def actualizar_producto_patch(item_id: int, data: ProductoCreateRequest, db: DB):
    return _actualizar_producto(item_id, data, db)


@router.patch("/admin/producto/{item_id}/disable", response_model=EstadoActivoResponse, responses=ERRORES,
              summary="Habilitar/deshabilitar producto — changeEstadoProducto")
def cambiar_estado_producto(item_id: int, db: DB):
    producto = db.get(Producto, item_id)
    if not producto:
        return _producto_no_existe(item_id)
    producto.activo = not bool(producto.activo)
    db.commit()
    mensaje = "Producto Habilitado exitosamente" if producto.activo else "Producto deshabilitado exitosamente"
    return EstadoActivoResponse(mensaje=mensaje, success=True, id=item_id, activo=producto.activo)


@router.delete("/admin/producto/{item_id}", response_model=BaseResponse, responses=ERRORES,
               summary="Eliminar producto (borrado físico) — deleteProducto")
def eliminar_producto(item_id: int, db: DB):
    """Borrado físico como en Spring. Si el producto tiene ventas o facturas de proveedor asociadas, Spring
    fallaba por la FK (sin cascade); aquí se responde 409 sin borrar nada."""
    producto = db.get(Producto, item_id)
    if not producto:
        return _producto_no_existe(item_id)
    en_uso = db.scalar(select(DetalleVenta.detalle_venta_id).where(DetalleVenta.producto_id == item_id).limit(1)) \
        or db.scalar(select(DetalleFactura.detalle_factura_id).where(DetalleFactura.producto_id == item_id).limit(1))
    if en_uso:
        return _fail(409, "No es posible eliminar un producto con ventas o facturas asociadas")
    db.delete(producto)
    if not _commit(db):
        return _fail(409, "No es posible eliminar el producto: tiene registros asociados")
    return BaseResponse(mensaje="Producto eliminado exitosamente", success=True)


# ---------------------------------------------------------------------------------------------------------------------
# Categoría (/admin/categoria)
# ---------------------------------------------------------------------------------------------------------------------
def _categorias_response(db: Session, categorias: list[Categoria]) -> list[CategoriaResponse]:
    ids = [c.categoria_id for c in categorias]
    if not ids:
        return []
    conteos = dict(db.execute(select(Producto.categoria_id, func.count(Producto.producto_id))
                              .where(Producto.categoria_id.in_(ids)).group_by(Producto.categoria_id)).all())
    subs: dict[int, list[SubCategoriaResponse]] = {i: [] for i in ids}
    for s in db.scalars(select(SubCategoria).where(SubCategoria.categoria_id.in_(ids))
                        .order_by(SubCategoria.subcategoria_id)):
        subs[s.categoria_id].append(SubCategoriaResponse(id=s.subcategoria_id, nombre=s.nombre))
    return [CategoriaResponse(id=c.categoria_id, imagen=cloudinary_url(c.imagen), nombre=c.nombre,
                              descripcion=c.descripcion, activo=bool(c.activo),
                              total_productos=int(conteos.get(c.categoria_id, 0)),
                              subcategorias=subs[c.categoria_id])
            for c in categorias]


def _categoria_no_existe(item_id: int) -> JSONResponse:
    return _fail(404, f"La categoria con id: {item_id} no existe o ha sido eliminada")


def _nombre_categoria_duplicado(db: Session, nombre: str, excluir: int | None = None) -> JSONResponse | None:
    stmt = select(Categoria.categoria_id).where(Categoria.nombre == nombre)
    if excluir is not None:
        stmt = stmt.where(Categoria.categoria_id != excluir)
    if db.scalar(stmt.limit(1)) is not None:
        return _fail(409, f"Ya existe una categoria con el nombre {nombre}")
    return None


@router.get("/admin/categoria", response_model=list[CategoriaResponse],
            summary="Categorías (activas e inactivas) — categoriaService.getCategorias()")
def listar_categorias(db: DB):
    return _categorias_response(db, list(db.scalars(select(Categoria).order_by(Categoria.categoria_id))))


@router.get("/admin/categoria/{item_id}", response_model=CategoriaResponse, responses=ERRORES,
            summary="Categoría por id — getCategoriaResponseById")
def obtener_categoria(item_id: int, db: DB):
    categoria = db.get(Categoria, item_id)
    if not categoria:
        return _categoria_no_existe(item_id)
    return _categorias_response(db, [categoria])[0]


@router.post("/admin/categoria", status_code=201, response_model=CreatedResponse,
             responses={409: {"model": BaseResponse}}, summary="Crear categoría con subcategorías — createCategoria")
def crear_categoria(data: CategoriaCreateRequest, db: DB):
    error = _nombre_categoria_duplicado(db, data.nombre)
    if error:
        return error
    categoria = Categoria(imagen=data.imagen, nombre=data.nombre, descripcion=data.descripcion, activo=data.activo)
    db.add(categoria)
    try:
        db.flush()
        db.add_all([SubCategoria(nombre=n, categoria_id=categoria.categoria_id) for n in data.subcategorias])
        db.commit()
    except IntegrityError:
        db.rollback()
        return _fail(409, "No se pudo crear la categoria: viola una restricción de integridad")
    return CreatedResponse(mensaje="Categoria creada exitosamente", success=True, id=categoria.categoria_id)


def _actualizar_categoria(item_id: int, data: CategoriaCreateRequest, db: Session):
    """Spring borra todas las subcategorías y las vuelve a crear (orphanRemoval), lo que falla por FK en cuanto un
    producto apunta a una de ellas. Aquí se reconcilia por nombre: las que se mantienen conservan su id, las nuevas
    se crean y las que se quitan se borran; si alguna de las quitadas tiene productos se responde 409."""
    categoria = db.get(Categoria, item_id)
    if not categoria:
        return _categoria_no_existe(item_id)
    error = _nombre_categoria_duplicado(db, data.nombre, excluir=item_id)
    if error:
        return error
    actuales = list(db.scalars(select(SubCategoria).where(SubCategoria.categoria_id == item_id)))
    por_nombre = {s.nombre: s for s in actuales}
    quitar = [s for s in actuales if s.nombre not in data.subcategorias]
    if quitar:
        ids_quitar = [s.subcategoria_id for s in quitar]
        en_uso = db.scalars(select(SubCategoria.nombre).join(Producto, Producto.subcategoria_id == SubCategoria.subcategoria_id)
                            .where(SubCategoria.subcategoria_id.in_(ids_quitar)).distinct()).all()
        if en_uso:
            return _fail(409, "No es posible quitar subcategorias con productos asociados: " + ", ".join(sorted(en_uso)))
    categoria.nombre = data.nombre
    categoria.descripcion = data.descripcion
    categoria.activo = data.activo
    if data.imagen is not None:
        categoria.imagen = data.imagen
    for s in quitar:
        db.delete(s)
    vistos = set()
    for nombre in data.subcategorias:
        if nombre not in por_nombre and nombre not in vistos:
            db.add(SubCategoria(nombre=nombre, categoria_id=item_id))
        vistos.add(nombre)
    if not _commit(db):
        return _fail(409, "No se pudo actualizar la categoria: viola una restricción de integridad")
    return BaseResponse(mensaje="Categoria actualizada exitosamente", success=True)


@router.put("/admin/categoria/{item_id}", response_model=BaseResponse, responses=ERRORES,
            summary="Actualizar categoría y subcategorías — updateCategoria")
def actualizar_categoria(item_id: int, data: CategoriaCreateRequest, db: DB):
    return _actualizar_categoria(item_id, data, db)


@router.patch("/admin/categoria/{item_id}", response_model=BaseResponse, responses=ERRORES,
              summary="Alias de PUT (reemplaza el PATCH genérico sin validación; requiere el cuerpo completo)")
def actualizar_categoria_patch(item_id: int, data: CategoriaCreateRequest, db: DB):
    return _actualizar_categoria(item_id, data, db)


@router.patch("/admin/categoria/{item_id}/disable", response_model=EstadoActivoResponse, responses=ERRORES,
              summary="Habilitar/deshabilitar categoría — changeEstadoCategoria")
def cambiar_estado_categoria(item_id: int, db: DB):
    categoria = db.get(Categoria, item_id)
    if not categoria:
        return _categoria_no_existe(item_id)
    categoria.activo = not bool(categoria.activo)
    db.commit()
    mensaje = "Categoría habilitada exitosamente" if categoria.activo else "Categoría deshabilitada exitosamente"
    return EstadoActivoResponse(mensaje=mensaje, success=True, id=item_id, activo=categoria.activo)


@router.delete("/admin/categoria/{item_id}", response_model=BaseResponse, responses=ERRORES,
               summary="Eliminar categoría y sus subcategorías (solo sin productos) — deleteCategoria")
def eliminar_categoria(item_id: int, db: DB):
    categoria = db.get(Categoria, item_id)
    if not categoria:
        return _categoria_no_existe(item_id)
    sub_ids = list(db.scalars(select(SubCategoria.subcategoria_id).where(SubCategoria.categoria_id == item_id)))
    con_productos = db.scalar(select(Producto.producto_id).where(Producto.categoria_id == item_id).limit(1))
    if con_productos is None and sub_ids:
        con_productos = db.scalar(select(Producto.producto_id).where(Producto.subcategoria_id.in_(sub_ids)).limit(1))
    if con_productos is not None:
        return _fail(409, "No es posible eliminar una categoria con productos")
    for sub in db.scalars(select(SubCategoria).where(SubCategoria.categoria_id == item_id)):
        db.delete(sub)
    db.flush()
    db.delete(categoria)
    if not _commit(db):
        return _fail(409, "No es posible eliminar la categoria: tiene registros asociados")
    return BaseResponse(mensaje="categoria eliminada exitosamente", success=True)


# ---------------------------------------------------------------------------------------------------------------------
# Compra (/admin/compra)
# ---------------------------------------------------------------------------------------------------------------------
@router.get("/admin/compra", response_model=list[CompraDashboardResponse],
            summary="Compras con su usuario, más recientes primero — getCompraByOrderAndFechaDesc")
def listar_compras(db: DB, offset: int = Query(0, ge=0),
                   limit: int | None = Query(None, ge=1, le=10000, description="Sin límite por defecto (como Spring)")):
    stmt = (select(Compra, Usuario)
            .join(Usuario, Usuario.usuario_id == Compra.usuario_id)
            .order_by(Compra.fecha.desc(), Compra.compra_id.desc())
            .offset(offset))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [CompraDashboardResponse(
        compra_id=c.compra_id, numero_orden=f"ORD-{c.compra_id:04d}",
        usuario_nombre_completo=_nombre(u.nombres, u.apellidos), usuario_imagen_url=cloudinary_url(u.imagen),
        metodo_pago=DESCRIPCION_METODO_PAGO.get(c.metodo_pago or "", c.metodo_pago), total=float(c.total or 0),
        fecha=c.fecha, estado=DESCRIPCION_ESTADO.get(c.estado or "", c.estado),
    ) for c, u in db.execute(stmt).all()]


def _compra_no_existe(item_id: int) -> JSONResponse:
    return _fail(404, f"La compra con id: {item_id} no existe.")


def _detalle_compra(item_id: int, db: Session):
    compra = db.get(Compra, item_id)
    if not compra:
        return _compra_no_existe(item_id)
    usuario = db.get(Usuario, compra.usuario_id) if compra.usuario_id else None
    empresa = db.get(Empresa, usuario.empresa_id) if usuario and usuario.empresa_id else None
    filas = db.execute(select(DetalleVenta, Producto)
                       .join(Producto, Producto.producto_id == DetalleVenta.producto_id)
                       .where(DetalleVenta.compra_id == item_id)
                       .order_by(DetalleVenta.detalle_venta_id)).all()
    return DetalleCompraResponse(
        compra_id=compra.compra_id, numero_orden=f"#FC{compra.compra_id:04d}",
        metodo_pago=DESCRIPCION_METODO_PAGO.get(compra.metodo_pago or "", compra.metodo_pago),
        subtotal=float(compra.subtotal or 0), cupon_descuento=compra.cupon_descuento, iva=float(compra.iva or 0),
        total=float(compra.total or 0), fecha=compra.fecha,
        estado=DESCRIPCION_ESTADO.get(compra.estado or "", compra.estado),
        usuario_id=usuario.usuario_id if usuario else None,
        usuario_nombre_completo=_nombre(usuario.nombres, usuario.apellidos) if usuario else None,
        usuario_correo=usuario.correo if usuario else None, usuario_telefono=usuario.telefono if usuario else None,
        usuario_direccion=usuario.direccion if usuario else None,
        ciudad_empresa=empresa.ciudad if empresa else "",
        productos=[DetalleProductoResponse(
            producto_id=p.producto_id, nombre=p.nombre, imagen=cloudinary_url(p.imagen), marca=p.marca, tipo=p.tipo,
            precio_unitario=float(d.precio_unitario or 0), cantidad=int(d.cantidad or 0),
            subtotal=float(d.subtotal or 0),
        ) for d, p in filas],
    )


@router.get("/admin/compra/{item_id}", response_model=DetalleCompraResponse, responses=ERRORES,
            summary="Detalle de compra — getDetalleCompra")
def detalle_compra(item_id: int, db: DB):
    return _detalle_compra(item_id, db)


@router.patch("/admin/compra/{item_id}/estado", response_model=EstadoCompraResponse, responses=ERRORES,
              summary="Cambiar estado de la compra — changeEstadoCompra")
def cambiar_estado_compra(item_id: int, data: CambiarEstadoCompraRequest, db: DB):
    compra = db.get(Compra, item_id)
    if not compra:
        return _compra_no_existe(item_id)
    compra.estado = data.estado
    if not _commit(db):
        return _fail(409, "No se pudo cambiar el estado")
    return EstadoCompraResponse(mensaje="Estado cambiado exitosamente", success=True, id=item_id, estado=data.estado)
