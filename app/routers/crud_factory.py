"""Factoría de endpoints CRUD; las rutas administrativas requieren rol ADMIN."""
from fastapi import APIRouter, Depends, Body, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies import admin_user
from app.services.base_service import BaseService

def build_crud_router(prefix: str, tag: str, service: BaseService, *, admin_only: bool = True):
    router = APIRouter(prefix=prefix, tags=[tag])
    dependencies = [Depends(admin_user)] if admin_only else []
    router.dependencies.extend(dependencies)

    @router.get("")
    def list_items(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
        return service.list(db, offset, limit)

    @router.get("/{item_id}")
    def get_item(item_id: int, db: Session = Depends(get_db)):
        return service.get(db, item_id)

    @router.post("", status_code=201)
    def create_item(payload: dict = Body(...), db: Session = Depends(get_db)):
        return service.create(db, payload)

    @router.patch("/{item_id}")
    def update_item(item_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
        return service.update(db, item_id, payload)

    @router.delete("/{item_id}")
    def delete_item(item_id: int, db: Session = Depends(get_db)):
        return service.delete(db, item_id)

    return router
