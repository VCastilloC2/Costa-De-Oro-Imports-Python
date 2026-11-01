"""Endpoints administrativos de Producto."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.producto_service import producto_service

router = build_crud_router("/admin/producto", "Producto", producto_service)
