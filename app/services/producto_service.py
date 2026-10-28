"""Servicio de negocio para Producto."""
from app.models import Producto
from app.services.base_service import BaseService

class ProductoService(BaseService):
    def __init__(self):
        super().__init__(Producto)

producto_service = ProductoService()
