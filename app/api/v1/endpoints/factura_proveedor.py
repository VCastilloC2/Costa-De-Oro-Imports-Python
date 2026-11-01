"""Endpoints administrativos de FacturaProveedor."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.factura_proveedor_service import factura_proveedor_service

router = build_crud_router("/admin/factura-proveedor", "FacturaProveedor", factura_proveedor_service)
