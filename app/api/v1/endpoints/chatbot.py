"""Admin-only chatbot grounded in a read-only snapshot of MySQL."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import admin_user
from app.core.config import settings
from app.core.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chatbot_service import (
    ChatbotNotConfigured,
    ChatbotProviderError,
    build_business_context,
    generate_chat_response,
)

router = APIRouter(tags=["Chatbot"])


@router.post(
    "/admin/chatbot/chat",
    response_model=ChatResponse,
    dependencies=[Depends(admin_user)],
)
def admin_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    if not settings.gemini_api_key or not settings.gemini_api_key.strip():
        raise HTTPException(503, "El chatbot no está configurado: falta GEMINI_API_KEY")
    try:
        context = build_business_context(db)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "No se pudo consultar la información de MySQL") from exc
    try:
        answer = generate_chat_response(payload.message, context, payload.history)
    except ChatbotNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ChatbotProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return ChatResponse(answer=answer, model=settings.gemini_model)
