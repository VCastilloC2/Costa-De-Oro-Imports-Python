"""Servicio de negocio para Peticion."""
from app.models import Peticion
from app.services.base_service import BaseService

class PeticionService(BaseService):
    def __init__(self):
        super().__init__(Peticion)

peticion_service = PeticionService()
