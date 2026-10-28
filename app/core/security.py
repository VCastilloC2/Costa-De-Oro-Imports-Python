from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from app.core.config import settings

password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return bool(hashed) and password_hash.verify(password, hashed)
    except Exception:
        return False

def create_token(subject: str, role: str = "PERSONA_NATURAL") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "role": role, "iss": settings.jwt_issuer_ecommerce,
        "iat": now, "exp": now + timedelta(hours=1)}, settings.jwt_secret_ecommerce, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_ecommerce, algorithms=["HS256"], issuer=settings.jwt_issuer_ecommerce,
                      options={"require": ["sub", "exp", "iat", "iss"]})
