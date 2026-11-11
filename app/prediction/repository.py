"""Persistencia del servicio ML: registro de modelos, historial, evaluaciones, API Keys y accesos."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    PrediccionAcceso, PrediccionApiCliente, PrediccionEvaluacion, PrediccionHistorial, PrediccionModelo,
)

logger = logging.getLogger(__name__)
API_KEY_PREFIX = "cdo_pk_"
SCOPE_READ = "predictions:read"
SCOPE_GENERATE = "predictions:generate"
# Acceso de servicio (Spring Boot) a las rutas de administración. admin:write implica admin:read.
SCOPE_ADMIN_READ = "admin:read"
SCOPE_ADMIN_WRITE = "admin:write"
VALID_SCOPES = {SCOPE_READ, SCOPE_GENERATE, SCOPE_ADMIN_READ, SCOPE_ADMIN_WRITE}
MISSING_TABLES_MESSAGE = (
    "Las tablas del servicio de predicciones no existen en la base de datos. Ejecuta "
    "app/prediction/sql/ml_tables.sql o 'python -m app.prediction.scripts_pred --create-ml-tables'.")


class HistoryUnavailableError(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _fail(db: Session, exc: Exception):
    db.rollback()
    logger.warning("Operación sobre tablas de predicción fallida: %s", exc)
    raise HistoryUnavailableError(MISSING_TABLES_MESSAGE) from exc


# --------------------------------------------------------------------------- modelos

def register_model(db: Session, metadata: dict, user_id: int | None) -> int | None:
    metrics = metadata.get("metricas_preliminares") or {}
    training = metadata.get("entrenamiento") or {}
    prep = metadata.get("preparacion") or {}
    try:
        db.execute(update(PrediccionModelo)
                   .where(PrediccionModelo.granularidad == metadata["granularidad"],
                          PrediccionModelo.estado == "ACTIVO")
                   .values(estado="INACTIVO"))
        row = PrediccionModelo(
            nombre=metadata["nombre"], version=metadata["version"], granularidad=metadata["granularidad"],
            estado="ACTIVO", fecha_entrenamiento=datetime.fromisoformat(metadata["fecha_entrenamiento"]),
            epocas_ejecutadas=training.get("epocas_ejecutadas"),
            loss_entrenamiento=training.get("loss_entrenamiento_final"),
            loss_validacion=training.get("loss_validacion_final"),
            mae=metrics.get("mae"), mse=metrics.get("mse"), rmse=metrics.get("rmse"),
            mape=metrics.get("mape_percentage"), porcentaje_acierto=metrics.get("accuracy_percentage"),
            muestras_entrenamiento=prep.get("registros_entrenamiento"),
            muestras_validacion=prep.get("registros_validacion"),
            muestras_prueba=prep.get("registros_prueba"),
            fuente_datos=prep.get("fuente_datos"), ruta_artefactos=metadata.get("ruta_artefactos"),
            resumen_json=dumps({"preparacion": prep, "entrenamiento": {k: v for k, v in training.items() if k != "historial"}}),
            usuario_id=user_id,
        )
        db.add(row)
        db.commit()
        return int(row.modelo_id)
    except SQLAlchemyError as exc:
        _fail(db, exc)


def list_models(db: Session, granularity: str | None = None) -> list[PrediccionModelo]:
    try:
        query = select(PrediccionModelo).order_by(PrediccionModelo.fecha_entrenamiento.desc())
        if granularity:
            query = query.where(PrediccionModelo.granularidad == granularity)
        return list(db.scalars(query))
    except SQLAlchemyError as exc:
        _fail(db, exc)


# --------------------------------------------------------------------------- historial

def find_duplicate(db: Session, request_key: str, window_seconds: int) -> PrediccionHistorial | None:
    try:
        query = select(PrediccionHistorial).where(PrediccionHistorial.clave_solicitud == request_key)
        if window_seconds > 0:
            query = query.where(PrediccionHistorial.fecha_generacion >= now() - timedelta(seconds=window_seconds))
        return db.scalars(query.order_by(PrediccionHistorial.prediccion_id.desc()).limit(1)).first()
    except SQLAlchemyError as exc:
        _fail(db, exc)


def save_prediction(db: Session, **fields) -> PrediccionHistorial:
    try:
        row = PrediccionHistorial(**fields)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except SQLAlchemyError as exc:
        _fail(db, exc)


def get_prediction(db: Session, prediction_id: int) -> PrediccionHistorial | None:
    try:
        return db.get(PrediccionHistorial, prediction_id)
    except SQLAlchemyError as exc:
        _fail(db, exc)


def list_predictions(db: Session, offset: int = 0, limit: int = 20, granularity: str | None = None,
                     only_finished_before=None) -> tuple[list[PrediccionHistorial], int]:
    try:
        query = select(PrediccionHistorial)
        count = select(func.count(PrediccionHistorial.prediccion_id))
        if granularity:
            query = query.where(PrediccionHistorial.granularidad == granularity)
            count = count.where(PrediccionHistorial.granularidad == granularity)
        if only_finished_before is not None:
            query = query.where(PrediccionHistorial.fecha_fin <= only_finished_before)
            count = count.where(PrediccionHistorial.fecha_fin <= only_finished_before)
        rows = list(db.scalars(query.order_by(PrediccionHistorial.prediccion_id.desc()).offset(offset).limit(limit)))
        return rows, int(db.scalar(count) or 0)
    except SQLAlchemyError as exc:
        _fail(db, exc)


def update_real_sales(db: Session, row: PrediccionHistorial, real: float) -> None:
    try:
        row.ventas_reales = round(real, 2)
        row.error_porcentual = round(abs(row.ventas_estimadas - real) / real * 100, 4) if real else None
        row.fecha_evaluacion = now()
        db.commit()
    except SQLAlchemyError as exc:
        _fail(db, exc)


def statistics(db: Session) -> dict:
    try:
        rows = db.execute(
            select(PrediccionHistorial.granularidad, PrediccionHistorial.canal,
                   func.count(PrediccionHistorial.prediccion_id),
                   func.avg(PrediccionHistorial.ventas_estimadas),
                   func.count(PrediccionHistorial.ventas_reales),
                   func.avg(PrediccionHistorial.error_porcentual),
                   func.max(PrediccionHistorial.fecha_generacion))
            .group_by(PrediccionHistorial.granularidad, PrediccionHistorial.canal)
        ).all()
    except SQLAlchemyError as exc:
        _fail(db, exc)
    groups = [{
        "granularity": g, "channel": c, "predictions": int(n),
        "average_predicted_sales": round(float(avg), 2) if avg is not None else None,
        "evaluated_against_real_sales": int(evaluated),
        "average_error_percentage": round(float(err), 4) if err is not None else None,
        "last_generated_at": last,
    } for g, c, n, avg, evaluated, err, last in rows]
    return {
        "total_predictions": sum(g["predictions"] for g in groups),
        "total_evaluated": sum(g["evaluated_against_real_sales"] for g in groups),
        "groups": groups,
    }


# --------------------------------------------------------------------------- evaluaciones

def save_evaluation(db: Session, kind: str, granularity: str, version: int | None, report: dict, detail) -> int:
    try:
        row = PrediccionEvaluacion(
            tipo=kind, granularidad=granularity, modelo_version=version, fecha_evaluacion=now(),
            muestras=int(report.get("samples") or 0), mae=report.get("mae"), mse=report.get("mse"),
            rmse=report.get("rmse"), mape=report.get("mape_percentage"),
            porcentaje_acierto=report.get("accuracy_percentage"), detalle_json=dumps(detail),
        )
        db.add(row)
        db.commit()
        return int(row.evaluacion_id)
    except SQLAlchemyError as exc:
        _fail(db, exc)


def latest_evaluation(db: Session, granularity: str, kind: str) -> PrediccionEvaluacion | None:
    try:
        return db.scalars(select(PrediccionEvaluacion)
                          .where(PrediccionEvaluacion.granularidad == granularity, PrediccionEvaluacion.tipo == kind)
                          .order_by(PrediccionEvaluacion.evaluacion_id.desc()).limit(1)).first()
    except SQLAlchemyError as exc:
        _fail(db, exc)


# --------------------------------------------------------------------------- API Keys

def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_api_client(db: Session, name: str, scopes: list[str], created_by: int | None) -> tuple[PrediccionApiCliente, str]:
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    try:
        row = PrediccionApiCliente(
            nombre=name.strip(), prefijo=raw_key[:12], clave_hash=hash_api_key(raw_key),
            permisos=",".join(sorted(set(scopes))), activo=True, fecha_creacion=now(), creado_por=created_by)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, raw_key
    except SQLAlchemyError as exc:
        _fail(db, exc)


def list_api_clients(db: Session) -> list[PrediccionApiCliente]:
    try:
        return list(db.scalars(select(PrediccionApiCliente).order_by(PrediccionApiCliente.cliente_id)))
    except SQLAlchemyError as exc:
        _fail(db, exc)


def revoke_api_client(db: Session, client_id: int) -> bool:
    try:
        row = db.get(PrediccionApiCliente, client_id)
        if not row:
            return False
        row.activo = False
        db.commit()
        return True
    except SQLAlchemyError as exc:
        _fail(db, exc)


def verify_api_key(db: Session, raw_key: str) -> PrediccionApiCliente | None:
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX) or len(raw_key) > 200:
        return None
    try:
        row = db.scalars(select(PrediccionApiCliente).where(
            PrediccionApiCliente.clave_hash == hash_api_key(raw_key))).first()
        if not row or not row.activo or not secrets.compare_digest(row.clave_hash, hash_api_key(raw_key)):
            return None
        row.ultimo_uso = now()
        db.commit()
        return row
    except SQLAlchemyError as exc:
        _fail(db, exc)


def record_access(db: Session, method: str, path: str, channel: str, requester: str | None,
                  ip: str | None, result: str) -> None:
    """Registro de accesos best-effort: nunca bloquea la petición si la tabla no existe."""
    logger.info("prediction-api access method=%s path=%s channel=%s requester=%s ip=%s result=%s",
                method, path, channel, requester, ip, result)
    try:
        db.add(PrediccionAcceso(fecha=now(), metodo=method[:10], ruta=path[:255], canal=channel[:20],
                                solicitante=(requester or "")[:150] or None, ip=(ip or "")[:64] or None,
                                resultado=result))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
