"""Pydantic request and response schemas."""
from .common import CrudPayload, DeleteResponse, MessageResponse, ProductResponse, UserResponse
from .auth import AdminCreateRequest, LoginRequest, OAuthLoginRequest, RegisterRequest
from .prediction import ForecastRequest
from .chat import ChatRequest, ChatResponse, ChatTurn

__all__ = [
    "AdminCreateRequest", "CrudPayload", "DeleteResponse", "ForecastRequest", "LoginRequest",
    "MessageResponse", "OAuthLoginRequest", "ProductResponse", "RegisterRequest", "UserResponse",
    "ChatRequest", "ChatResponse", "ChatTurn",
]