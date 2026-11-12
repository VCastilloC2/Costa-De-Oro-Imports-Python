"""Backward-compatible imports; new code should use app.api.deps."""
from app.api.deps import DB, admin_user, current_user, provider_user, require_roles, user_role

__all__ = ["DB", "admin_user", "current_user", "provider_user", "require_roles", "user_role"]