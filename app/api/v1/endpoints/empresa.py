"""Endpoints administrativos de Empresa."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.empresa_service import empresa_service

router = build_crud_router("/admin/empresa", "Empresa", empresa_service)
