"""Endpoints administrativos de Compra."""
from app.routers.crud_factory import build_crud_router
from app.services.compra_service import compra_service

router = build_crud_router("/admin/compra", "Compra", compra_service)
