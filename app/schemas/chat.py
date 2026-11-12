from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "message": "¿Qué productos tienen menos stock?",
        "history": [{"role": "user", "content": "Hablemos de inventario."},
                    {"role": "model", "content": "Claro, ¿qué quieres saber?"}]}})
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class ChatUsage(BaseModel):
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    answer: str
    model: str
    source: Literal["database"] = "database"
    context_cached: bool | None = Field(None, description="true si el resumen de MySQL vino de la caché")
    finish_reason: str | None = Field(None, description="STOP o MAX_TOKENS (respuesta truncada)")
    usage: ChatUsage | None = None


class ShopChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=1000)


class ShopChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "message": "¿Qué whisky escocés me recomiendas para regalar?", "history": []}})
    message: str = Field(min_length=1, max_length=500)
    history: list[ShopChatTurn] = Field(default_factory=list, max_length=8)


class ProductSuggestion(BaseModel):
    producto_id: int
    nombre: str
    precio: float
    precio_antes: float | None = None
    disponibilidad: Literal["disponible", "pocas_unidades", "agotado"]
    imagen: str | None = None


class ShopChatResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "answer": "Te recomiendo Whisky A (COP 40.000), está disponible.",
        "model": "gemini-3.8-flash", "source": "catalog",
        "productos": [{"producto_id": 1, "nombre": "Whisky A", "precio": 40000, "precio_antes": None,
                       "disponibilidad": "disponible", "imagen": None}],
        "finish_reason": "STOP", "usage": {"prompt_tokens": 900, "output_tokens": 60, "total_tokens": 960}}})
    answer: str
    model: str
    source: Literal["catalog"] = "catalog"
    productos: list[ProductSuggestion] = Field(
        default_factory=list, description="Productos del catálogo mencionados en la respuesta (para tarjetas)")
    finish_reason: str | None = None
    usage: ChatUsage | None = None


class ChatbotStatus(BaseModel):
    configured: bool = Field(description="true si GEMINI_API_KEY está configurada")
    model: str
    timeout_seconds: float
    max_retries: int
    context_cache_seconds: int
    admin_rate_limit_per_minute: int
    shop_assistant_enabled: bool
    shop_rate_limit_per_minute: int
    shop_daily_limit: int


class ShopAssistantStatus(BaseModel):
    available: bool
    model: str | None = None
