"""Endpoints administrativos de SubCategoria."""
from app.routers.crud_factory import build_crud_router
from app.services.subcategoria_service import subcategoria_service

router = build_crud_router("/admin/subcategoria", "SubCategoria", subcategoria_service)
