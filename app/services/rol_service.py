"""Servicio de negocio para Rol."""
from app.models import Rol
from app.services.base_service import BaseService

class RolService(BaseService):
    def __init__(self):
        super().__init__(Rol)

rol_service = RolService()
