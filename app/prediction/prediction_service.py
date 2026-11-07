"""FASE 6 — Integración del modelo TensorFlow con el sistema (servicio de predicción).

1. Recupera el modelo entrenado y 2. su scaler (``ModelStore.load``; sin reentrenar).
3. Recibe las variables necesarias: el histórico real de ventas se extrae de MySQL.
4. Valida los datos de entrada (granularidad, período, historia suficiente, variables finitas).
5. Transforma con el mismo pipeline y el mismo scaler del entrenamiento.
6. Ejecuta TensorFlow (pronóstico recursivo período a período).
7. Obtiene las ventas estimadas, 8. calcula la variación porcentual frente al período anterior
   equivalente, 9. recupera las métricas del modelo, 10. prepara la respuesta y
11. registra la predicción en el historial (opcional).

Controles: semáforo de concurrencia, tiempo máximo de inferencia, deduplicación de solicitudes
(ventana configurable o cabecera ``Idempotency-Key``).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.prediction import repository
from app.prediction.artifacts import LoadedModel, ModelNotTrainedError, ModelStore, model_store
from app.prediction.evaluation import ACCURACY_BASIS, regression_report
from app.prediction.preparation import (
    GRANULARITIES, TARGET, DataPreparationError, ExtractionResult, build_features, build_history_series,
    clean_transactions, describe_feature, get_granularity, load_transactions,
)

logger = logging.getLogger(__name__)

PERIODS: dict[str, tuple[str, int]] = {
    "7_days": ("daily", 7), "14_days": ("daily", 14), "30_days": ("daily", 30),
    "4_weeks": ("weekly", 4), "8_weeks": ("weekly", 8), "12_weeks": ("weekly", 12),
    "1_month": ("monthly", 1), "3_months": ("monthly", 3), "6_months": ("monthly", 6),
    "12_months": ("monthly", 12),
}


class PredictionBusyError(RuntimeError):
    pass


class PredictionTimeoutError(TimeoutError):
    pass


@dataclass
class GenerateParams:
    period: str
    prediction_type: str = "sales"
    granularity: str | None = None
    data_source: str = "auto"
    register: bool = True
    idempotency_key: str | None = None


def resolve_period(period: str, granularity: str | None) -> tuple[str, int]:
    if period not in PERIODS:
        raise DataPreparationError(f"Período no soportado: {period}. Valores permitidos: {list(PERIODS)}")
    native, steps = PERIODS[period]
    if granularity and granularity != native:
        allowed = [p for p, (g, _) in PERIODS.items() if g == granularity]
        raise DataPreparationError(
            f"El período '{period}' requiere granularidad '{native}'. Para '{granularity}' usa: {allowed}")
    return native, steps


def _performance(metadata: dict) -> dict:
    metrics = metadata.get("metricas_preliminares") or {}
    return {
        "metric_type": "PRELIMINAR",
        "evaluation_set": "prueba (un paso adelante con ventas reales como rezagos)",
        "mae": metrics.get("mae"), "mse": metrics.get("mse"), "rmse": metrics.get("rmse"),
        "mape_percentage": metrics.get("mape_percentage"),
        "wape_percentage": metrics.get("wape_percentage"),
        "accuracy_percentage": metrics.get("accuracy_percentage"),
        "accuracy_basis": ACCURACY_BASIS,
        "evaluated_samples": metrics.get("samples"),
        "train_loss": metrics.get("loss_entrenamiento"),
        "validation_loss": metrics.get("loss_validacion"),
        "evaluated_at": metrics.get("fecha_evaluacion"),
    }


def model_info(metadata: dict) -> dict:
    return {
        "name": metadata.get("nombre"),
        "version": metadata.get("version_etiqueta") or f"v{metadata.get('version')}",
        "version_number": metadata.get("version"),
        "granularity": metadata.get("granularidad"),
        "trained_at": metadata.get("fecha_entrenamiento"),
        "framework": f"TensorFlow {metadata.get('tensorflow_version') or ''}".strip(),
        "architecture": metadata.get("arquitectura"),
        "features": metadata.get("variables"),
        "target": metadata.get("variable_objetivo"),
    }


def history_row_to_dict(row) -> dict:
    return {
        "prediction_id": row.prediccion_id,
        "generated_at": row.fecha_generacion,
        "model_version": f"v{row.modelo_version}",
        "granularity": row.granularidad,
        "period": row.periodo,
        "prediction_type": row.tipo_prediccion,
        "start_date": row.fecha_inicio,
        "end_date": row.fecha_fin,
        "predicted_sales": row.ventas_estimadas,
        "previous_period_sales": row.ventas_periodo_anterior,
        "variation_percentage": row.variacion_porcentual,
        "currency": "COP",
        "breakdown": repository.loads(row.detalle_json, []),
        "prediction_variables": repository.loads(row.variables_json, []),
        "channel": row.canal,
        "requested_by": row.solicitante,
        "real_sales": row.ventas_reales,
        "error_percentage": row.error_porcentual,
        "evaluated_at": row.fecha_evaluacion,
    }


class PredictionService:
    def __init__(self, store: ModelStore = model_store) -> None:
        self.store = store
        self._semaphore = threading.BoundedSemaphore(settings.prediction_max_concurrent)
        self._executor = ThreadPoolExecutor(max_workers=settings.prediction_max_concurrent,
                                            thread_name_prefix="ml-predict")
        self._inflight: dict[str, threading.Lock] = {}
        self._inflight_guard = threading.Lock()

    # -- núcleo de inferencia (sin efectos secundarios) --------------------------------
    def forecast(self, loaded: LoadedModel, extraction: ExtractionResult, steps: int,
                 reference: datetime | None = None) -> dict:
        metadata = loaded.metadata
        granularity = loaded.granularity
        cfg = get_granularity(granularity)
        if granularity != "monthly" and not extraction.has_exact_dates:
            raise DataPreparationError(
                f"La granularidad '{granularity}' requiere fechas exactas de MySQL; la fuente '{extraction.source}' sólo tiene meses")
        bounds = tuple(metadata["limites_atipicos"]) if metadata.get("limites_atipicos") else None
        series = build_history_series(extraction, granularity, bounds, reference)
        if len(series) < cfg.warmup:
            raise DataPreparationError(
                f"Se necesitan al menos {cfg.warmup} {cfg.unit} de historia para predecir; hay {len(series)}")
        origin = pd.Period(metadata["origen_serie"], freq=cfg.period_freq)
        history = series[["periodo", "fecha_periodo", TARGET]].tail(cfg.warmup).reset_index(drop=True)
        breakdown, first_variables = [], None
        for step in range(steps):
            next_period = history["periodo"].iloc[-1] + 1
            pending = pd.DataFrame([{"periodo": next_period, "fecha_periodo": next_period.start_time, TARGET: np.nan}])
            extended = pd.concat([history, pending], ignore_index=True)
            features = build_features(extended, cfg, origin).iloc[[-1]]
            value = float(loaded.predict(features)[0])
            if step == 0:
                first_variables = features[loaded.transformer.feature_names].iloc[0].to_dict()
            extended.loc[extended.index[-1], TARGET] = value
            history = extended.tail(cfg.warmup).reset_index(drop=True)
            breakdown.append({
                "period_start": next_period.start_time.date().isoformat(),
                "period_end": next_period.end_time.date().isoformat(),
                "predicted_sales": round(value, 2),
            })
        predicted_total = round(sum(item["predicted_sales"] for item in breakdown), 2)

        # Variación frente al período anterior equivalente con ventas REALES (sin ajuste de atípicos).
        raw_series = build_history_series(extraction, granularity, None, reference)
        previous = raw_series[TARGET].tail(steps) if len(raw_series) >= steps else None
        previous_total = round(float(previous.sum()), 2) if previous is not None else None
        variation = (round((predicted_total - previous_total) / previous_total * 100, 2)
                     if previous_total else None)
        last = series.iloc[-1]
        return {
            "granularity": granularity,
            "steps": steps,
            "start_date": breakdown[0]["period_start"],
            "end_date": breakdown[-1]["period_end"],
            "predicted_sales": predicted_total,
            "previous_period_sales": previous_total,
            "variation_percentage": variation,
            "breakdown": breakdown,
            "prediction_variables": [
                {"name": name, "value": round(float(value), 6), "description": describe_feature(name)}
                for name, value in (first_variables or {}).items()
            ],
            "history": {
                "data_source": extraction.source,
                "last_complete_period": last["fecha_periodo"].date().isoformat(),
                "periods_available": int(len(series)),
                "warnings": extraction.warnings,
            },
        }

    # -- orquestación con controles de disponibilidad -------------------------------
    def _request_key(self, params: GenerateParams, granularity: str, version: int, requester: str) -> str:
        if params.idempotency_key:
            base = f"idem|{requester}|{params.idempotency_key}"
        else:
            base = f"{granularity}|{params.period}|{params.prediction_type}|v{version}|{params.data_source}|{date.today()}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _inflight_lock(self, key: str) -> threading.Lock:
        with self._inflight_guard:
            if len(self._inflight) > 256:
                self._inflight = {k: v for k, v in self._inflight.items() if v.locked()}
            return self._inflight.setdefault(key, threading.Lock())

    def generate(self, db: Session, params: GenerateParams, principal: dict) -> dict:
        if params.prediction_type != "sales":
            raise DataPreparationError("Sólo se admite prediction_type='sales'")
        granularity, steps = resolve_period(params.period, params.granularity)
        loaded = self.store.load(granularity)  # 1 y 2: modelo + scaler persistidos (ModelNotTrainedError si no hay)
        requester = principal.get("name") or "desconocido"
        key = self._request_key(params, granularity, loaded.version, requester)

        with self._inflight_lock(key):
            if params.register:
                try:
                    window = None if params.idempotency_key else settings.prediction_dedup_window_seconds
                    if window != 0:
                        existing = repository.find_duplicate(db, key, window or 0)
                        if existing is not None:
                            return self._response(history_row_to_dict(existing), loaded.metadata, existing.prediccion_id,
                                                  duplicated=True, registered=True)
                except repository.HistoryUnavailableError:
                    pass

            if not self._semaphore.acquire(timeout=5):
                raise PredictionBusyError("El servicio de predicción está ocupado; reintenta en unos segundos")
            try:
                extraction = load_transactions(db, params.data_source)  # E/S de BD en el hilo de la petición
                future = self._executor.submit(self.forecast, loaded, extraction, steps)
                try:
                    result = future.result(timeout=settings.prediction_inference_timeout_seconds)
                except FutureTimeout as exc:
                    raise PredictionTimeoutError(
                        f"La inferencia superó {settings.prediction_inference_timeout_seconds:.0f} s") from exc
            finally:
                self._semaphore.release()

            prediction_id, registered, warning = None, False, None
            if params.register:
                try:
                    row = repository.save_prediction(
                        db, fecha_generacion=repository.now(), modelo_version=loaded.version,
                        granularidad=granularity, periodo=params.period, tipo_prediccion=params.prediction_type,
                        fecha_inicio=date.fromisoformat(result["start_date"]),
                        fecha_fin=date.fromisoformat(result["end_date"]),
                        ventas_estimadas=result["predicted_sales"],
                        ventas_periodo_anterior=result["previous_period_sales"],
                        variacion_porcentual=result["variation_percentage"],
                        detalle_json=repository.dumps(result["breakdown"]),
                        variables_json=repository.dumps(result["prediction_variables"]),
                        canal=principal.get("channel", "JWT"), solicitante=requester, clave_solicitud=key,
                    )
                    prediction_id, registered = row.prediccion_id, True
                except repository.HistoryUnavailableError as exc:
                    warning = str(exc)
            payload = {**result, "period": params.period, "prediction_type": params.prediction_type, "currency": "COP"}
            response = self._response(payload, loaded.metadata, prediction_id, duplicated=False, registered=registered)
            if warning:
                response["warnings"] = [warning]
            return response

    @staticmethod
    def _response(payload: dict, metadata: dict, prediction_id, duplicated: bool, registered: bool) -> dict:
        return {
            "prediction_id": prediction_id,
            "duplicated": duplicated,
            "registered": registered,
            "model": model_info(metadata),
            "forecast": {
                "period": payload.get("period"),
                "prediction_type": payload.get("prediction_type", "sales"),
                "granularity": payload.get("granularity"),
                "start_date": str(payload.get("start_date")),
                "end_date": str(payload.get("end_date")),
                "predicted_sales": payload.get("predicted_sales"),
                "currency": "COP",
                "previous_period_sales": payload.get("previous_period_sales"),
                "variation_percentage": payload.get("variation_percentage"),
                "breakdown": payload.get("breakdown", []),
            },
            "performance": _performance(metadata),
            "prediction_variables": payload.get("prediction_variables", []),
            "history": payload.get("history"),
            "generated_at": payload.get("generated_at") or repository.now(),
        }

    # -- métricas posteriores -------------------------------------------------------
    def compare(self, db: Session, granularity: str | None = None, limit: int = 50,
                data_source: str = "auto", persist: bool = True) -> dict:
        rows, _ = repository.list_predictions(db, 0, limit, granularity)
        extraction = load_transactions(db, data_source)
        clean, _ = clean_transactions(extraction.transactions)
        last_data = clean["fecha"].max() if not clean.empty else None
        items, actual, predicted = [], [], []
        for row in rows:
            real = row.ventas_reales
            if real is None:
                real = _real_sales(clean, last_data, row.granularidad, row.fecha_inicio, row.fecha_fin)
                if real is not None and persist:
                    repository.update_real_sales(db, row, real)
            item = {
                "prediction_id": row.prediccion_id, "granularity": row.granularidad, "period": row.periodo,
                "start_date": row.fecha_inicio, "end_date": row.fecha_fin, "model_version": f"v{row.modelo_version}",
                "predicted_sales": row.ventas_estimadas, "real_sales": round(real, 2) if real is not None else None,
                "difference": round(row.ventas_estimadas - real, 2) if real is not None else None,
                "error_percentage": round(abs(row.ventas_estimadas - real) / real * 100, 4) if real else None,
                "status": "EVALUADA" if real is not None else "PENDIENTE",
            }
            items.append(item)
            if real is not None:
                actual.append(real)
                predicted.append(row.ventas_estimadas)
        return {
            "metric_type": "POSTERIOR",
            "description": "Predicciones registradas comparadas con las ventas reales ocurridas después",
            "evaluated": len(actual),
            "pending": len(items) - len(actual),
            "metrics": regression_report(actual, predicted),
            "items": items,
        }

    def evaluate_model(self, db: Session, granularity: str, data_source: str = "auto",
                       include_posterior: bool = True) -> dict:
        """Reevalúa la versión activa sobre períodos posteriores a su validación (nunca vistos)."""
        loaded = self.store.load(granularity)
        metadata = loaded.metadata
        cfg = get_granularity(granularity)
        extraction = load_transactions(db, data_source)
        bounds = tuple(metadata["limites_atipicos"]) if metadata.get("limites_atipicos") else None
        series = build_history_series(extraction, granularity, bounds)
        origin = pd.Period(metadata["origen_serie"], freq=cfg.period_freq)
        featured = build_features(series, cfg, origin).iloc[cfg.warmup:] if len(series) > cfg.warmup else series.iloc[0:0]
        holdout = featured[pd.to_datetime(featured["fecha_periodo"]) > pd.Timestamp(metadata["fin_validacion"])] \
            if not featured.empty else featured
        preliminary = None
        if not holdout.empty:
            pred = loaded.predict(holdout)
            report = regression_report(holdout[TARGET].to_numpy(dtype=float), pred)
            preliminary = {**report, "tipo": "PRELIMINAR", "conjunto": "períodos posteriores a la validación",
                           "fecha_evaluacion": repository.now().isoformat(), "version_modelo": loaded.version}
            self.store.update_metadata(granularity, loaded.version, {"ultima_reevaluacion": preliminary})
        result = {"model": model_info(metadata), "preliminary": preliminary,
                  "preliminary_message": None if preliminary else "No hay períodos no vistos para reevaluar"}
        warnings = []
        try:
            if preliminary:
                repository.save_evaluation(db, "PRELIMINAR", granularity, loaded.version, preliminary, None)
            if include_posterior:
                posterior = self.compare(db, granularity, limit=200, data_source=data_source)
                result["posterior"] = posterior
                if posterior["evaluated"]:
                    repository.save_evaluation(db, "POSTERIOR", granularity, loaded.version,
                                               posterior["metrics"], posterior["items"])
        except repository.HistoryUnavailableError as exc:
            warnings.append(str(exc))
        result["warnings"] = warnings
        return result

    def model_overview(self) -> list[dict]:
        overview = []
        for name in GRANULARITIES:
            version = self.store.active_version(name)
            entry = {"granularity": name, "trained": bool(version), "active_version": f"v{version}" if version else None,
                     "available_versions": [f"v{v}" for v in self.store.versions(name)]}
            if version:
                metadata = self.store.read_metadata(name, version)
                entry.update({"trained_at": metadata.get("fecha_entrenamiento"),
                              "performance": _performance(metadata)})
            overview.append(entry)
        return overview


def _real_sales(clean: pd.DataFrame, last_data, granularity: str, start, end) -> float | None:
    """Ventas reales del rango sólo si el período ya terminó y los datos lo cubren por completo."""
    if last_data is None or pd.isna(last_data):
        return None
    cfg = GRANULARITIES.get(granularity) or GRANULARITIES["monthly"]
    end_ts = pd.Timestamp(end)
    if end_ts.normalize() >= pd.Timestamp(datetime.now()).normalize():
        return None
    if pd.Timestamp(last_data).to_period(cfg.period_freq) < end_ts.to_period(cfg.period_freq):
        return None
    mask = (clean["fecha"] >= pd.Timestamp(start)) & (clean["fecha"] < end_ts + pd.Timedelta(days=1))
    return float(clean.loc[mask, "venta_total"].sum())


prediction_service = PredictionService()


__all__ = ["PERIODS", "GenerateParams", "ModelNotTrainedError", "PredictionBusyError", "PredictionService",
           "PredictionTimeoutError", "history_row_to_dict", "model_info", "prediction_service", "resolve_period"]
