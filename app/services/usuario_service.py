"""Servicio de negocio para Usuario."""
from app.models import Usuario
from app.services.base_service import BaseService

class UsuarioService(BaseService):
    def __init__(self):
        super().__init__(Usuario)

usuario_service = UsuarioService()
