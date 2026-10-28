from pydantic import BaseModel, ConfigDict, EmailStr, Field
class LoginRequest(BaseModel):
    username: EmailStr
    password: str = Field(min_length=1, max_length=128)
class RegisterRequest(BaseModel):
    correo: EmailStr
    password: str = Field(min_length=10, max_length=128)
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    tipo_identificacion: str | None = None
    numero_identificacion: str | None = None
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
