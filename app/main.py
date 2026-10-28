from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, verify_password, is_bcrypt_hash, create_token
from app.dependencies import current_user, admin_user, user_role
from app.models import Usuario, Rol, Producto
from app.schemas import LoginRequest, RegisterRequest, AdminCreateRequest, UserResponse, ProductResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title=settings.app_name, version="3.1.0",
    description="API REST de Costa De Oro Imports migrada desde Spring Boot. Operaciones administrativas protegidas por rol ADMIN.",
    docs_url="/doc" if settings.springdoc_swagger_ui_enabled else None,
    openapi_url="/v3/api-docs" if settings.springdoc_api_docs_enabled else None,
    redoc_url="/redoc", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
logger = logging.getLogger(__name__)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/doc", status_code=307)

@app.get("/health", tags=["Sistema"])
def health():
    return {"status": "ok", "application": settings.app_name}

@app.get("/health/db", tags=["Sistema"])
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        logger.exception("Fallo la comprobación de conexión a la base de datos")
        raise HTTPException(503, "Base de datos no disponible") from exc

@app.post("/auth/login", tags=["Autenticación"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(Usuario).where(Usuario.correo == str(payload.username)))
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(401, "Credenciales inválidas")
    if not is_bcrypt_hash(user.password):
        user.password = hash_password(payload.password)
        db.commit()
    if user.is_enabled is not True or user.account_non_locked is False or user.account_non_expired is False or user.credentials_non_expired is False:
        raise HTTPException(403, "Cuenta deshabilitada, bloqueada o pendiente de aprobación")
    role = db.get(Rol, user.rol_id) if user.rol_id else None
    if not role or not role.rol:
        raise HTTPException(403, "La cuenta no tiene un rol válido asignado")
    token = create_token(str(user.usuario_id), role.rol)
    return {"accessToken": token, "token_type": "bearer", "expires_in": 3600,
            "usuario": {"usuarioId": user.usuario_id, "correo": user.correo,
                        "nombres": user.nombres, "apellidos": user.apellidos, "rol": role.rol}}

@app.post("/admin/usuario/admin", status_code=201, tags=["Administración"])
def create_admin_user(
    payload: AdminCreateRequest,
    db: Session = Depends(get_db),
    _: Usuario = Depends(admin_user),
):
    """Crea un administrador nuevo; solo puede hacerlo un ADMIN autenticado."""
    email = str(payload.correo).lower().strip()
    if db.scalar(select(Usuario.usuario_id).where(Usuario.correo == email)):
        raise HTTPException(409, "El correo ya está registrado")
    if payload.telefono and db.scalar(select(Usuario.usuario_id).where(Usuario.telefono == payload.telefono)):
        raise HTTPException(409, "El teléfono ya está registrado")

    admin_role = db.scalar(select(Rol).where(Rol.rol == "ADMIN"))
    if not admin_role:
        raise HTTPException(409, "No existe el rol ADMIN en la base de datos")

    admin = Usuario(
        correo=email,
        password=hash_password(payload.password),
        nombres=payload.nombres,
        apellidos=payload.apellidos,
        telefono=payload.telefono,
        rol_id=admin_role.rol_id,
        is_enabled=True,
        account_non_expired=True,
        account_non_locked=True,
        credentials_non_expired=True,
    )
    try:
        db.add(admin)
        db.commit()
        db.refresh(admin)
    except Exception as exc:
        db.rollback()
        raise HTTPException(409, "No se pudo crear el administrador; revisa los campos y duplicados") from exc
    return {"success": True, "mensaje": "Administrador creado", "usuarioId": admin.usuario_id}

@app.post("/auth/registro", status_code=201, tags=["Autenticación"], response_model=UserResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.correo).lower().strip()
    if db.scalar(select(Usuario).where(Usuario.correo == email)):
        raise HTTPException(409, detail={"mensaje": "El correo ya está registrado", "success": False})
    if payload.telefono and db.scalar(select(Usuario).where(Usuario.telefono == payload.telefono)):
        raise HTTPException(409, detail={"mensaje": "El teléfono ya está registrado", "success": False})
    # Nunca permitir que el registro público cree un administrador.
    role_name = (payload.rol or "PERSONA_NATURAL").upper()
    if role_name not in {"INVITADO", "PERSONA_CONTACTO", "PERSONA_JURIDICA", "PERSONA_NATURAL", "PROVEEDOR"}:
        raise HTTPException(403, "Ese rol no puede asignarse mediante registro público")
    role = db.scalar(select(Rol).where(Rol.rol == role_name))
    if not role:
        raise HTTPException(409, f"El rol {role_name} no existe en la tabla rol. Inicializa los roles antes de registrar usuarios.")
    # PERSONA_NATURAL es el único rol activado automáticamente. Los demás requieren aprobación de ADMIN.
    enabled = role_name == "PERSONA_NATURAL"
    user = Usuario(correo=email, password=hash_password(payload.password), nombres=payload.nombres,
        apellidos=payload.apellidos, telefono=payload.telefono, direccion=payload.direccion,
        tipo_identificacion=payload.tipo_identificacion, numero_identificacion=payload.numero_identificacion,
        rol_id=role.rol_id, is_enabled=enabled, account_non_expired=True,
        account_non_locked=True, credentials_non_expired=True)
    try:
        db.add(user); db.commit(); db.refresh(user)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, "No fue posible registrar el usuario; revisa correo, teléfono e identificación duplicados") from exc
    return user

@app.post("/auth/logout", tags=["Autenticación"])
def logout(_user: Usuario = Depends(current_user)):
    # JWT stateless: el cliente debe borrar el token. Para revocación inmediata multiinstancia se requiere blacklist persistente.
    return {"success": True, "mensaje": "Sesión cerrada en el cliente; elimina el accessToken almacenado"}

@app.get("/auth/catalogos", tags=["Autenticación"])
def catalogs():
    return {"tiposIdentificacion": ["CC", "CE", "DE", "NIT", "PP", "TE", "TI"],
            "sectores": ["BAR", "CAFE", "CATERING", "HOTEL", "NIGHTCLUB", "RESTAURANT"],
            "rolesRegistro": ["INVITADO", "PERSONA_CONTACTO", "PERSONA_JURIDICA", "PERSONA_NATURAL", "PROVEEDOR"],
            "nota": "PERSONA_NATURAL se activa automáticamente; los otros roles requieren aprobación administrativa. ADMIN nunca se asigna por registro público."}

@app.get("/perfil", tags=["Perfil"], response_model=UserResponse)
def profile(user: Usuario = Depends(current_user)):
    return user

@app.get("/perfil/configuracion", tags=["Perfil"])
def profile_config(user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return {"usuarioId": user.usuario_id, "correo": user.correo, "rol": user_role(user, db), "tieneEmpresa": bool(user.empresa_id)}

@app.get("/api/productos", tags=["Catálogo"], response_model=list[ProductResponse])
def public_products(offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100), db: Session = Depends(get_db)):
    return list(db.scalars(select(Producto).where(Producto.activo.is_(True)).offset(offset).limit(limit)))

@app.get("/api/productos/{producto_id}", tags=["Catálogo"], response_model=ProductResponse)
def public_product(producto_id: int, db: Session = Depends(get_db)):
    item = db.get(Producto, producto_id)
    if not item or not item.activo: raise HTTPException(404, "Producto no encontrado")
    return item

@app.get("/admin/usuario/pendientes", tags=["Administración"])
def usuarios_pendientes(db: Session = Depends(get_db), _: Usuario = Depends(admin_user)):
    return list(db.scalars(select(Usuario).where(Usuario.is_enabled.is_(False))))

@app.patch("/admin/usuario/{usuario_id}/activar", tags=["Administración"])
def activar_usuario(usuario_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin_user)):
    user = db.get(Usuario, usuario_id)
    if not user: raise HTTPException(404, "Usuario no encontrado")
    user.is_enabled = True
    db.commit()
    return {"success": True, "mensaje": "Usuario activado", "usuarioId": usuario_id}

@app.patch("/admin/usuario/{usuario_id}/desactivar", tags=["Administración"])
def desactivar_usuario(usuario_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin_user)):
    user = db.get(Usuario, usuario_id)
    if not user: raise HTTPException(404, "Usuario no encontrado")
    user.is_enabled = False
    db.commit()
    return {"success": True, "mensaje": "Usuario desactivado", "usuarioId": usuario_id}

@app.get("/openapi-check", tags=["Sistema"])
def openapi_check():
    return {"openapi": "/v3/api-docs", "swagger": "/doc", "redoc": "/redoc"}

# Import the Spring-equivalent administrative controllers before generic CRUD routers,
# so specific paths such as /opciones and /{id}/estado are matched correctly.
from app.routers.admin_extra import router as admin_extra_router
app.include_router(admin_extra_router)

from app.routers.categoria import router as categoria_router
from app.routers.comentario import router as comentario_router
from app.routers.subcategoria import router as subcategoria_router
from app.routers.producto import router as producto_router
from app.routers.detalle_venta import router as detalle_venta_router
from app.routers.rol import router as rol_router
from app.routers.factura_proveedor import router as factura_proveedor_router
from app.routers.usuario import router as usuario_router
from app.routers.detalle_factura import router as detalle_factura_router
from app.routers.empresa import router as empresa_router
from app.routers.compra import router as compra_router
from app.routers.historia import router as historia_router
from app.routers.peticion import router as peticion_router

for api_router in [categoria_router, comentario_router, subcategoria_router, producto_router,
                   detalle_venta_router, rol_router, factura_proveedor_router, usuario_router,
                   detalle_factura_router, empresa_router, compra_router, historia_router, peticion_router]:
    app.include_router(api_router)
