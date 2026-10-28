"""Servicios CRUD reutilizables sobre SQLAlchemy. La lógica de negocio específica vive en cada servicio.""" 
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import Type

class BaseService:
    def __init__(self, model: Type):
        self.model = model
        self.pk = next(c for c in model.__table__.columns if c.primary_key)

    def serialize(self, item):
        hidden = {"password", "remember_me_token", "token"}
        return {column.name: getattr(item, column.name) for column in self.model.__table__.columns
                if column.name not in hidden}

    def list(self, db: Session, offset: int = 0, limit: int = 50):
        return [self.serialize(item) for item in db.scalars(select(self.model).offset(offset).limit(limit))]

    def get_item(self, db: Session, item_id: int):
        item = db.get(self.model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{self.model.__name__} no encontrado")
        return item

    def get(self, db: Session, item_id: int):
        return self.serialize(self.get_item(db, item_id))

    def create(self, db: Session, data: dict):
        allowed = {c.name for c in self.model.__table__.columns if not c.primary_key and not c.computed}
        payload = {k: v for k, v in data.items() if k in allowed}
        # Las contraseñas nunca se almacenan en texto plano, incluso desde el CRUD de administración.
        if self.model.__name__ == "Usuario" and payload.get("password"):
            from app.core.security import hash_password
            payload["password"] = hash_password(payload["password"])
        item = self.model(**payload)
        db.add(item)
        try:
            db.commit()
            db.refresh(item)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="No se pudo crear el registro; revisa campos obligatorios, duplicados y claves foráneas") from exc
        return self.serialize(item)

    def update(self, db: Session, item_id: int, data: dict):
        item = self.get_item(db, item_id)
        allowed = {c.name for c in self.model.__table__.columns if not c.primary_key and not c.computed}
        for key, value in data.items():
            if key in allowed:
                if self.model.__name__ == "Usuario" and key == "password" and value:
                    from app.core.security import hash_password
                    value = hash_password(value)
                setattr(item, key, value)
        try:
            db.commit()
            db.refresh(item)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="No se pudo actualizar el registro; revisa restricciones de la base de datos") from exc
        return self.serialize(item)

    def delete(self, db: Session, item_id: int):
        item = self.get_item(db, item_id)
        try:
            db.delete(item)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="No se pudo eliminar: el registro puede estar relacionado con otros datos") from exc
        return {"success": True, "mensaje": "Registro eliminado", "id": item_id}
