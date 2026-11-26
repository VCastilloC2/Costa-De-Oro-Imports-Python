from contextlib import asynccontextmanager
import asyncio
import logging
import re

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import current_user, user_role
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.chatbot import router as chatbot_router
from app.api.v1.endpoints.passkey import router as passkey_router
from app.api.v1.endpoints.location import router as location_router
from app.api.v1.endpoints.profile import router as profile_router
from app.api.v1.endpoints.predictions import install_prediction_error_handlers, router as predictions_router
from app.api.v1.endpoints.spring_integration import router as spring_integration_router
from app.api.v1.endpoints.dashboard_integration import router as dashboard_integration_router
from app.core.config import settings
from app.core.cache import cache_health
from app.core.database import SessionLocal, get_db
from app.models import Producto, Usuario
from app.schemas import ProductResponse, UserResponse

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.prediction_data_source.strip().lower() in {"db", "database", "mysql", "postgresql"}:
        # Deja el modelo y la respuesta de la pantalla listos antes de aceptar
        # peticiones. Las consultas de Flutter no deben entrenar ni inferir.
        await asyncio.to_thread(_prepare_monthly_prediction_snapshot)
    yield


def _prepare_monthly_prediction_snapshot() -> None:
    """Ensure a current model and save the ready-to-serve dashboard response."""
    from app.prediction.training_service import training_service
    from app.prediction.artifacts import model_store
    from app.prediction.data_handler import historical_dashboard_data
    from app.prediction.engine import evaluate_recent_months, generate_forecast
    from app.prediction import repository

    with SessionLocal() as db:
        training = training_service.ensure_monthly_model_current(db)
        historical = historical_dashboard_data(db)
        forecast = generate_forecast(db, years=6, forecast_months=12)
        # Guarda únicamente los campos usados por la pantalla Flutter: la
        # respuesta cabe en resumen_json y evita adjuntar inventarios completos.
        snapshot = {
            "total_ventas": historical["total_ventas"],
            "cantidad_compras": historical["cantidad_compras"],
            "proyeccion_ventas": forecast["serie"],
        }
        snapshot["historial_datos"] = forecast["historial_datos"]
        snapshot["advertencia_modelo"] = forecast.get("advertencia_modelo")
        snapshot["variables_prediccion"] = forecast.get("variables_prediccion", [])
        snapshot["metricas"] = forecast.get("metricas", {})
        try:
            snapshot["evaluacion"] = evaluate_recent_months(db, months=5)
        except ValueError as exc:
            # La gráfica y el modelo siguen disponibles si aún no hay meses
            # cerrados suficientes para el backtest secundario.
            snapshot["evaluacion"] = {"error": str(exc), "comparacion": [], "metricas": {}}
        version = model_store.active_version("monthly")
        if version is None:
            raise RuntimeError("No quedó un modelo mensual activo después del entrenamiento")
        repository.save_dashboard_snapshot(db, "monthly", version, snapshot)
    logger.info("Modelo mensual y resumen guardados en BD: %s (v%s)", training, version)

app = FastAPI(
    title="Costa De Oro Imports",
    version="4.0.0",
    description=(
        "API REST de Costa De Oro Imports. Operaciones administrativas protegidas por rol ADMIN.\n\n"
        "**Servicio de predicciones (TensorFlow):** `/api/v1/predictions/*`. Consumible desde cualquier "
        "cliente HTTP/JSON (Flutter, Spring Boot, Node.js, Python...) con `Authorization: Bearer <JWT>` "
        "o `X-API-Key`. Guía de integración: `docs/API_PREDICCIONES.md`."
    ),
    openapi_tags=[{
        "name": "Predicción",
        "description": (
            "Módulo unificado de predicción de ventas: pronóstico mensual, inferencia, "
            "entrenamiento TensorFlow, métricas, historial y endpoints de integración. "
            "Los endpoints conservan funciones y permisos distintos, pero se documentan juntos."
        ),
    }],
    docs_url="/doc" if settings.springdoc_swagger_ui_enabled else None,
    openapi_url="/v3/api-docs" if settings.springdoc_api_docs_enabled else None,
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/doc", status_code=307)



@app.get(
    "/.well-known/assetlinks.json",
    include_in_schema=True,
    tags=["Passkeys"]
)
def android_assetlinks():
    """Publica la asociación Android necesaria para Passkeys."""

    rp_id = settings.passkey_rp_id.strip().lower()
    package_name = settings.passkey_android_package_name.strip()

    fingerprints = [
        value.strip().upper()
        for value in settings.passkey_android_sha256_fingerprints.split(",")
        if re.fullmatch(
            r"(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}",
            value.strip()
        )
    ]

    if not rp_id or not package_name or not fingerprints:
        raise HTTPException(
            status_code=503,
            detail="Asociación Android de Passkeys no configurada"
        )

    return JSONResponse(
        content=[
            {
                # get_login_creds permite compartir credenciales; handle_all_urls
                # también es necesario para que Android verifique el RP al crear passkeys.
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                    "delegate_permission/common.get_login_creds",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": package_name,
                    "sha256_cert_fingerprints": fingerprints,
                },
            },
        ],
        # Esta respuesta depende de variables de entorno; evita que Swagger/navegadores
        # mantengan la versión anterior tras cambiar las huellas o relaciones.
        headers={"Cache-Control": "no-store"},
    )


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
    return {
        "usuarioId": user.usuario_id,
        "correo": user.correo,
        "rol": user_role(user, db),
        "tieneEmpresa": bool(user.empresa_id),
        "nombres": user.nombres,
        "apellidos": user.apellidos,
        "telefono": user.telefono,
        "imagen": user.imagen,
        "direccion": user.direccion,
        "tipo_identificacion": user.tipo_identificacion,
        "numero_identificacion": user.numero_identificacion,
        "account_non_expired": user.account_non_expired,
        "account_non_locked": user.account_non_locked,
        "credentials_non_expired": user.credentials_non_expired,
        "is_enabled": user.is_enabled,
    }


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
app.include_router(passkey_router)
app.include_router(location_router)
app.include_router(profile_router)
app.include_router(admin_router)
app.include_router(chatbot_router)
app.include_router(predictions_router)
app.include_router(spring_integration_router)
app.include_router(dashboard_integration_router)
install_prediction_error_handlers(app)
