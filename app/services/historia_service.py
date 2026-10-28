"""Servicio de negocio para Historia."""
from app.models import Historia
from app.services.base_service import BaseService

class HistoriaService(BaseService):
    def __init__(self):
        super().__init__(Historia)

historia_service = HistoriaService()
