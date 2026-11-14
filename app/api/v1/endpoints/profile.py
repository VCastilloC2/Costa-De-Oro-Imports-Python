"""Edición del perfil del usuario autenticado."""
from __future__ import annotations

import logging

import cloudinary
from cloudinary.uploader import upload as cloudinary_upload
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.cache import cache_auth_credentials, cache_auth_user, cache_delete, credential_cache_key
from app.core.config import settings
from app.core.database import get_db
from app.models import Rol, Usuario
from app.schemas import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/perfil", tags=["Perfil"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@router.patch("", response_model=UserResponse)
@router.put("", response_model=UserResponse, include_in_schema=False)
async def update_profile(
    nombres: str | None = Form(None),
    apellidos: str | None = Form(None),
    correo: str | None = Form(None),
    telefono: str | None = Form(None),
    direccion: str | None = Form(None),
    numero_identificacion: str | None = Form(None),
    tipo_identificacion: str | None = Form(None),
    imagen: UploadFile | None = File(None),
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
) -> Usuario:
    """Actualiza solo los campos enviados; el rol siempre queda intacto."""
    cambios = {
        "nombres": nombres,
        "apellidos": apellidos,
        "correo": correo,
        "telefono": telefono,
        "direccion": direccion,
        "numero_identificacion": numero_identificacion,
        "tipo_identificacion": tipo_identificacion,
    }
    cambios = {campo: valor.strip() for campo, valor in cambios.items()
               if valor is not None and valor.strip()}
    if "correo" in cambios:
        try:
            cambios["correo"] = str(TypeAdapter(EmailStr).validate_python(cambios["correo"]))
        except ValidationError as exc:
            raise HTTPException(422, "El correo no tiene un formato válido") from exc
    if cambios.get("tipo_identificacion") and cambios["tipo_identificacion"] not in {
        "CC", "CE", "DE", "NIT", "PP", "TE", "TI",
    }:
        raise HTTPException(422, "Tipo de identificación no válido")
    if imagen is not None and not imagen.filename:
        imagen = None
    if not cambios and imagen is None:
        raise HTTPException(400, "Envía al menos un campo para actualizar")

    imagen_public_id = None
    if imagen is not None and imagen.filename:
        if imagen.content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            raise HTTPException(415, "Formato de imagen no permitido")
        contenido = await imagen.read(MAX_IMAGE_BYTES + 1)
        if not contenido or len(contenido) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "La imagen debe pesar máximo 5 MB")
        if not (settings.cloud_name and settings.cloud_api_key and settings.cloud_api_secret):
            raise HTTPException(503, "Cloudinary no está configurado")
        try:
            cloudinary.config(cloud_name=settings.cloud_name, api_key=settings.cloud_api_key,
                              api_secret=settings.cloud_api_secret, secure=True)
            resultado = cloudinary_upload(contenido, folder="usuarios/perfiles",
                                          public_id=f"usuario_{user.usuario_id}",
                                          overwrite=True, resource_type="image")
            imagen_public_id = resultado.get("public_id")
            if not imagen_public_id:
                raise RuntimeError("Cloudinary no devolvió public_id")
        except Exception as exc:
            logger.exception("No fue posible subir la imagen del perfil")
            raise HTTPException(502, "No fue posible guardar la imagen en Cloudinary") from exc

    # current_user puede venir del snapshot de Valkey; recuperar la fila persistida
    # garantiza modificar MySQL y mantener intactos rol y atributos de seguridad.
    usuario_db = db.get(Usuario, user.usuario_id)
    if usuario_db is None:
        raise HTTPException(404, "Usuario no encontrado")
    correo_anterior = usuario_db.correo
    for campo, valor in cambios.items():
        setattr(usuario_db, campo, valor)
    if imagen_public_id:
        usuario_db.imagen = imagen_public_id
    try:
        db.commit()
        db.refresh(usuario_db)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El correo o teléfono ya está registrado") from exc

    rol = db.get(Rol, usuario_db.rol_id) if usuario_db.rol_id else None
    rol_nombre = str(rol.rol) if rol and rol.rol else ""
    # Refrescar el snapshot de usuario de Valkey; al cambiar correo también se
    # mueve la clave de credenciales sin alterar el hash BCrypt existente.
    if correo_anterior != usuario_db.correo:
        cache_delete(credential_cache_key(correo_anterior))
        cache_auth_credentials(usuario_db.correo, usuario_db.usuario_id, usuario_db.password)
    cache_auth_user(usuario_db, rol_nombre)
    return usuario_db
