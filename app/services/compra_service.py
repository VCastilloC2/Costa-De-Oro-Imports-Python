"""Servicio de negocio para Compra."""
from app.models import Compra
from app.services.base_service import BaseService

class CompraService(BaseService):
    def __init__(self):
        super().__init__(Compra)

compra_service = CompraService()
