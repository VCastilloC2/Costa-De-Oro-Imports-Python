"""Costa De Oro Imports FastAPI application."""
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import current_user, user_role
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.chatbot import router as chatbot_router
from app.api.v1.endpoints.predictions import router as predictions_router
from app.core.config import settings
from app.core.cache import cache_health
from app.core.database import get_db
from app.models import Producto, Usuario
from app.schemas import ProductResponse, UserResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version="4.0.0",
    description="API REST de Costa De Oro Imports. Operaciones administrativas protegidas por rol ADMIN.",
    docs_url="/doc" if settings.springdoc_swagger_ui_enabled else None,
    openapi_url="/v3/api-docs" if settings.springdoc_api_docs_enabled else None,
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


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


@app.get("/health/cache", tags=["Sistema"])
def health_cache():
    status = cache_health()
    if status["status"] != "ok":
        raise HTTPException(503, detail=status)
    return status


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
    if not item or not item.activo:
        raise HTTPException(404, "Producto no encontrado")
    return item


@app.get("/openapi-check", tags=["Sistema"])
def openapi_check():
    return {"openapi": "/v3/api-docs", "swagger": "/doc", "redoc": "/redoc"}


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(chatbot_router)
app.include_router(predictions_router)
