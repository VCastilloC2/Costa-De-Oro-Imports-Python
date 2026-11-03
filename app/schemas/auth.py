from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    correo: EmailStr = Field(validation_alias=AliasChoices("correo", "username"))
    password: str = Field(min_length=5, max_length=150)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    correo: EmailStr
    password: str = Field(min_length=5, max_length=150)
    tipo_identificacion: str = Field(validation_alias=AliasChoices("tipoIdentificacion", "tipo_identificacion"), pattern="^(CC|CE|DE|NIT|PP|TE|TI)$")
    numero_identificacion: str = Field(validation_alias=AliasChoices("numeroIdentificacion", "numero_identificacion"), min_length=3, max_length=25)
    nombres: str = Field(min_length=3, max_length=175)
    apellidos: str = Field(min_length=3, max_length=175)
    telefono: str = Field(min_length=5, max_length=25)
    direccion: str | None = None
    rol: str | None = Field(default="PERSONA_NATURAL", pattern="^(INVITADO|PERSONA_CONTACTO|PERSONA_JURIDICA|PERSONA_NATURAL|PROVEEDOR)$")


class OAuthLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id_token: str = Field(min_length=20)
    correo: EmailStr | None = None
    tipo_identificacion: str | None = Field(default=None, validation_alias=AliasChoices("tipoIdentificacion", "tipo_identificacion"), pattern="^(CC|CE|DE|NIT|PP|TE|TI)$")
    numero_identificacion: str | None = Field(default=None, validation_alias=AliasChoices("numeroIdentificacion", "numero_identificacion"), max_length=15)
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    password: str | None = Field(default=None, min_length=5, max_length=150)


class AdminCreateRequest(BaseModel):
    correo: EmailStr
    password: str = Field(min_length=5, max_length=150)
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
