"""Servicio de negocio para SubCategoria."""
from app.models import SubCategoria
from app.services.base_service import BaseService

class SubCategoriaService(BaseService):
    def __init__(self):
        super().__init__(SubCategoria)

subcategoria_service = SubCategoriaService()
