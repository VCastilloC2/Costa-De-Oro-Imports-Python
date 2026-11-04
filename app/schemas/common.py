from typing import Any
from pydantic import BaseModel, ConfigDict, EmailStr

class UserResponse(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    usuario_id: int
    correo: EmailStr
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    imagen: str | None = None
    is_enabled: bool | None = None

class ProductResponse(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    producto_id: int
    codigo_producto: str | None = None
    imagen: str | None = None
    nombre: str | None = None
    marca: str | None = None
    pais: str | None = None
    tipo: str | None = None
    precio: float
    precio_regular: float | None = None
    stock: int
    descripcion: str | None = None
    activo: bool
    categoria_id: int | None = None
    subcategoria_id: int | None = None

# DTOs comunes para operaciones CRUD de los módulos administrativos.
# Los endpoints aceptan diccionarios para mantener compatibilidad con los nombres
# de columnas de la base de datos heredada. Estos DTOs sirven para validaciones
# reutilizables en endpoints específicos.
class CrudPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: dict[str, Any]

class MessageResponse(BaseModel):
    success: bool
    mensaje: str

class DeleteResponse(MessageResponse):
    id: int