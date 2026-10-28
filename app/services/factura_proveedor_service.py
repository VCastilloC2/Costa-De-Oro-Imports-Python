"""Servicio de negocio para FacturaProveedor."""
from app.models import FacturaProveedor
from app.services.base_service import BaseService

class FacturaProveedorService(BaseService):
    def __init__(self):
        super().__init__(FacturaProveedor)

factura_proveedor_service = FacturaProveedorService()
