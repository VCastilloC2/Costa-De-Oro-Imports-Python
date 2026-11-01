"""Endpoints administrativos de Peticion."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.peticion_service import peticion_service

router = build_crud_router("/admin/peticion", "Peticion", peticion_service)
