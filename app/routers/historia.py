"""Endpoints administrativos de Historia."""
from app.routers.crud_factory import build_crud_router
from app.services.historia_service import historia_service

router = build_crud_router("/admin/historia", "Historia", historia_service)
