"""Endpoints administrativos de Usuario."""
from app.routers.crud_factory import build_crud_router
from app.services.usuario_service import usuario_service

router = build_crud_router("/admin/usuario", "Usuario", usuario_service)
