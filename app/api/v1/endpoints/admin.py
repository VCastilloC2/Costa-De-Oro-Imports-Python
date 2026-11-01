"""Administrative endpoints and compatibility CRUD routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import admin_user
from app.core.cache import cache_delete, cache_get_json, cache_set_json, user_cache_key
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Rol, Usuario
from app.prediction.data_handler import historical_dashboard_data
from app.prediction.engine import generate_forecast
from app.schemas import AdminCreateRequest, ForecastRequest
from app.api.v1.endpoints.admin_extra import router as legacy_admin_router
from app.api.v1.endpoints.categoria import router as categoria_router
from app.api.v1.endpoints.comentario import router as comentario_router
from app.api.v1.endpoints.subcategoria import router as subcategoria_router
from app.api.v1.endpoints.producto import router as producto_router
from app.api.v1.endpoints.detalle_venta import router as detalle_venta_router
from app.api.v1.endpoints.rol import router as rol_router
from app.api.v1.endpoints.factura_proveedor import router as factura_proveedor_router
from app.api.v1.endpoints.usuario import router as usuario_router
from app.api.v1.endpoints.detalle_factura import router as detalle_factura_router
from app.api.v1.endpoints.empresa import router as empresa_router
from app.api.v1.endpoints.compra import router as compra_router
from app.api.v1.endpoints.historia import router as historia_router
from app.api.v1.endpoints.peticion import router as peticion_router

router = APIRouter()


@router.get("/admin/usuario/pendientes", tags=["Administración"], dependencies=[Depends(admin_user)])
def pending_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(Usuario).where(Usuario.is_enabled.is_(False))))


router.include_router(legacy_admin_router)
for child in [
    categoria_router, comentario_router, subcategoria_router, producto_router,
    detalle_venta_router, rol_router, factura_proveedor_router, usuario_router,
    detalle_factura_router, empresa_router, compra_router, historia_router, peticion_router,
]:
    router.include_router(child)


@router.post("/admin/usuario/admin", status_code=201, tags=["Administración"])
def create_admin_user(
    payload: AdminCreateRequest,
    db: Session = Depends(get_db),
    _: Usuario = Depends(admin_user),
):
    email = str(payload.correo).lower().strip()
    if db.scalar(select(Usuario.usuario_id).where(Usuario.correo == email)):
        raise HTTPException(409, "El correo ya está registrado")
    if payload.telefono and db.scalar(select(Usuario.usuario_id).where(Usuario.telefono == payload.telefono)):
        raise HTTPException(409, "El teléfono ya está registrado")
    role = db.scalar(select(Rol).where(Rol.rol == "ADMIN"))
    if not role:
        raise HTTPException(409, "No existe el rol ADMIN en la base de datos")
    user = Usuario(
        correo=email, password=hash_password(payload.password), nombres=payload.nombres,
        apellidos=payload.apellidos, telefono=payload.telefono, rol_id=role.rol_id,
        is_enabled=True, account_non_expired=True, account_non_locked=True,
        credentials_non_expired=True,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(409, "No se pudo crear el administrador; revisa correo o teléfono duplicado") from exc
    return {"success": True, "mensaje": "Administrador creado", "usuarioId": user.usuario_id}


@router.get("/admin/prediccion", tags=["Predicción"], dependencies=[Depends(admin_user)])
def prediction_status():
    return {"disponible": True, "mensaje": "Motor de predicciones interno activo"}


@router.get("/admin/prediccion/datos-grafica", tags=["Predicción"], dependencies=[Depends(admin_user)])
def prediction_dashboard(db: Session = Depends(get_db)):
    cache_key = "dashboard:prediction:v1"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached
    try:
        result = historical_dashboard_data(db)
        if result["cantidad_compras"]:
            result["proyeccion_ventas"] = generate_forecast(db, years=6, forecast_months=12)["serie"]
        else:
            result["proyeccion_ventas"] = []
    except ValueError as exc:
        result = {
            "ventas_mensuales": [], "stock_vs_ventas": [], "ventas_por_ciudad": [],
            "total_ventas": 0.0, "cantidad_compras": 0, "proyeccion_ventas": [],
            "mensaje": str(exc),
        }
    cache_set_json(cache_key, result, settings.valkey_cache_ttl_seconds)
    return result


@router.post("/admin/prediccion/generar", tags=["Predicción"], dependencies=[Depends(admin_user)])
def generate_prediction(payload: ForecastRequest | None = None, db: Session = Depends(get_db)):
    request = payload or ForecastRequest()
    try:
        return generate_forecast(db, years=request.anios, forecast_months=request.proyeccion_meses)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# Cache is short-lived and cleared whenever a user is explicitly deactivated/reactivated here.
@router.patch("/admin/usuario/{usuario_id}/activar", tags=["Administración"], dependencies=[Depends(admin_user)])
def activate_user(usuario_id: int, db: Session = Depends(get_db)):
    user = db.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    user.is_enabled = True
    db.commit()
    cache_delete(user_cache_key(usuario_id))
    return {"success": True, "mensaje": "Usuario activado", "usuarioId": usuario_id}


@router.patch("/admin/usuario/{usuario_id}/desactivar", tags=["Administración"], dependencies=[Depends(admin_user)])
def deactivate_user(usuario_id: int, db: Session = Depends(get_db)):
    user = db.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    user.is_enabled = False
    db.commit()
    cache_delete(user_cache_key(usuario_id))
    return {"success": True, "mensaje": "Usuario desactivado", "usuarioId": usuario_id}
