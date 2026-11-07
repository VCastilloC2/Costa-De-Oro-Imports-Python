"""Tablas de Passkeys (WebAuthn). Son tablas nuevas; no modifican ``usuario``.

Créalas con ``app/sql/passkeys.sql`` (la aplicación no ejecuta ``create_all`` en MySQL).
Los binarios WebAuthn (credential_id, clave pública, user handle) se guardan en base64url
para que sean portables entre MySQL, Valkey (JSON) y las pruebas en SQLite.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import PK_ID


class PasskeyCredencial(Base):
    """Credencial WebAuthn registrada por un usuario (persistencia principal)."""
    __tablename__ = "passkey_credencial"
    passkey_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.usuario_id"), nullable=False, index=True)
    credential_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    user_handle: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transports: Mapped[str | None] = mapped_column(String(255))
    aaguid: Mapped[str | None] = mapped_column(String(64))
    device_type: Mapped[str | None] = mapped_column(String(20))  # single_device | multi_device
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_name: Mapped[str | None] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ultimo_uso: Mapped[datetime | None] = mapped_column(DateTime)


class PasskeyChallenge(Base):
    """Respaldo de challenges cuando Valkey no está disponible (un solo uso, con expiración)."""
    __tablename__ = "passkey_challenge"
    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # registro | login
    datos_json: Mapped[str] = mapped_column(Text, nullable=False)
    expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_passkey_challenge_expira", "expira_en"),)
