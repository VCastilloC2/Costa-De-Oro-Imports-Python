"""Almacenamiento de Passkeys con estrategia Valkey -> MySQL (cache-aside + write-through).

* Credenciales: MySQL es la fuente de verdad. Al registrar se escribe en MySQL y se carga en
  Valkey de inmediato. Al leer se consulta Valkey; si no está (cache miss) se lee MySQL y se
  re-puebla Valkey con ``PASSKEY_CACHE_TTL_SECONDS``. El ``sign_count`` se actualiza en ambas.
* Challenges: viven en Valkey con TTL (``PASSKEY_CHALLENGE_TTL_SECONDS``) y se consumen con GETDEL
  (un solo uso, anti-replay). Si Valkey no responde se usa la tabla ``passkey_challenge`` como
  respaldo transparente, también de un solo uso y con expiración.

Claves en Valkey::

    passkey:challenge:<challenge_id>  -> {"tipo", "challenge", "usuario_id", ...}
    passkey:cred:<credential_id>      -> registro de la credencial (sin datos secretos)
    passkey:user:<usuario_id>         -> {"user_handle", "credentials": [{"credential_id", "transports"}]}
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import cache
from app.core.config import settings
from app.models import PasskeyChallenge, PasskeyCredencial

logger = logging.getLogger(__name__)


class DuplicateCredentialError(Exception):
    pass


class SignCountConflictError(Exception):
    """El contador cambió entre la lectura y la escritura (uso concurrente o clonado)."""


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def challenge_key(challenge_id: str) -> str:
    return f"passkey:challenge:{challenge_id}"


def credential_key(credential_id: str) -> str:
    return f"passkey:cred:{credential_id}"


def user_key(usuario_id: int) -> str:
    return f"passkey:user:{usuario_id}"


def serialize_credential(row: PasskeyCredencial) -> dict[str, Any]:
    return {
        "passkey_id": int(row.passkey_id),
        "usuario_id": int(row.usuario_id),
        "credential_id": row.credential_id,
        "public_key": row.public_key,
        "user_handle": row.user_handle,
        "sign_count": int(row.sign_count or 0),
        "transports": json.loads(row.transports) if row.transports else [],
        "aaguid": row.aaguid,
        "device_type": row.device_type,
        "backed_up": bool(row.backed_up),
        "device_name": row.device_name,
        "activo": bool(row.activo),
        "created_at": row.fecha_creacion.isoformat() if row.fecha_creacion else None,
        "last_used_at": row.ultimo_uso.isoformat() if row.ultimo_uso else None,
    }


class PasskeyStore:
    # ------------------------------------------------------------------ challenges
    def save_challenge(self, db: Session, kind: str, data: dict[str, Any]) -> tuple[str, int]:
        ttl = settings.passkey_challenge_ttl_seconds
        challenge_id = secrets.token_hex(16)
        record = {**data, "tipo": kind}
        if cache.cache_set_json(challenge_key(challenge_id), record, ttl):
            return challenge_id, ttl
        logger.warning("Valkey no disponible: el challenge de passkey se guarda en MySQL")
        try:
            db.execute(delete(PasskeyChallenge).where(PasskeyChallenge.expira_en < _now()))
            db.add(PasskeyChallenge(challenge_id=challenge_id, tipo=kind, datos_json=json.dumps(record),
                                    expira_en=_now() + timedelta(seconds=ttl)))
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise RuntimeError("No hay almacenamiento disponible para el challenge de passkey") from exc
        return challenge_id, ttl

    def consume_challenge(self, db: Session, challenge_id: str, kind: str) -> dict[str, Any] | None:
        """Devuelve el challenge y lo invalida (un solo uso). None si no existe, expiró o no coincide."""
        _, record = cache.cache_pop_json(challenge_key(challenge_id))
        if record is None:
            record = self._consume_challenge_db(db, challenge_id)
        if not isinstance(record, dict) or record.get("tipo") != kind:
            return None
        return record

    @staticmethod
    def _consume_challenge_db(db: Session, challenge_id: str) -> dict[str, Any] | None:
        try:
            row = db.get(PasskeyChallenge, challenge_id)
            if row is None:
                return None
            data, expires = row.datos_json, row.expira_en
            # El DELETE con rowcount garantiza que sólo una petición consume el challenge.
            deleted = db.execute(delete(PasskeyChallenge).where(PasskeyChallenge.challenge_id == challenge_id))
            db.commit()
            if deleted.rowcount != 1 or expires < _now():
                return None
            return json.loads(data)
        except SQLAlchemyError:
            db.rollback()
            logger.warning("No se pudo consultar el respaldo de challenges en MySQL", exc_info=True)
            return None

    # ------------------------------------------------------------------ credenciales
    def _cache_credential(self, record: dict[str, Any]) -> None:
        cache.cache_set_json(credential_key(record["credential_id"]), record, settings.passkey_cache_ttl_seconds)

    def get_credential(self, db: Session, credential_id: str) -> dict[str, Any] | None:
        """Valkey primero; en cache miss consulta MySQL y re-puebla Valkey."""
        cached = cache.cache_get_json(credential_key(credential_id))
        if isinstance(cached, dict) and cached.get("credential_id") == credential_id:
            return cached if cached.get("activo", True) else None
        row = db.scalar(select(PasskeyCredencial).where(PasskeyCredencial.credential_id == credential_id))
        if row is None or not row.activo:
            return None
        record = serialize_credential(row)
        self._cache_credential(record)
        return record

    def get_user_credentials(self, db: Session, usuario_id: int) -> dict[str, Any]:
        """``{"user_handle": str | None, "credentials": [...]}`` (Valkey -> MySQL)."""
        cached = cache.cache_get_json(user_key(usuario_id))
        if isinstance(cached, dict) and "credentials" in cached:
            return cached
        rows = list(db.scalars(select(PasskeyCredencial).where(
            PasskeyCredencial.usuario_id == usuario_id, PasskeyCredencial.activo.is_(True))))
        info = {
            "user_handle": rows[0].user_handle if rows else None,
            "credentials": [{"credential_id": r.credential_id,
                             "transports": json.loads(r.transports) if r.transports else []} for r in rows],
        }
        cache.cache_set_json(user_key(usuario_id), info, settings.passkey_cache_ttl_seconds)
        return info

    def save_credential(self, db: Session, **fields) -> dict[str, Any]:
        """Persiste en MySQL y sincroniza Valkey inmediatamente."""
        row = PasskeyCredencial(**fields, activo=True, fecha_creacion=_now())
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
        except IntegrityError as exc:
            db.rollback()
            raise DuplicateCredentialError("La passkey ya está registrada") from exc
        record = serialize_credential(row)
        self._cache_credential(record)
        cache.cache_delete(user_key(record["usuario_id"]))
        self.get_user_credentials(db, record["usuario_id"])  # re-puebla la lista del usuario
        return record

    def record_usage(self, db: Session, record: dict[str, Any], new_sign_count: int) -> dict[str, Any]:
        """Actualiza sign_count y último uso en MySQL (con control optimista) y en Valkey."""
        used_at = _now()
        result = db.execute(
            update(PasskeyCredencial)
            .where(PasskeyCredencial.passkey_id == record["passkey_id"],
                   PasskeyCredencial.sign_count == record["sign_count"],
                   PasskeyCredencial.activo.is_(True))
            .values(sign_count=new_sign_count, ultimo_uso=used_at)
        )
        db.commit()
        if result.rowcount != 1:
            # Valkey podía tener un contador viejo o hubo uso concurrente: invalida y que se reintente.
            cache.cache_delete(credential_key(record["credential_id"]))
            raise SignCountConflictError("El contador de la passkey cambió durante la verificación")
        updated = {**record, "sign_count": int(new_sign_count), "last_used_at": used_at.isoformat()}
        self._cache_credential(updated)
        return updated

    def revoke_user_credential(self, db: Session, usuario_id: int, passkey_id: int) -> bool:
        row = db.get(PasskeyCredencial, passkey_id)
        if row is None or int(row.usuario_id) != int(usuario_id) or not row.activo:
            return False
        row.activo = False
        db.commit()
        cache.cache_delete(credential_key(row.credential_id))
        cache.cache_delete(user_key(usuario_id))
        return True

    def list_user_credentials(self, db: Session, usuario_id: int) -> list[dict[str, Any]]:
        rows = db.scalars(select(PasskeyCredencial).where(
            PasskeyCredencial.usuario_id == usuario_id, PasskeyCredencial.activo.is_(True))
            .order_by(PasskeyCredencial.passkey_id))
        return [serialize_credential(r) for r in rows]


passkey_store = PasskeyStore()
