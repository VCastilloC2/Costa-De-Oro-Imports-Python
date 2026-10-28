"""Endpoints administrativos de DetalleVenta."""
from app.routers.crud_factory import build_crud_router
from app.services.detalle_venta_service import detalle_venta_service

router = build_crud_router("/admin/detalle-venta", "DetalleVenta", detalle_venta_service)
