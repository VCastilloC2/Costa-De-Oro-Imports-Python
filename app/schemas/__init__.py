"""Pydantic request and response schemas."""
from .common import CrudPayload, DeleteResponse, MessageResponse, ProductResponse, UserResponse
from .auth import AdminCreateRequest, LoginRequest, OAuthLoginRequest, RegisterRequest
from .prediction import ForecastRequest

__all__ = [
    "AdminCreateRequest", "CrudPayload", "DeleteResponse", "ForecastRequest", "LoginRequest",
    "MessageResponse", "OAuthLoginRequest", "ProductResponse", "RegisterRequest", "UserResponse",
]
