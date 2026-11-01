"""Endpoints administrativos de Rol."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.rol_service import rol_service

router = build_crud_router("/admin/rol", "Rol", rol_service)
