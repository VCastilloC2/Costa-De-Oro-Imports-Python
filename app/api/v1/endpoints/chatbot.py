"""Asistentes con Gemini.

* ``/admin/chatbot/*``: chatbot administrativo (sólo ADMIN) con un resumen agregado de MySQL.
* ``/api/asistente/*``: asistente de compras público, sólo con el catálogo activo.
"""
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import admin_user
from app.core import rate_limit
from app.core.config import settings
from app.core.database import get_db
from app.models import Usuario
from app.schemas.chat import (
    ChatbotStatus, ChatRequest, ChatResponse, ShopAssistantStatus, ShopChatRequest, ShopChatResponse,
)
from app.services import gemini_client
from app.services.chatbot_service import cached_business_context, generate_chat_response
from app.services.gemini_client import GeminiBlockedError, GeminiNotConfigured, GeminiProviderError
from app.services.shop_assistant_service import answer_shopper

router = APIRouter(tags=["Chatbot"])

ERRORS = {
    422: {"description": "Mensaje inválido o bloqueado por los filtros de seguridad"},
    429: {"description": "Demasiadas consultas; reintenta tras `Retry-After` segundos"},
    502: {"description": "Gemini devolvió un error o una respuesta vacía"},
    503: {"description": "Gemini no configurado, cuota agotada o base de datos no disponible"},
}


def _limit(key: str, limit: int, window: int, message: str) -> None:
    allowed, retry_after = rate_limit.hit(key, limit, window)
    if not allowed:
        raise HTTPException(429, message, headers={"Retry-After": str(retry_after)})


def _ask(action: Callable):
    """Traduce los errores de Gemini a respuestas HTTP con mensaje para el usuario."""
    try:
        return action()
    except GeminiNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except GeminiBlockedError as exc:
        raise HTTPException(422, str(exc)) from exc
    except GeminiProviderError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


# --------------------------------------------------------------------------- administración

@router.get("/admin/chatbot/status", response_model=ChatbotStatus, dependencies=[Depends(admin_user)],
            summary="Configuración y disponibilidad de los asistentes")
def chatbot_status():
    """No consume tokens: sólo informa la configuración (nunca devuelve la clave)."""
    return ChatbotStatus(
        configured=gemini_client.is_configured(), model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds, max_retries=settings.gemini_max_retries,
        context_cache_seconds=settings.chatbot_context_cache_seconds,
        admin_rate_limit_per_minute=settings.chatbot_rate_limit_per_minute,
        shop_assistant_enabled=settings.shop_assistant_enabled,
        shop_rate_limit_per_minute=settings.shop_assistant_rate_limit_per_minute,
        shop_daily_limit=settings.shop_assistant_daily_limit,
    )


@router.post("/admin/chatbot/chat", response_model=ChatResponse, response_model_exclude_none=True,
             responses=ERRORS, summary="Chat administrativo con datos agregados de MySQL")
def admin_chat(payload: ChatRequest, user: Annotated[Usuario, Depends(admin_user)],
               db: Session = Depends(get_db)):
    """Responde con un resumen agregado de inventario, ventas y catálogo (sin datos personales).
    El resumen se reutiliza `CHATBOT_CONTEXT_CACHE_SECONDS` segundos en Valkey. El cliente envía
    hasta 12 mensajes previos en `history`."""
    if not gemini_client.is_configured():
        raise HTTPException(503, "El chatbot no está configurado: falta GEMINI_API_KEY")
    _limit(f"chatbot:admin:{user.usuario_id}", settings.chatbot_rate_limit_per_minute, 60,
           "Demasiadas consultas al chatbot. Espera un minuto.")
    try:
        context, from_cache = cached_business_context(db)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "No se pudo consultar la información de MySQL") from exc
    result = _ask(lambda: generate_chat_response(payload.message, context, payload.history))
    return ChatResponse(answer=result.text, model=settings.gemini_model, context_cached=from_cache,
                        finish_reason=result.finish_reason, usage=result.usage or None)


# --------------------------------------------------------------------------- asistente de compras

def _shop_available() -> bool:
    return settings.shop_assistant_enabled and gemini_client.is_configured()


@router.get("/api/asistente/status", response_model=ShopAssistantStatus, response_model_exclude_none=True,
            tags=["Asistente de compras"], summary="¿Está disponible el asistente de compras?")
def shop_assistant_status():
    """Público. La app puede ocultar el botón del asistente si `available` es false."""
    available = _shop_available()
    return ShopAssistantStatus(available=available, model=settings.gemini_model if available else None)


@router.post("/api/asistente/chat", response_model=ShopChatResponse, responses=ERRORS,
             tags=["Asistente de compras"], summary="Asistente de compras con el catálogo")
def shop_assistant_chat(payload: ShopChatRequest, request: Request, db: Session = Depends(get_db)):
    """Público (no requiere sesión). Recomienda productos del catálogo activo; no ve ventas, pedidos,
    stock exacto ni datos de clientes. Devuelve en `productos` los artículos mencionados para que la
    app muestre tarjetas. Límite por IP y diario global para controlar el costo."""
    if not _shop_available():
        raise HTTPException(503, "El asistente de compras no está disponible")
    ip = request.client.host if request.client else "desconocida"
    _limit(f"chatbot:shop:ip:{ip}", settings.shop_assistant_rate_limit_per_minute, 60,
           "Demasiadas consultas. Espera un minuto.")
    _limit("chatbot:shop:global:day", settings.shop_assistant_daily_limit, 86400,
           "El asistente alcanzó su límite diario. Intenta mañana.")
    try:
        return _ask(lambda: answer_shopper(db, payload.message, payload.history))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "No se pudo consultar el catálogo") from exc
