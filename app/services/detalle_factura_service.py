"""Servicio de negocio para DetalleFactura."""
from app.models import DetalleFactura
from app.services.base_service import BaseService

class DetalleFacturaService(BaseService):
    def __init__(self):
        super().__init__(DetalleFactura)

detalle_factura_service = DetalleFacturaService()
