"""Búsqueda universal del panel de administración (equivalente a SearchController de Spring).

Contrato idéntico a ``SearchController`` + ``SearchServiceImpl`` + ``SearchResponse`` /
``SearchItemResponse`` de Spring: mismas claves camelCase (todas presentes, con ``null`` cuando
no hay valor, como serializa Jackson), mismas reglas de coincidencia, límites y mensajes.

Autenticación (como ``SecurityConfig`` de Spring, que la declara pública): cualquiera puede buscar
productos, categorías y blog. Clientes y proveedores solo se devuelven a un ADMIN.
Corrección respecto a Spring: allí una búsqueda anónima SIN ``tipo`` incluía clientes y proveedores
(nombres y correos); aquí, sin rol ADMIN esas listas siempre van vacías.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.media import cloudinary_url
from app.api.deps import ADMIN_EMAIL_HEADER, admin_user, api_key_header, security
from app.models.entities import Categoria, Empresa, Historia, Producto, Rol, Usuario

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["Búsqueda"])

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
MAX_LIMIT = 50
ROLES_CLIENTE = ("PERSONA_CONTACTO", "PERSONA_NATURAL", "PERSONA_JURIDICA", "INVITADO")
ROL_PROVEEDOR = "PROVEEDOR"
TIPOS_SOLO_ADMIN = ("clientes", "proveedores")


def es_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> bool:
    """Autenticación opcional: True con un JWT de ADMIN, o con la API key de servicio + ``X-Admin-Email``
    de un ADMIN (Spring); anónimo, inválido o sin rol -> False (solo resultados públicos)."""
    if credentials is None and not (api_key and request.headers.get(ADMIN_EMAIL_HEADER)):
        return False  # búsqueda anónima: ni siquiera se intenta (no ensucia el registro de accesos)
    try:
        admin_user(request, db, credentials, api_key)
        return True
    except HTTPException:
        return False


class SearchItemResponse(BaseModel):
    id: int | None = None
    type: str | None = None
    titulo: str | None = None
    subtitulo: str | None = None
    descripcion: str | None = None
    imagen: str | None = None
    icono: str | None = None
    url: str | None = None
    badge: str | None = None
    badgeClass: str | None = None


class SearchResponse(BaseModel):
    productos: list[SearchItemResponse] = Field(default_factory=list)
    categorias: list[SearchItemResponse] = Field(default_factory=list)
    clientes: list[SearchItemResponse] = Field(default_factory=list)
    proveedores: list[SearchItemResponse] = Field(default_factory=list)
    blog: list[SearchItemResponse] = Field(default_factory=list)
    totalResults: int | None = None
    query: str | None = None
    success: bool = False
    message: str | None = None


# ====== UTILIDADES (mismas que SearchServiceImpl) ======

def _truncar(texto: str | None, maximo: int) -> str:
    if texto is None:
        return ""
    if len(texto) <= maximo:
        return texto
    return texto[:maximo] + "..."


def _safe(value: str | None) -> str:
    return "" if value is None else value


def _java_str(value) -> str:
    """Concatenación de String en Java: ``null`` se convierte en el texto "null"."""
    return "null" if value is None else str(value)


def _imagen_cloudinary(imagen: str | None) -> str | None:
    """Mismo flujo que ``SearchServiceImpl.imagenCloudinary`` usando el helper compartido."""
    try:
        return cloudinary_url(imagen)
    except Exception:  # pragma: no cover - mismo comportamiento defensivo que Spring
        logger.warning("No fue posible generar la URL de Cloudinary para '%s'", imagen)
        return None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _containing_ignore_case(column, query: str):
    """Spring Data ``...ContainingIgnoreCase``: escapa comodines del término."""
    return func.upper(column).like(func.upper(f"%{_escape_like(query)}%"), escape="\\")


def _jpql_like_lower(column, query: str):
    """JPQL ``LOWER(x) LIKE LOWER(CONCAT('%', :query, '%'))``: sin escapar comodines."""
    return func.lower(column).like(func.lower(f"%{query}%"))


# ====== MAPEOS A DTO ======

def _map_producto(p: Producto) -> SearchItemResponse:
    en_stock = (p.stock or 0) > 0
    return SearchItemResponse(
        id=p.producto_id,
        type="producto",
        titulo=p.nombre,
        subtitulo=f"{_java_str(p.marca)} - {_java_str(p.pais)}",
        descripcion=_truncar(p.descripcion, 100),
        imagen=_imagen_cloudinary(p.imagen),
        url=f"/ver?id={_java_str(p.codigo_producto)}",
        badge="En Stock" if en_stock else "Agotado",
        badgeClass="badge-success" if en_stock else "badge-danger",
    )


def _map_categoria(c: Categoria) -> SearchItemResponse:
    return SearchItemResponse(
        id=c.categoria_id,
        type="categoria",
        titulo=c.nombre,
        subtitulo="Categoría",
        imagen=_imagen_cloudinary(c.imagen),
        descripcion=_truncar(c.descripcion, 100),
        icono="ri-list-unordered",
        url=f"/productos?categoria={c.categoria_id}",
        badge="Categoría",
        badgeClass="badge-info",
    )


def _map_cliente(u: Usuario) -> SearchItemResponse:
    return SearchItemResponse(
        id=u.usuario_id,
        type="cliente",
        titulo=f"{_safe(u.nombres)} {_safe(u.apellidos)}",
        subtitulo=_safe(u.correo),
        imagen=_imagen_cloudinary(u.imagen),
        descripcion=f"Teléfono: {_safe(u.telefono)}",
        icono="ri-user-line",
        url=f"/admin/clientes/{u.usuario_id}",
        badge="Cliente",
        badgeClass="badge-primary",
    )


def _map_proveedor(u: Usuario, razon_social: str | None) -> SearchItemResponse:
    razon = _safe(razon_social)
    return SearchItemResponse(
        id=u.usuario_id,
        type="proveedor",
        titulo=_safe(u.nombres) if razon == "" else razon,
        subtitulo=_safe(u.correo),
        imagen=_imagen_cloudinary(u.imagen),
        descripcion=f"Teléfono: {_safe(u.telefono)}",
        icono="ri-store-2-line",
        url=f"/admin/proveedores/{u.usuario_id}",
        badge="Proveedor",
        badgeClass="badge-warning",
    )


def _map_blog(h: Historia) -> SearchItemResponse:
    return SearchItemResponse(
        id=h.historia_id,
        type="blog",
        titulo=h.titulo,
        subtitulo="Artículo de Blog",
        descripcion=_truncar(h.descripcion, 100),
        imagen=_imagen_cloudinary(h.imagen),
        icono="ri-news-line",
        url=f"/blog/info?id={h.historia_id}",
        badge="Blog",
        badgeClass="badge-secondary",
    )


# ====== CONSULTAS (mismos filtros que los repositorios de Spring) ======

def _buscar_productos(db: Session, q: str, limit: int) -> list[SearchItemResponse]:
    stmt = (
        select(Producto)
        .where(or_(
            _containing_ignore_case(Producto.nombre, q),
            _containing_ignore_case(Producto.marca, q),
            _containing_ignore_case(Producto.descripcion, q),
        ))
        .where(Producto.activo.is_(True))
        .order_by(Producto.producto_id)
        .limit(limit)
    )
    return [_map_producto(p) for p in db.scalars(stmt)]


def _buscar_categorias(db: Session, q: str, limit: int) -> list[SearchItemResponse]:
    stmt = (
        select(Categoria)
        .where(_containing_ignore_case(Categoria.nombre, q))
        .order_by(Categoria.categoria_id)
        .limit(limit)
    )
    return [_map_categoria(c) for c in db.scalars(stmt)]


def _buscar_clientes(db: Session, q: str, limit: int) -> list[SearchItemResponse]:
    stmt = (
        select(Usuario)
        .join(Rol, Usuario.rol_id == Rol.rol_id)
        .where(Usuario.account_non_locked.is_(True))
        .where(or_(
            _jpql_like_lower(Usuario.nombres, q),
            _jpql_like_lower(Usuario.apellidos, q),
            _jpql_like_lower(Usuario.correo, q),
        ))
        .where(Rol.rol.in_(ROLES_CLIENTE))
        .order_by(Usuario.usuario_id)
        .limit(limit)
    )
    return [_map_cliente(u) for u in db.scalars(stmt)]


def _buscar_proveedores(db: Session, q: str, limit: int) -> list[SearchItemResponse]:
    # u.empresa.razonSocial en el WHERE de JPQL implica INNER JOIN con empresa (Hibernate 6).
    stmt = (
        select(Usuario, Empresa.razon_social)
        .join(Rol, Usuario.rol_id == Rol.rol_id)
        .join(Empresa, Usuario.empresa_id == Empresa.empresa_id)
        .where(Usuario.account_non_locked.is_(True))
        .where(Rol.rol == ROL_PROVEEDOR)
        .where(or_(
            _jpql_like_lower(Usuario.nombres, q),
            _jpql_like_lower(Usuario.apellidos, q),
            _jpql_like_lower(Usuario.correo, q),
            _jpql_like_lower(Empresa.razon_social, q),
        ))
        .order_by(Usuario.usuario_id)
        .limit(limit)
    )
    return [_map_proveedor(u, razon) for u, razon in db.execute(stmt).all()]


def _buscar_blog(db: Session, q: str, limit: int) -> list[SearchItemResponse]:
    stmt = (
        select(Historia)
        .where(or_(
            _containing_ignore_case(Historia.titulo, q),
            _containing_ignore_case(Historia.descripcion, q),
        ))
        .where(Historia.is_enabled.is_(True))
        .order_by(Historia.historia_id)
        .limit(limit)
    )
    return [_map_blog(h) for h in db.scalars(stmt)]


def buscar_universal(db: Session, query: str, tipo: str | None, limit: int,
                     incluir_privados: bool = True) -> SearchResponse:
    response = SearchResponse(query=query, success=False)
    if query is None or not query.strip():
        response.message = "Búsqueda vacía"
        response.totalResults = 0
        return response

    try:
        if tipo is None or tipo == "productos":
            response.productos = _buscar_productos(db, query, limit)
        if tipo is None or tipo == "categorias":
            response.categorias = _buscar_categorias(db, query, limit)
        if incluir_privados and (tipo is None or tipo == "clientes"):
            response.clientes = _buscar_clientes(db, query, limit)
        if incluir_privados and (tipo is None or tipo == "proveedores"):
            response.proveedores = _buscar_proveedores(db, query, limit)
        if tipo is None or tipo == "blog":
            response.blog = _buscar_blog(db, query, limit)

        response.totalResults = (
            len(response.productos) + len(response.categorias) + len(response.clientes)
            + len(response.proveedores) + len(response.blog)
        )
        response.success = True
        response.message = "Búsqueda completada"
    except Exception:
        logger.exception("Error en búsqueda universal")
        response.productos, response.categorias, response.clientes = [], [], []
        response.proveedores, response.blog = [], []
        response.success = False
        response.message = "Error en la búsqueda"
        response.totalResults = 0
    return response


@router.get("/universal", response_model=SearchResponse)
def universal(
    q: str | None = Query(default=None),
    tipo: str | None = Query(default=None),
    limit: int = Query(default=10),
    db: Session = Depends(get_db),
    admin: bool = Depends(es_admin),
) -> SearchResponse:
    if q is None or len(q.strip()) < MIN_QUERY_LENGTH:
        return SearchResponse(
            success=False,
            message="El término de búsqueda debe tener al menos 2 caracteres",
            query=q,
            totalResults=0,
        )
    if len(q) > MAX_QUERY_LENGTH:
        return SearchResponse(
            success=False,
            message=f"El término de búsqueda no puede superar {MAX_QUERY_LENGTH} caracteres",
            query=q[:MAX_QUERY_LENGTH],
            totalResults=0,
        )

    safe_tipo = tipo.lower() if tipo is not None else None
    if safe_tipo in TIPOS_SOLO_ADMIN and not admin:
        logger.warning("Búsqueda '%s' bloqueada: usuario sin rol ADMIN", safe_tipo)
        return SearchResponse(success=False, query=q, message="No autorizado", totalResults=0)

    safe_limit = max(1, min(limit, MAX_LIMIT))
    logger.debug("Búsqueda universal -> q='%s' tipo='%s' limit=%s", q, safe_tipo, safe_limit)
    return buscar_universal(db, q, safe_tipo, safe_limit, incluir_privados=admin)
