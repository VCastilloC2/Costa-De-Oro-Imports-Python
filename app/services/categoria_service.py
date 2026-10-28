"""Servicio de negocio para Categoria."""
from app.models import Categoria
from app.services.base_service import BaseService

class CategoriaService(BaseService):
    def __init__(self):
        super().__init__(Categoria)

categoria_service = CategoriaService()
