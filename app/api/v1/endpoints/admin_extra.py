"""Páginas de administración de Spring expuestas como API REST.

Equivalentes de ``ClientesController``, ``ProvedoresController``, ``BlogController``,
``PQRS_Controller``, ``ResennaController`` y ``DashboardController``: devuelven los mismos datos que
reciben las vistas Thymeleaf (``UsuarioGastoResponse``, ``ProveedorResponse``, ``HistoriaResponse``…)
y aplican las mismas reglas de negocio. Diferencias deliberadas respecto a Spring:

* Se usan verbos REST (POST crear, PUT actualizar, PATCH .../disable alternar, DELETE eliminar)
  en lugar de GET + redirect; las respuestas son ``{"mensaje", "success"}`` con su código HTTP.
* Nunca se devuelve ``password`` (Spring lo enviaba al formulario de edición).
* Las imágenes se reciben como ``public_id`` o URL ya subida a Cloudinary (no multipart).
* En actualizaciones de usuario la contraseña es opcional (Spring obligaba a reescribirla).

Productos, categorías y compras están en ``admin_catalogo.py``; gráficas, reportes y búsqueda en
``admin_graficas.py``, ``admin_reportes.py`` y ``admin_search.py``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import extract, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.cache import cache_auth_credentials, cache_auth_user, cache_delete, credential_cache_key, user_cache_key
from app.core.database import get_db
from app.core.media import cloudinary_url
from app.core.security import hash_password
from app.dependencies import admin_user
from app.models import (Comentario, Compra, DetalleFactura, DetalleVenta, Empresa, FacturaProveedor, Historia,
                        Peticion, Producto, Rol, Usuario)

router = APIRouter(tags=["Administración"], dependencies=[Depends(admin_user)])
DB = Annotated[Session, Depends(get_db)]

ROLES_CLIENTE_LISTADO = ("INVITADO", "PERSONA_CONTACTO", "PERSONA_JURIDICA", "PERSONA_NATURAL")
TIPOS_IDENTIFICACION = {
    "CC": "Cédula de Ciudadanía", "CE": "Cédula de Extranjería", "DE": "Documento de Extranjería",
    "NIT": "Número de Identificación Tributaria", "PP": "Pasaporte", "TE": "Tarjeta de Extranjería",
    "TI": "Tarjeta de Identidad",
}
TipoIdentificacion = Literal["CC", "CE", "DE", "NIT", "PP", "TE", "TI"]
ESTADOS_PETICION = {"RESUELTO": "Resuelto", "EN_PROCESO": "En Proceso", "PENDIENTE": "Pendiente"}
TIPOS_PETICION = {"PETICION": "Peticion", "QUEJA": "Queja", "RECLAMO": "Reclamo", "SUGERENCIA": "Sugerencia"}


# --------------------------------------------------------------------------- utilidades
class CamelModel(BaseModel):
    """Acepta los nombres de Spring (camelCase) y también snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)


def ok(mensaje: str, status_code: int = 200, **extra) -> JSONResponse:
    """``BaseResponse`` de Spring: ``{"mensaje", "success"}``."""
    return JSONResponse(status_code=status_code, content={"mensaje": mensaje, "success": status_code < 400, **extra})


def error(status_code: int, mensaje: str) -> HTTPException:
    return HTTPException(status_code, detail={"mensaje": mensaje, "success": False})


def _get(db: Session, model, item_id: int, nombre: str):
    item = db.get(model, item_id)
    if item is None:
        raise error(404, f"{nombre} no encontrado con id {item_id}")
    return item


def _commit(db: Session, mensaje_conflicto: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error(409, mensaje_conflicto) from exc


def _invalidar_usuario(usuario: Usuario, *correos: str | None) -> None:
    cache_delete(user_cache_key(int(usuario.usuario_id)))
    for correo in {usuario.correo, *correos} - {None}:
        cache_delete(credential_cache_key(correo))


def _rol(db: Session, nombre: str) -> Rol:
    rol = db.scalar(select(Rol).where(Rol.rol == nombre))
    if rol is None:
        raise error(409, f"error: el rol {nombre} no existe en la BD")
    return rol


def _nombre_completo(nombres: str | None, apellidos: str | None) -> str:
    return f"{nombres or ''} {apellidos or ''}".strip()


def _opciones_identificacion() -> dict:
    return {"tiposIdentificacion": [{"codigo": k, "descripcion": v} for k, v in TIPOS_IDENTIFICACION.items()]}


# --------------------------------------------------------------------------- panel principal
@router.get("/admin/principal", summary="Datos del panel principal (DashboardController)")
def dashboard_admin(usuario: Annotated[Usuario, Depends(admin_user)], db: DB) -> dict:
    """Mismos datos que la vista ``Dashboard`` de Spring (= ``/api/graficas/dashboard``).

    Se conservan, por compatibilidad con clientes anteriores de esta API, los contadores
    ``totalProductos``, ``totalCompras``, ``totalProveedores``, ``ventasTotales`` y ``comprasPendientes``.
    ``totalClientes`` sigue ahora el criterio de Spring (solo roles de cliente).
    """
    from app.api.v1.endpoints.admin_graficas import dashboard as dashboard_graficas

    datos = dashboard_graficas(usuario, db)
    datos.update({
        "totalProductos": db.scalar(select(func.count()).select_from(Producto)) or 0,
        "totalCompras": db.scalar(select(func.count()).select_from(Compra)) or 0,
        "totalProveedores": db.scalar(select(func.count()).select_from(FacturaProveedor)) or 0,
        "ventasTotales": float(db.scalar(select(func.coalesce(func.sum(Compra.total), 0))
                                         .where(Compra.estado == "PAGADO")) or 0),
        "comprasPendientes": db.scalar(select(func.count()).select_from(Compra)
                                       .where(Compra.estado == "PENDIENTE")) or 0,
    })
    return datos


# --------------------------------------------------------------------------- blog (historias)
class HistoriaRequest(CamelModel):
    imagen: str | None = Field(None, max_length=255, description="public_id o URL de Cloudinary")
    titulo: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(min_length=1, max_length=1000)
    historia_completa: str = Field(min_length=1)
    activo: bool = False


def _historia(h: Historia) -> dict:
    return {"id": h.historia_id, "imagen": cloudinary_url(h.imagen), "titulo": h.titulo,
            "descripcion": h.descripcion, "historiaCompleta": h.historia_completa,
            "fecha": h.fecha.isoformat() if h.fecha else None, "activo": bool(h.is_enabled)}


@router.get("/admin/blog", summary="Historias del blog (HistoriaResponse)")
def listar_blog(db: DB) -> list[dict]:
    return [_historia(h) for h in db.scalars(select(Historia).order_by(Historia.fecha.desc(), Historia.historia_id.desc()))]


@router.get("/admin/blog/{item_id}")
def obtener_blog(item_id: int, db: DB) -> dict:
    return _historia(_get(db, Historia, item_id, "Historia"))


@router.post("/admin/blog", status_code=201)
def crear_blog(data: HistoriaRequest, db: DB):
    if not data.imagen:
        raise error(422, "La imagen es obligatoria")
    h = Historia(imagen=data.imagen, titulo=data.titulo, descripcion=data.descripcion,
                 historia_completa=data.historia_completa, fecha=date.today(), is_enabled=data.activo)
    db.add(h)
    _commit(db, "No se pudo crear la historia")
    return ok("Historia creada exitosamente", 201, id=h.historia_id)


@router.put("/admin/blog/{item_id}")
def actualizar_blog(item_id: int, data: HistoriaRequest, db: DB):
    h = _get(db, Historia, item_id, "Historia")
    if data.imagen:
        h.imagen = data.imagen
    h.titulo, h.descripcion, h.historia_completa = data.titulo, data.descripcion, data.historia_completa
    h.fecha, h.is_enabled = date.today(), data.activo
    _commit(db, "No se pudo actualizar la historia")
    return ok("Historia actualizada exitosamente")


@router.patch("/admin/blog/{item_id}/disable")
def disable_blog(item_id: int, db: DB):
    h = _get(db, Historia, item_id, "Historia")
    h.is_enabled = not bool(h.is_enabled)
    _commit(db, "No se pudo cambiar el estado")
    return ok("Historia habilitada exitosamente" if h.is_enabled else "Historia deshabilitada exitosamente",
              activo=h.is_enabled)


@router.delete("/admin/blog/{item_id}")
def eliminar_blog(item_id: int, db: DB):
    h = _get(db, Historia, item_id, "Historia")
    db.delete(h)
    _commit(db, "La historia tiene comentarios asociados; deshabilítala en lugar de eliminarla")
    return ok("Historia eliminada exitosamente")


# --------------------------------------------------------------------------- clientes
class ClienteRequest(CamelModel):
    imagen: str | None = Field(None, max_length=255, description="public_id o URL de Cloudinary")
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str = Field(min_length=1, max_length=15)
    nombres: str = Field(min_length=1, max_length=175)
    apellidos: str = Field(min_length=1, max_length=175)
    telefono: str = Field(min_length=1, max_length=20)
    correo: EmailStr
    direccion: str = Field(min_length=1, max_length=100)
    password: str | None = Field(None, min_length=8, max_length=72)


@router.get("/admin/clientes", summary="Clientes con su gasto del último año (UsuarioGastoResponse)")
def listar_clientes(db: DB) -> list[dict]:
    desde = datetime.now() - timedelta(days=365)
    gastado = func.coalesce(func.sum(Compra.total), 0)
    filas = db.execute(
        select(Usuario, gastado)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .outerjoin(Compra, (Compra.usuario_id == Usuario.usuario_id) & (Compra.fecha >= desde)
                   & (Compra.estado == "PAGADO"))
        .where(Usuario.account_non_locked.is_(True), Rol.rol.in_(ROLES_CLIENTE_LISTADO))
        .group_by(Usuario.usuario_id)
        .order_by(gastado.desc())
    ).all()
    return [{"usuarioId": u.usuario_id, "imagen": cloudinary_url(u.imagen),
             "nombreCompleto": _nombre_completo(u.nombres, u.apellidos), "correo": u.correo,
             "telefono": u.telefono, "totalGastado": float(total or 0), "isEnabled": bool(u.is_enabled)}
            for u, total in filas]


@router.get("/admin/clientes/opciones", summary="Datos del formulario de cliente")
def opciones_cliente() -> dict:
    return _opciones_identificacion()


@router.get("/admin/clientes/{item_id}", summary="Cliente para el formulario de edición (ClienteResponse)")
def obtener_cliente(item_id: int, db: DB) -> dict:
    u = _get(db, Usuario, item_id, "Cliente")
    return {"clienteId": u.usuario_id, "tipoIdentificacion": u.tipo_identificacion,
            "numeroIdentificacion": u.numero_identificacion, "imagen": cloudinary_url(u.imagen),
            "nombres": u.nombres, "apellidos": u.apellidos, "telefono": u.telefono, "correo": u.correo,
            "direccion": u.direccion}


def _correo_libre(db: Session, correo: str, excepto: int | None = None) -> None:
    q = select(Usuario.usuario_id).where(func.lower(Usuario.correo) == correo.lower())
    if excepto is not None:
        q = q.where(Usuario.usuario_id != excepto)
    if db.scalar(q) is not None:
        raise error(409, f"El correo {correo} ya está registrado")


@router.post("/admin/clientes", status_code=201)
def crear_cliente(data: ClienteRequest, db: DB):
    if not data.password:
        raise error(422, "La contraseña es obligatoria")
    _correo_libre(db, data.correo)
    # Igual que Spring: NIT -> persona jurídica; cualquier otro documento -> persona natural.
    rol = _rol(db, "PERSONA_JURIDICA" if data.tipo_identificacion == "NIT" else "PERSONA_NATURAL")
    u = Usuario(tipo_identificacion=data.tipo_identificacion, numero_identificacion=data.numero_identificacion,
                imagen=data.imagen, nombres=data.nombres, apellidos=data.apellidos, telefono=data.telefono,
                correo=data.correo, password=hash_password(data.password), direccion=data.direccion,
                rol_id=rol.rol_id, is_enabled=True, account_non_expired=True, account_non_locked=True,
                credentials_non_expired=True)
    db.add(u)
    _commit(db, "No se pudo crear el cliente: teléfono o documento duplicado")
    cache_auth_user(u, rol.rol)
    cache_auth_credentials(u.correo, int(u.usuario_id), u.password)
    return ok("Usuario creado exitosamente", 201, id=u.usuario_id)


def _aplicar_datos_usuario(u: Usuario, data: ClienteRequest) -> None:
    u.tipo_identificacion, u.numero_identificacion = data.tipo_identificacion, data.numero_identificacion
    u.nombres, u.apellidos, u.telefono = data.nombres, data.apellidos, data.telefono
    u.correo, u.direccion = data.correo, data.direccion
    if data.imagen:
        u.imagen = data.imagen
    if data.password:
        u.password = hash_password(data.password)


@router.put("/admin/clientes/{item_id}")
def actualizar_cliente(item_id: int, data: ClienteRequest, db: DB):
    u = _get(db, Usuario, item_id, "Cliente")
    correo_anterior = u.correo
    _correo_libre(db, data.correo, excepto=item_id)
    _aplicar_datos_usuario(u, data)
    _commit(db, "No se pudo actualizar el cliente: teléfono o documento duplicado")
    _invalidar_usuario(u, correo_anterior)
    return ok("Cliente actualizado exitosamente")


def _alternar_usuario(db: Session, item_id: int, nombre: str):
    u = _get(db, Usuario, item_id, nombre)
    u.is_enabled = not bool(u.is_enabled)
    _commit(db, "No se pudo cambiar el estado")
    _invalidar_usuario(u)
    return ok("Usuario habilitado exitosamente" if u.is_enabled else "Usuario deshabilitado exitosamente",
              isEnabled=u.is_enabled)


def _eliminar_usuario(db: Session, item_id: int, nombre: str):
    """Borrado lógico como Spring: ``account_non_locked = False`` (preserva compras y facturas)."""
    u = _get(db, Usuario, item_id, nombre)
    u.account_non_locked = False
    _commit(db, "No se pudo eliminar el usuario")
    _invalidar_usuario(u)
    return ok("Usuario eliminado exitosamente")


@router.patch("/admin/clientes/{item_id}/disable")
def disable_cliente(item_id: int, db: DB):
    return _alternar_usuario(db, item_id, "Cliente")


@router.delete("/admin/clientes/{item_id}")
def eliminar_cliente(item_id: int, db: DB):
    return _eliminar_usuario(db, item_id, "Cliente")


# --------------------------------------------------------------------------- proveedores
class ProveedorRequest(ClienteRequest):
    imagen_empresa: str | None = Field(None, max_length=255, description="public_id o URL de Cloudinary")
    nit: str = Field(min_length=1, max_length=12)
    razon_social: str = Field(min_length=1, max_length=175)
    ciudad: str = Field(min_length=1, max_length=255)
    direccion_empresa: str = Field(min_length=1, max_length=255)
    telefono_empresa: str = Field(min_length=1, max_length=20)
    correo_empresa: EmailStr


@router.get("/admin/provedores", summary="Proveedores con gasto y ganancia del año (ProveedorEstadisticasResponse)")
def listar_proveedores(db: DB) -> list[dict]:
    anio = date.today().year
    gastado = func.coalesce(func.sum(FacturaProveedor.total), 0)
    ganado = (
        select(func.coalesce(func.sum(DetalleVenta.subtotal), 0))
        .join(Compra, Compra.compra_id == DetalleVenta.compra_id)
        .join(Producto, Producto.producto_id == DetalleVenta.producto_id)
        .where(Producto.usuario_id == Usuario.usuario_id, Compra.estado == "PAGADO",
               extract("year", Compra.fecha) == anio)
        .correlate(Usuario)
        .scalar_subquery()
    )
    filas = db.execute(
        select(Usuario, Empresa, gastado, ganado)
        .join(Empresa, Empresa.empresa_id == Usuario.empresa_id)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .outerjoin(FacturaProveedor, (FacturaProveedor.usuario_id == Usuario.usuario_id)
                   & FacturaProveedor.activo.is_(True)
                   & (extract("year", FacturaProveedor.fecha_emision) == anio))
        .where(Rol.rol == "PROVEEDOR", Usuario.account_non_locked.is_(True))
        .group_by(Usuario.usuario_id, Empresa.empresa_id)
        .order_by(gastado.desc())
    ).all()
    return [{"usuarioId": u.usuario_id, "imagenEmpresa": cloudinary_url(e.imagen), "nombreEmpresa": e.razon_social,
             "nombreCompleto": _nombre_completo(u.nombres, u.apellidos), "correo": u.correo,
             "totalGastado": float(g or 0), "totalGanado": float(gan or 0), "isEnabled": bool(u.is_enabled)}
            for u, e, g, gan in filas]


@router.get("/admin/provedores/opciones", summary="Datos del formulario de proveedor")
def opciones_proveedor() -> dict:
    return _opciones_identificacion()


@router.get("/admin/provedores/productos/{proveedor_id}",
            summary="Productos activos del proveedor para una factura de compra (FacturaProductoProveedorResponse)")
def productos_proveedor(proveedor_id: int, db: DB) -> list[dict]:
    productos = db.scalars(select(Producto).where(Producto.usuario_id == proveedor_id, Producto.activo.is_(True))
                           .order_by(Producto.nombre))
    return [{"id": p.producto_id, "nombre": p.nombre, "codigoProducto": p.codigo_producto, "marca": p.marca,
             "precio": float(p.precio or 0), "stock": p.stock} for p in productos]


@router.get("/admin/provedores/{item_id}", summary="Proveedor y su empresa (ProveedorResponse)")
def obtener_proveedor(item_id: int, db: DB) -> dict:
    u = _get(db, Usuario, item_id, "Proveedor")
    e = db.get(Empresa, u.empresa_id) if u.empresa_id else None
    return {"proveedorId": u.usuario_id, "tipoIdentificacion": u.tipo_identificacion,
            "numeroIdentificacion": u.numero_identificacion, "imagen": cloudinary_url(u.imagen),
            "nombres": u.nombres, "apellidos": u.apellidos, "telefono": u.telefono, "correo": u.correo,
            "direccion": u.direccion, "empresaId": e.empresa_id if e else None,
            "imagenEmpresa": cloudinary_url(e.imagen) if e else None, "nit": e.nit if e else None,
            "razonSocial": e.razon_social if e else None, "ciudad": e.ciudad if e else None,
            "direccionEmpresa": e.direccion if e else None, "telefonoEmpresa": e.telefono if e else None,
            "correoEmpresa": e.correo if e else None}


@router.post("/admin/provedores", status_code=201)
def crear_proveedor(data: ProveedorRequest, db: DB):
    if not data.password:
        raise error(422, "La contraseña es obligatoria")
    _correo_libre(db, data.correo)
    rol = _rol(db, "PROVEEDOR")
    if db.scalar(select(Empresa.empresa_id).where(Empresa.nit == data.nit)) is not None:
        raise error(409, f"error: La empresa con el nit '{data.nit}' ya tiene un usuario asignado. Si usted es "
                         "el nuevo representante, use el formulario de contacto para solicitar la actualización.")
    empresa = Empresa(imagen=data.imagen_empresa, nit=data.nit, razon_social=data.razon_social, ciudad=data.ciudad,
                      direccion=data.direccion_empresa, telefono=data.telefono_empresa, correo=data.correo_empresa,
                      activo=True)
    db.add(empresa)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise error(409, "Razón social, teléfono o correo de la empresa ya registrados") from exc
    u = Usuario(tipo_identificacion=data.tipo_identificacion, numero_identificacion=data.numero_identificacion,
                imagen=data.imagen, nombres=data.nombres, apellidos=data.apellidos, telefono=data.telefono,
                correo=data.correo, password=hash_password(data.password), direccion=data.direccion,
                empresa_id=empresa.empresa_id, rol_id=rol.rol_id, is_enabled=True, account_non_expired=True,
                account_non_locked=True, credentials_non_expired=True)
    db.add(u)
    _commit(db, "No se pudo crear el proveedor: teléfono o documento duplicado")
    cache_auth_user(u, "PROVEEDOR")
    cache_auth_credentials(u.correo, int(u.usuario_id), u.password)
    return ok("Proveedor creado exitosamente", 201, id=u.usuario_id, empresaId=empresa.empresa_id)


@router.put("/admin/provedores/{item_id}")
def actualizar_proveedor(item_id: int, data: ProveedorRequest, db: DB):
    u = _get(db, Usuario, item_id, "Proveedor")
    e = db.get(Empresa, u.empresa_id) if u.empresa_id else None
    if e is None:
        raise error(409, "El proveedor no tiene una empresa asociada.")
    correo_anterior = u.correo
    _correo_libre(db, data.correo, excepto=item_id)
    _aplicar_datos_usuario(u, data)
    e.nit, e.razon_social, e.ciudad = data.nit, data.razon_social, data.ciudad
    e.direccion, e.telefono, e.correo = data.direccion_empresa, data.telefono_empresa, data.correo_empresa
    if data.imagen_empresa:
        e.imagen = data.imagen_empresa
    _commit(db, "No se pudo actualizar el proveedor: NIT, razón social, teléfono o correo duplicados")
    _invalidar_usuario(u, correo_anterior)
    return ok("Proveedor actualizado exitosamente")


@router.patch("/admin/provedores/{item_id}/disable")
def disable_proveedor(item_id: int, db: DB):
    return _alternar_usuario(db, item_id, "Proveedor")


@router.delete("/admin/provedores/{item_id}")
def eliminar_proveedor(item_id: int, db: DB):
    return _eliminar_usuario(db, item_id, "Proveedor")


class DetalleFacturaRequest(CamelModel):
    producto_id: int
    cantidad: int = Field(ge=1)
    precio_compra: int = Field(ge=0)
    subtotal: int | None = Field(None, ge=0)


class FacturaProveedorRequest(CamelModel):
    numero_factura: str = Field(min_length=1, max_length=255)
    fecha_emision: date
    detalles: list[DetalleFacturaRequest] = Field(min_length=1)
    total_compra: float = Field(ge=0)
    proveedor_id: int

    @field_validator("detalles")
    @classmethod
    def _sin_productos_repetidos(cls, detalles: list[DetalleFacturaRequest]) -> list[DetalleFacturaRequest]:
        ids = [d.producto_id for d in detalles]
        if len(ids) != len(set(ids)):
            raise ValueError("Un producto no puede aparecer dos veces en la misma factura")
        return detalles


@router.post("/admin/provedores/compras", status_code=201,
             summary="Registrar factura de compra a proveedor (suma el stock de cada producto)")
def crear_factura_proveedor(data: FacturaProveedorRequest, db: DB):
    if db.scalar(select(FacturaProveedor.factura_id).where(FacturaProveedor.numero_factura == data.numero_factura)):
        raise error(409, f"Ya existe una factura con el número: {data.numero_factura}")
    _get(db, Usuario, data.proveedor_id, "Proveedor")
    factura = FacturaProveedor(numero_factura=data.numero_factura, fecha_emision=data.fecha_emision,
                               fecha_registro=datetime.now(), total=data.total_compra, activo=True,
                               usuario_id=data.proveedor_id)
    db.add(factura)
    db.flush()
    for d in data.detalles:
        producto = db.scalar(select(Producto).where(Producto.producto_id == d.producto_id,
                                                    Producto.usuario_id == data.proveedor_id))
        if producto is None:
            db.rollback()
            raise error(404, f"Producto no encontrado o no pertenece al proveedor: {d.producto_id}")
        subtotal = d.subtotal if d.subtotal is not None else d.cantidad * d.precio_compra
        db.add(DetalleFactura(cantidad=d.cantidad, precio_compra=d.precio_compra, subtotal=subtotal,
                              factura_id=factura.factura_id, producto_id=producto.producto_id))
        producto.stock = (producto.stock or 0) + d.cantidad
    _commit(db, "No se pudo registrar la factura")
    return ok("Factura de compra registrada exitosamente", 201, id=factura.factura_id)


# --------------------------------------------------------------------------- PQRS
class EstadoPeticionRequest(CamelModel):
    estado_peticion: str | None = None
    estado: str | None = None


def _codigo_estado_peticion(valor: str | None) -> str:
    """Acepta lo que envía la vista de Spring ("Resuelto", "En Proceso", "Pendiente") o el código del enum."""
    texto = (valor or "").strip().upper().replace(" ", "_")
    if texto not in ESTADOS_PETICION:
        raise error(422, f"Estado Invalido {valor}")
    return texto


def _peticion(p: Peticion, u: Usuario | None) -> dict:
    return {"id": p.peticion_id, "tipoPeticion": TIPOS_PETICION.get(p.tipo or "", p.tipo), "asunto": p.asunto,
            "mensaje": p.mensaje, "fecha": p.fecha.isoformat() if p.fecha else None,
            "estadoPeticion": ESTADOS_PETICION.get(p.estado or "", p.estado), "activo": bool(p.activo),
            # "usurarioResponse" (sic): mismo nombre que el record de Spring.
            "usurarioResponse": {"nombres": u.nombres, "apellidos": u.apellidos, "correo": u.correo,
                                 "telefono": u.telefono} if u else None}


@router.get("/admin/pqrs", summary="Peticiones activas (PeticionResponse)")
def listar_pqrs(db: DB) -> list[dict]:
    filas = db.execute(select(Peticion, Usuario).outerjoin(Usuario, Usuario.usuario_id == Peticion.usuario_id)
                       .where(Peticion.activo.is_(True)).order_by(Peticion.fecha.desc())).all()
    return [_peticion(p, u) for p, u in filas]


@router.patch("/admin/pqrs/{item_id}/estado")
def estado_pqrs(item_id: int, data: EstadoPeticionRequest, db: DB):
    p = _get(db, Peticion, item_id, "Petición")
    p.estado = _codigo_estado_peticion(data.estado_peticion or data.estado)
    _commit(db, "No se pudo cambiar el estado")
    return ok("Estado cambiado exitosamente", estado=p.estado)


@router.delete("/admin/pqrs/{item_id}")
def eliminar_pqrs(item_id: int, db: DB):
    p = _get(db, Peticion, item_id, "Petición")
    p.activo = False
    _commit(db, "No se pudo eliminar la petición")
    return ok("Petición eliminada exitosamente")


# --------------------------------------------------------------------------- reseñas (comentarios)
@router.get("/admin/resenna", summary="Comentarios del blog (ComentarioResponse)")
def listar_resenas(db: DB) -> list[dict]:
    filas = db.execute(
        select(Comentario, Usuario, Historia)
        .outerjoin(Usuario, Usuario.usuario_id == Comentario.usuario_id)
        .outerjoin(Historia, Historia.historia_id == Comentario.historia_id)
        .order_by(Comentario.fecha.desc(), Comentario.comentario_id.desc())
    ).all()
    return [{"id": c.comentario_id, "titulo": c.titulo, "mensaje": c.mensaje, "calificacion": c.calificacion,
             "fecha": c.fecha.isoformat() if c.fecha else None, "estado": bool(c.activo),
             "usuarioResponse": {"nombres": u.nombres, "apellidos": u.apellidos, "correo": u.correo} if u else None,
             "blogResponse": {"titulo": h.titulo} if h else None}
            for c, u, h in filas]


@router.patch("/admin/resenna/{item_id}/disable")
def disable_resena(item_id: int, db: DB):
    c = _get(db, Comentario, item_id, "Comentario")
    c.activo = not bool(c.activo)
    _commit(db, "No se pudo cambiar el estado")
    return ok("Comentario habilitado exitosamente" if c.activo else "Comentario deshabilitado exitosamente",
              estado=c.activo)


@router.delete("/admin/resenna/{item_id}")
def eliminar_resena(item_id: int, db: DB):
    """Borrado físico como Spring (el admin puede borrar cualquier comentario)."""
    c = _get(db, Comentario, item_id, "Comentario")
    db.delete(c)
    _commit(db, "No se pudo eliminar el comentario")
    return ok("Comentario eliminado exitosamente")
