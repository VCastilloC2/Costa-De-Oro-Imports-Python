"""Servicio de negocio para Empresa."""
from app.models import Empresa
from app.services.base_service import BaseService

class EmpresaService(BaseService):
    def __init__(self):
        super().__init__(Empresa)

empresa_service = EmpresaService()
