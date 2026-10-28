from datetime import datetime, timedelta, timezone
import jwt
import bcrypt
from pwdlib import PasswordHash
from app.core.config import settings

legacy_password_hash = PasswordHash.recommended()

def _bcrypt_password(password: str) -> bytes:
    # Spring BCryptPasswordEncoder also operates on UTF-8 bytes; BCrypt uses
    # at most the first 72 bytes of a password.
    return password.encode("utf-8")[:72]

def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_password(password), bcrypt.gensalt(rounds=10, prefix=b"2a")).decode("ascii")

def verify_password(password: str, hashed: str | None) -> bool:
    try:
        if not hashed:
            return False
        if hashed.startswith(("$2a$", "$2b$", "$2y$")):
            return bcrypt.checkpw(_bcrypt_password(password), hashed.encode("ascii"))
        # Accept Argon2 hashes from earlier FastAPI versions during migration.
        if hashed.startswith("$argon2"):
            return legacy_password_hash.verify(password, hashed)
        return False
    except Exception:
        return False

def is_bcrypt_hash(hashed: str | None) -> bool:
    return bool(hashed and hashed.startswith(("$2a$", "$2b$", "$2y$")))

def create_token(subject: str, role: str = "PERSONA_NATURAL") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "role": role, "iss": settings.jwt_issuer_ecommerce,
        "iat": now, "exp": now + timedelta(hours=1)}, settings.jwt_secret_ecommerce, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_ecommerce, algorithms=["HS256"], issuer=settings.jwt_issuer_ecommerce,
                      options={"require": ["sub", "exp", "iat", "iss"]})
