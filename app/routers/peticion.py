"""Endpoints administrativos de Peticion."""
from app.routers.crud_factory import build_crud_router
from app.services.peticion_service import peticion_service

router = build_crud_router("/admin/peticion", "Peticion", peticion_service)
