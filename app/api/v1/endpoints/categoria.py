"""Endpoints administrativos de Categoria."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.categoria_service import categoria_service

router = build_crud_router("/admin/categoria", "Categoria", categoria_service)
