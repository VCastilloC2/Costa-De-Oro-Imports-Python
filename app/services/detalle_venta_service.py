"""Servicio de negocio para DetalleVenta."""
from app.models import DetalleVenta
from app.services.base_service import BaseService

class DetalleVentaService(BaseService):
    def __init__(self):
        super().__init__(DetalleVenta)

detalle_venta_service = DetalleVentaService()
