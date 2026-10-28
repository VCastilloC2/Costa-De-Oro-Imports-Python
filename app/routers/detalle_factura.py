"""Endpoints administrativos de DetalleFactura."""
from app.routers.crud_factory import build_crud_router
from app.services.detalle_factura_service import detalle_factura_service

router = build_crud_router("/admin/detalle-factura", "DetalleFactura", detalle_factura_service)
