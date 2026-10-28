"""Servicio de negocio para Comentario."""
from app.models import Comentario
from app.services.base_service import BaseService

class ComentarioService(BaseService):
    def __init__(self):
        super().__init__(Comentario)

comentario_service = ComentarioService()
