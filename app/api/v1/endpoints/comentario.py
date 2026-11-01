"""Endpoints administrativos de Comentario."""
from app.api.v1.endpoints.crud_factory import build_crud_router
from app.services.comentario_service import comentario_service

router = build_crud_router("/admin/comentario", "Comentario", comentario_service)
