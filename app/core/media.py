"""URLs públicas de imágenes (equivalente a ``CloudinaryService.getImagenUrl`` de Spring)."""
from __future__ import annotations

from urllib.parse import quote

from app.core.config import settings


def cloudinary_url(public_id: str | None) -> str | None:
    """URL https de una imagen de Cloudinary a partir de su ``public_id``.

    Igual que ``cloudinary.url().secure(true).generate(publicId)`` en Spring:
    * ``None``/vacío -> ``None``.
    * Si ya es una URL absoluta (http/https), se devuelve tal cual.
    * Sin ``CLOUD_NAME`` configurado se devuelve el valor original (no se puede construir la URL).
    """
    if not public_id or not public_id.strip():
        return None
    value = public_id.strip()
    if value.startswith(("http://", "https://")):
        return value
    if not settings.cloud_name:
        return value
    return f"https://res.cloudinary.com/{settings.cloud_name}/image/upload/{quote(value, safe='/._-~')}"
