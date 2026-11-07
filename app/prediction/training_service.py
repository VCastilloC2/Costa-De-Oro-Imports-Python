"""FASE 4 — Entrenamiento de modelos (operación independiente de la predicción).

* Sólo se entrena bajo petición explícita de un ADMIN (``POST /api/v1/predictions/model/train``);
  la generación de predicciones NUNCA entrena.
* Un único entrenamiento a la vez: candado en memoria + archivo de bloqueo entre procesos/workers.
* La extracción y validación de datos (FASE 1) ocurren antes de responder, así un dataset
  insuficiente se informa de inmediato; el ajuste de la red corre en un hilo de fondo.
* Registra épocas, pérdidas, métricas, versión, fecha y guarda el modelo y el scaler.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.prediction.artifacts import ModelStore, model_store
from app.prediction.evaluation import ACCURACY_BASIS, comparison_rows, regression_report
from app.prediction.preparation import TARGET, PreparationResult, load_transactions, prepare_sales_data
from app.prediction.repository import HistoryUnavailableError, register_model, save_evaluation
from app.prediction.tf_model import (
    ARCHITECTURE, MODEL_NAME, TrainingConfig, build_sales_network, fit_network, predict_scaled,
    tensorflow_version,
)
from app.prediction.transformation import SalesTensorTransformer

logger = logging.getLogger(__name__)


class TrainingInProgressError(RuntimeError):
    pass


@dataclass
class TrainingParams:
    granularity: str = "monthly"
    data_source: str = "auto"
    epochs: int = 300
    batch_size: int = 16
    learning_rate: float = 0.001
    patience: int = 25


def _iso(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


class TrainingService:
    def __init__(self, store: ModelStore = model_store) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._state: dict = {"status": "idle", "job_id": None}

    # -- consulta --------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            state = dict(self._state)
            state["epochs"] = list(state.get("epochs") or [])
        return state

    def is_running(self) -> bool:
        with self._lock:
            return self._state.get("status") in {"queued", "running"}

    def _update(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    # -- inicio ----------------------------------------------------------------
    def start(self, db: Session, params: TrainingParams, requested_by: dict, wait: bool = False,
              session_factory: Callable[[], Session] | None = None) -> dict:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            if self._state.get("status") in {"queued", "running"}:
                raise TrainingInProgressError(f"Ya hay un entrenamiento en curso (job {self._state.get('job_id')})")
            if not self.store.acquire_training_lock(job_id):
                raise TrainingInProgressError("Otro proceso del backend está entrenando un modelo")
            self._state = {
                "status": "queued", "job_id": job_id, "granularity": params.granularity,
                "params": asdict(params), "requested_by": requested_by,
                "queued_at": _iso(datetime.now()), "started_at": None, "finished_at": None,
                "current_epoch": 0, "max_epochs": params.epochs, "epochs": [],
                "model_version": None, "error": None, "result": None,
            }
        try:
            extraction = load_transactions(db, params.data_source)
            prepared = prepare_sales_data(extraction, params.granularity)
        except Exception as exc:
            self._update(status="failed", error=str(exc), finished_at=_iso(datetime.now()))
            self.store.release_training_lock(job_id)
            raise
        self._update(preparation=prepared.summary)
        factory = session_factory or sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
        if wait:
            self._run(job_id, prepared, params, requested_by, factory)
        else:
            threading.Thread(target=self._run, args=(job_id, prepared, params, requested_by, factory),
                             name=f"ml-train-{job_id}", daemon=True).start()
        return self.status()

    # -- ejecución ---------------------------------------------------------------
    def _on_epoch(self, epoch: int, logs: dict) -> None:
        entry = {"epoch": epoch, **{k: round(float(v), 6) for k, v in logs.items()}}
        with self._lock:
            self._state["current_epoch"] = epoch
            self._state.setdefault("epochs", []).append(entry)

    def _run(self, job_id: str, prepared: PreparationResult, params: TrainingParams, requested_by: dict,
             session_factory: Callable[[], Session]) -> None:
        self._update(status="running", started_at=_iso(datetime.now()))
        try:
            transformer = SalesTensorTransformer(prepared.feature_names, prepared.target)
            data = transformer.prepare(prepared)  # FASE 2
            config = TrainingConfig(epochs=params.epochs, batch_size=params.batch_size,
                                    learning_rate=params.learning_rate, patience=params.patience)
            model = build_sales_network(len(prepared.feature_names), config.learning_rate, config.seed)  # FASE 3
            fit = fit_network(model, data, config, self._on_epoch)
            train_loss, train_mae = model.evaluate(data.x_train, data.y_train, verbose=0)
            val_loss, val_mae = model.evaluate(data.x_val, data.y_val, verbose=0)

            # FASE 5 — métricas preliminares sobre el conjunto de prueba (en COP, no escaladas).
            predicted = transformer.inverse_target(predict_scaled(model, data.x_test))
            actual = prepared.splits["prueba"][TARGET].to_numpy(dtype=float)
            evaluated_at = datetime.now()
            metrics = regression_report(actual, predicted)

            version = self.store.next_version(prepared.granularity)
            splits = prepared.splits
            metadata = {
                "nombre": MODEL_NAME,
                "version": version,
                "version_etiqueta": f"v{version}",
                "granularidad": prepared.granularity,
                "fecha_entrenamiento": _iso(datetime.now()),
                "job_id": job_id,
                "entrenado_por": requested_by,
                "tensorflow_version": tensorflow_version(),
                "arquitectura": ARCHITECTURE,
                "compilacion": {"optimizer": "Adam", "learning_rate": config.learning_rate,
                                "loss": "mean_squared_error", "metrics": ["mean_absolute_error"],
                                "early_stopping": {"monitor": "val_loss", "patience": config.patience,
                                                   "start_from_epoch": config.start_from_epoch,
                                                   "restore_best_weights": True}},
                "variables": prepared.feature_names,
                "variable_objetivo": prepared.target,
                "origen_serie": prepared.origin,
                "limites_atipicos": list(prepared.outlier_bounds) if prepared.outlier_bounds else None,
                "fin_entrenamiento": splits["entrenamiento"]["fecha_periodo"].max().date().isoformat(),
                "fin_validacion": splits["validacion"]["fecha_periodo"].max().date().isoformat(),
                "fin_historia": prepared.series["fecha_periodo"].max().date().isoformat(),
                "preparacion": prepared.summary,
                "formas_tensores": data.shapes(),
                "entrenamiento": {
                    "config": asdict(config),
                    "epocas_ejecutadas": fit["epocas_ejecutadas"],
                    "mejor_epoca": fit["mejor_epoca"],
                    "detenido_anticipadamente": fit["detenido_anticipadamente"],
                    "loss_entrenamiento_final": round(float(train_loss), 6),
                    "loss_validacion_final": round(float(val_loss), 6),
                    "mae_entrenamiento_escalado": round(float(train_mae), 6),
                    "mae_validacion_escalado": round(float(val_mae), 6),
                    "nota": "Las pérdidas se expresan sobre la variable objetivo normalizada (StandardScaler)",
                    "historial": fit["historial"],
                },
                "metricas_preliminares": {
                    **metrics,
                    "tipo": "PRELIMINAR",
                    "conjunto": "prueba",
                    "fecha_evaluacion": _iso(evaluated_at),
                    "version_modelo": version,
                    "loss_entrenamiento": round(float(train_loss), 6),
                    "loss_validacion": round(float(val_loss), 6),
                    "base_acierto": ACCURACY_BASIS,
                    "comparacion": comparison_rows(data.test_dates, actual, predicted),
                },
            }
            metadata["ruta_artefactos"] = str(self.store.version_dir(prepared.granularity, version))
            self.store.save(prepared.granularity, version, model, transformer, metadata)

            registry_warning = None
            with session_factory() as session:
                try:
                    register_model(session, metadata, requested_by.get("user_id"))
                    save_evaluation(session, "PRELIMINAR", prepared.granularity, version, metrics,
                                    metadata["metricas_preliminares"]["comparacion"])
                except HistoryUnavailableError as exc:
                    registry_warning = str(exc)
            self._update(
                status="completed", finished_at=_iso(datetime.now()), model_version=version,
                result={
                    "model_version": version, "granularity": prepared.granularity,
                    "epochs_run": fit["epocas_ejecutadas"], "best_epoch": fit["mejor_epoca"],
                    "train_loss": metadata["entrenamiento"]["loss_entrenamiento_final"],
                    "validation_loss": metadata["entrenamiento"]["loss_validacion_final"],
                    "preliminary_metrics": {k: v for k, v in metadata["metricas_preliminares"].items()
                                            if k != "comparacion"},
                    "registry_warning": registry_warning,
                },
            )
            logger.info("Entrenamiento %s completado: %s v%s", job_id, prepared.granularity, version)
        except Exception as exc:  # noqa: BLE001 - se informa en el estado del job
            logger.exception("Entrenamiento %s fallido", job_id)
            self._update(status="failed", finished_at=_iso(datetime.now()), error=f"{type(exc).__name__}: {exc}")
        finally:
            self.store.release_training_lock(job_id)


training_service = TrainingService()
