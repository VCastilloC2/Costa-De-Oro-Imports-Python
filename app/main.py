from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import engine, get_db
from app.core.security import hash_password, verify_password, create_token
from app.dependencies import current_user, admin_user
from app.models import Usuario, Rol, Producto, Categoria
from app.schemas import LoginRequest, RegisterRequest, UserResponse, ProductResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app=FastAPI(title=settings.app_name, version="1.0.0",
    description="API REST migrada desde Costa De Oro Imports. Contratos publicados en OpenAPI.",
    docs_url="/swagger-ui.html" if settings.springdoc_swagger_ui_enabled else None,
    openapi_url="/v3/api-docs" if settings.springdoc_api_docs_enabled else None,
    redoc_url="/redoc", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/health", tags=["Sistema"])
def health(): return {"status":"ok","application":settings.app_name}

@app.get("/health/db", tags=["Sistema"])
def health_db(db: Session=Depends(get_db)):
    try: db.execute(text("SELECT 1")); return {"status":"ok","database":"connected"}
    except Exception: raise HTTPException(503,"Base de datos no disponible")

@app.post("/auth/login", tags=["Autenticación"])
def login(payload: LoginRequest, db: Session=Depends(get_db)):
    user=db.scalar(select(Usuario).where(Usuario.correo==str(payload.username)))
    if not user or not verify_password(payload.password,user.password):
        raise HTTPException(401,"Credenciales inválidas")
    if user.is_enabled is False or user.account_non_locked is False:
        raise HTTPException(403,"Cuenta deshabilitada o bloqueada")
    role=db.get(Rol,user.rol_id) if user.rol_id else None
    token=create_token(str(user.usuario_id),role.rol if role else "PERSONA_NATURAL")
    return {"accessToken":token,"token_type":"bearer","expires_in":3600}

@app.post("/auth/registro", status_code=201, tags=["Autenticación"], response_model=UserResponse)
def register(payload: RegisterRequest, db: Session=Depends(get_db)):
    if db.scalar(select(Usuario).where(Usuario.correo==str(payload.correo))):
        raise HTTPException(400,detail={"mensaje":"El correo ya está registrado","success":False})
    user=Usuario(correo=str(payload.correo),password=hash_password(payload.password),
        nombres=payload.nombres,apellidos=payload.apellidos,telefono=payload.telefono,
        direccion=payload.direccion,tipo_identificacion=payload.tipo_identificacion,
        numero_identificacion=payload.numero_identificacion,is_enabled=True,
        account_non_expired=True,account_non_locked=True,credentials_non_expired=True)
    # Rol predeterminado: se obtiene por nombre; nunca se crea un rol implícito.
    role=db.scalar(select(Rol).where(Rol.rol=="PERSONA_NATURAL"))
    if role: user.rol_id=role.rol_id
    try: db.add(user); db.commit(); db.refresh(user)
    except Exception:
        db.rollback(); raise HTTPException(400,detail={"mensaje":"No fue posible registrar el usuario","success":False})
    return user

@app.post("/auth/logout", tags=["Autenticación"])
def logout(): return {"success":True,"mensaje":"Descarta el accessToken en el cliente"}

@app.get("/auth/catalogos", tags=["Autenticación"])
def catalogs():
    return {"tiposIdentificacion":["CC","CE","DE","NIT","PP","TE","TI"],
            "sectores":["BAR","CAFE","CATERING","HOTEL","NIGHTCLUB","RESTAURANT"]}

@app.get("/perfil", tags=["Perfil"], response_model=UserResponse)
def profile(user: Usuario=Depends(current_user)): return user

@app.get("/perfil/configuracion", tags=["Perfil"])
def profile_config(user: Usuario=Depends(current_user)):
    return {"usuarioId":user.usuario_id,"correo":user.correo,"tieneEmpresa":bool(user.empresa_id)}

@app.get("/api/productos", tags=["Catálogo"], response_model=list[ProductResponse])
def public_products(offset:int=Query(0,ge=0),limit:int=Query(24,ge=1,le=100),db:Session=Depends(get_db)):
    return list(db.scalars(select(Producto).where(Producto.activo.is_(True)).offset(offset).limit(limit)))

@app.get("/api/productos/{producto_id}", tags=["Catálogo"], response_model=ProductResponse)
def public_product(producto_id:int,db:Session=Depends(get_db)):
    item=db.get(Producto,producto_id)
    if not item or not item.activo: raise HTTPException(404,"Producto no encontrado")
    return item

@app.get("/admin/producto", tags=["Administración"], response_model=list[ProductResponse])
def admin_products(db:Session=Depends(get_db),_:Usuario=Depends(admin_user)):
    return list(db.scalars(select(Producto)))

@app.get("/admin/producto/{producto_id}", tags=["Administración"], response_model=ProductResponse)
def admin_product(producto_id:int,db:Session=Depends(get_db),_:Usuario=Depends(admin_user)):
    item=db.get(Producto,producto_id)
    if not item: raise HTTPException(404,"Producto no encontrado")
    return item

@app.get("/admin/categoria", tags=["Administración"])
def admin_categories(db:Session=Depends(get_db),_:Usuario=Depends(admin_user)):
    return [{"categoria_id":c.categoria_id,"nombre":c.nombre,"descripcion":c.descripcion,"activo":c.activo,"imagen":c.imagen}
            for c in db.scalars(select(Categoria))]

@app.get("/admin/categoria/{categoria_id}", tags=["Administración"])
def admin_category(categoria_id:int,db:Session=Depends(get_db),_:Usuario=Depends(admin_user)):
    c=db.get(Categoria,categoria_id)
    if not c: raise HTTPException(404,"Categoría no encontrada")
    return {"categoria_id":c.categoria_id,"nombre":c.nombre,"descripcion":c.descripcion,"activo":c.activo,"imagen":c.imagen}

@app.get("/openapi-check", tags=["Sistema"])
def openapi_check(): return {"openapi":"/v3/api-docs","swagger":"/swagger-ui.html","redoc":"/redoc"}
