"""API REST de predicciones de ventas (servicio de Machine Learning con TensorFlow).

TensorFlow se ejecuta Ãºnicamente en este backend; los clientes (Flutter, Spring Boot, Node.js,
Python, etc.) sÃ³lo envÃ­an y reciben JSON. Ver ``docs/API_PREDICCIONES.md``.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from importlib.metadata import version
import logging
import math
import platform
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import admin_user, prediction_access
from app.core.database import get_db
from app.prediction import repository
from app.prediction.artifacts import ModelNotTrainedError, model_store
from app.prediction.prediction_service import (
    PERIODS, GenerateParams, PredictionBusyError, PredictionTimeoutError, history_row_to_dict, model_info,
    prediction_service,
)
from app.prediction.preparation import DataPreparationError
from app.prediction.repository import SCOPE_GENERATE, SCOPE_READ, HistoryUnavailableError
from app.prediction.tf_model import TensorFlowUnavailableError, tensorflow_version
from app.prediction.training_service import TrainingInProgressError, TrainingParams, training_service
from app.prediction.transformation import TransformationError
from app.schemas.prediction_api import (
    GENERATE_RESPONSE_EXAMPLE, ApiClientCreated, ApiClientCreateRequest, ApiClientInfo, ApiResponse,
    ComparisonResult, ErrorResponse, EvaluateRequest, GeneratedPrediction, GeneratePredictionRequest,
    GranularityLiteral, ModelMetrics, ModelStatus, PaginatedPredictions, PredictionRecord, PredictionSummary,
    TrainingStatus, TrainRequest,
)
from app.prediction.data_handler import load_dataset
from app.prediction.engine import evaluate, predict_month_from_data
from app.schemas.prediction import (
    DemandPredictionMetrics,
    DemandPredictionRequest,
    DemandPredictionResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/predictions", tags=["Predicciones Analytics"])


@router.post(
    "/demand",
    response_model=DemandPredictionResponse,
    dependencies=[Depends(admin_user)],
    summary="Estimar ventas mensuales con metadata y mÃ©tricas del modelo",
)
def predict_demand(
    payload: DemandPredictionRequest,
    db: Session = Depends(get_db),
) -> DemandPredictionResponse:
    """Return a monthly sales estimate with out-of-sample quality metrics.

    The current trained target is aggregate sales revenue, not units by SKU.
    If a holdout validation cannot be calculated, confidence is explicitly 0%
    and the response explains that the metric is unavailable.
    """
    today = date.today()
    year = payload.target_year or today.year
    month = payload.target_month or today.month

    try:
        dataset = load_dataset(db, today)
        prediction = predict_month_from_data(dataset, year, month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("El pipeline de predicciÃ³n no estÃ¡ disponible")
        raise HTTPException(status_code=503, detail="El motor predictivo no estÃ¡ disponible") from exc
    except Exception as exc:
        logger.exception("FallÃ³ la inferencia de ventas")
        raise HTTPException(status_code=503, detail="No se pudo completar la predicciÃ³n") from exc

    try:
        validation = evaluate(dataset, today.year)
    except Exception:
        logger.exception("No se pudo calcular la validaciÃ³n del modelo")
        validation = None
    def finite(value):
        number = float(value) if value is not None else None
        return number if number is not None and math.isfinite(number) else None

    mape = finite(validation.get("mape")) if validation else None
    confidence = round(max(0.0, min(100.0, 100.0 - float(mape))), 2) if mape is not None else 0.0
    # Keep the required numeric field meaningful when no holdout exists; the
    # confidence_basis tells consumers this is an unavailable validation.
    error_margin = round(max(0.0, float(mape)), 2) if mape is not None else 100.0
    metrics = DemandPredictionMetrics(
        validation_year=validation.get("anio_prueba") if validation else None,
        mean_absolute_error=finite(validation.get("mae")) if validation else None,
        root_mean_squared_error=finite(validation.get("rmse")) if validation else None,
        mape_percentage=mape,
        r_squared=finite(validation.get("r2")) if validation else None,
        sample_count=int(validation.get("n", 0)) if validation else 0,
    )

    return DemandPredictionResponse(
        predicted_variable="Ventas estimadas del mes (COP)",
        prediction_value=prediction["prediccion"],
        confidence_percentage=confidence,
        error_margin_percentage=error_margin,
        algorithm_name=(
            "Ensamble promedio: RegresiÃ³n Lineal (Scikit-Learn) + "
            "Red Neuronal MLP (TensorFlow/Keras)"
        ),
        model_version="sales-ensemble-v1",
        tools_used=[
            f"Python {platform.python_version()}",
            f"FastAPI {version('fastapi')}",
            f"Scikit-Learn {version('scikit-learn')}",
            f"TensorFlow/Keras {version('tensorflow')}",
            f"Pandas {version('pandas')}",
            f"NumPy {version('numpy')}",
        ],
        target_period=f"{year:04d}-{month:02d}",
        confidence_basis=(
            "Indicador orientativo calculado como 100 - MAPE; "
            f"validaciÃ³n temporal sobre {metrics.sample_count} observaciones"
            if validation
            else "Sin suficientes aÃ±os histÃ³ricos para validar fuera de muestra; confianza no estimable"
        ),
        metrics=metrics,
        generated_at=datetime.now(timezone.utc),
    )


# =============================================================================
# Servicio ML reutilizable (TensorFlow) — /api/v1/predictions/...
# =============================================================================
ML_TAG = "Predicciones ML (TensorFlow)"
ADMIN_TAG = "Predicciones ML · Administración"
READ = Depends(prediction_access(SCOPE_READ))
GENERATE = Depends(prediction_access(SCOPE_GENERATE))
ADMIN_ONLY = Depends(prediction_access(SCOPE_READ, admin_only=True))
Principal = Annotated[dict, READ]

AUTH_DOC = (
    "\n\n**Autenticación:** `Authorization: Bearer <JWT>` de un usuario con rol permitido "
    "(por defecto ADMIN) **o** `X-API-Key: <clave de servicio>` con el permiso `{scope}`.")
ADMIN_DOC = "\n\n**Autenticación:** sólo `Authorization: Bearer <JWT>` de un usuario **ADMIN** (las API Keys se rechazan)."


def _err(description: str) -> dict:
    return {"model": ErrorResponse, "description": description}


AUTH_ERRORS = {401: _err("Falta la credencial o es inválida/expirada"),
               403: _err("La credencial no tiene permisos para esta operación"),
               422: _err("Solicitud inválida (validación de parámetros o de datos)")}


class PredictionAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


def _ok(message: str, data) -> dict:
    return {"success": True, "message": message, "data": data}


@contextmanager
def api_errors():
    """Traduce las excepciones del dominio ML a respuestas JSON consistentes."""
    try:
        yield
    except PredictionAPIError:
        raise
    except ModelNotTrainedError as exc:
        raise PredictionAPIError(409, "MODEL_NOT_TRAINED", str(exc)) from exc
    except TrainingInProgressError as exc:
        raise PredictionAPIError(409, "TRAINING_IN_PROGRESS", str(exc)) from exc
    except DataPreparationError as exc:
        raise PredictionAPIError(422, "INVALID_DATA", str(exc), exc.summary or None) from exc
    except TransformationError as exc:
        raise PredictionAPIError(422, "TRANSFORMATION_ERROR", str(exc)) from exc
    except PredictionBusyError as exc:
        raise PredictionAPIError(429, "SERVICE_BUSY", str(exc)) from exc
    except PredictionTimeoutError as exc:
        raise PredictionAPIError(504, "INFERENCE_TIMEOUT", str(exc)) from exc
    except HistoryUnavailableError as exc:
        raise PredictionAPIError(503, "HISTORY_UNAVAILABLE", str(exc)) from exc
    except TensorFlowUnavailableError as exc:
        raise PredictionAPIError(503, "TENSORFLOW_UNAVAILABLE", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en la API de predicciones")
        raise PredictionAPIError(500, "INTERNAL_ERROR", "Error interno del servicio de predicciones") from exc


def _is_ml_path(request: Request) -> bool:
    path = request.url.path
    return path.startswith(router.prefix) and not path.startswith(f"{router.prefix}/demand")


def install_prediction_error_handlers(app: FastAPI) -> None:
    """Formato de error uniforme en /api/v1/predictions (salvo /demand, que conserva su contrato)."""
    codes = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
             405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 429: "TOO_MANY_REQUESTS"}

    @app.exception_handler(PredictionAPIError)
    async def _prediction_error(_request: Request, exc: PredictionAPIError):
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder({
            "success": False, "message": exc.message, "error": {"code": exc.code, "details": exc.details}}))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        if not _is_ml_path(request):
            return await http_exception_handler(request, exc)
        return JSONResponse(status_code=exc.status_code, headers=getattr(exc, "headers", None), content={
            "success": False, "message": str(exc.detail),
            "error": {"code": codes.get(exc.status_code, f"HTTP_{exc.status_code}"), "details": None}})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if not _is_ml_path(request):
            return await request_validation_exception_handler(request, exc)
        details = [{"field": ".".join(str(p) for p in err.get("loc", [])), "message": err.get("msg")}
                   for err in exc.errors()]
        return JSONResponse(status_code=422, content={
            "success": False, "message": "Solicitud inválida", "error": {"code": "VALIDATION_ERROR", "details": details}})


def _history_available(db: Session) -> bool:
    try:
        repository.list_predictions(db, 0, 1)
        return True
    except HistoryUnavailableError:
        return False


def _periods_by_granularity() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for period, (granularity, _) in PERIODS.items():
        grouped.setdefault(granularity, []).append(period)
    return grouped


@router.get(
    "/health", tags=[ML_TAG], summary="Disponibilidad del servicio (público)",
    description="Comprobación ligera sin autenticación para balanceadores y monitores. No expone métricas.",
    responses={200: {"content": {"application/json": {"example": {
        "success": True, "message": "Servicio de predicciones disponible",
        "data": {"status": "ok", "model_available": True}}}}}},
)
def ml_health():
    with api_errors():
        available = any(model_store.active_version(g) for g in ("daily", "weekly", "monthly"))
    return _ok("Servicio de predicciones disponible", {"status": "ok", "model_available": available})


@router.get(
    "/model/status", tags=[ML_TAG], response_model=ApiResponse[ModelStatus], responses=AUTH_ERRORS,
    summary="Estado del servicio, modelos entrenados y entrenamiento en curso",
    description="Indica si TensorFlow está disponible, qué granularidades tienen modelo activo (y su versión), "
                "el estado del último entrenamiento y los períodos soportados." + AUTH_DOC.format(scope=SCOPE_READ),
)
def model_status(_: Principal, db: Session = Depends(get_db)):
    with api_errors():
        models = prediction_service.model_overview()
        tf_version = tensorflow_version()
        data = {
            "service": "online", "tensorflow_available": tf_version is not None, "tensorflow_version": tf_version,
            "any_model_trained": any(m["trained"] for m in models), "models": models,
            "training": training_service.status(), "supported_periods": _periods_by_granularity(),
            "history_storage_available": _history_available(db),
        }
    return _ok("Estado del servicio de predicciones", data)


@router.get(
    "/model/metrics", tags=[ML_TAG], response_model=ApiResponse[ModelMetrics],
    responses={**AUTH_ERRORS, 409: _err("No hay modelo entrenado para esa granularidad")},
    summary="Métricas del modelo (preliminares y posteriores)",
    description="Devuelve las métricas PRELIMINARES calculadas sobre el conjunto de prueba al entrenar "
                "(MAE, MSE, RMSE, MAPE, % de acierto aproximado, muestras, pérdidas, diferencias real vs. "
                "predicho) y, si existe, la última evaluación POSTERIOR contra ventas reales."
                + AUTH_DOC.format(scope=SCOPE_READ),
)
def model_metrics(
    _: Principal,
    granularity: GranularityLiteral = Query("monthly", description="Granularidad del modelo"),
    version: int | None = Query(None, ge=1, description="Versión concreta; por defecto la activa"),
    db: Session = Depends(get_db),
):
    with api_errors():
        metadata = model_store.read_metadata(granularity, version)
        posterior = None
        try:
            row = repository.latest_evaluation(db, granularity, "POSTERIOR")
            if row:
                posterior = {"evaluated_at": row.fecha_evaluacion, "model_version": row.modelo_version,
                             "samples": row.muestras, "mae": row.mae, "mse": row.mse, "rmse": row.rmse,
                             "mape_percentage": row.mape, "accuracy_percentage": row.porcentaje_acierto}
        except HistoryUnavailableError:
            posterior = None
        data = {
            "model": model_info(metadata), "preliminary": metadata.get("metricas_preliminares") or {},
            "training": metadata.get("entrenamiento") or {}, "preparation": metadata.get("preparacion") or {},
            "latest_reevaluation": metadata.get("ultima_reevaluacion"), "latest_posterior": posterior,
        }
    return _ok("Métricas del modelo", data)


@router.get(
    "/model/versions", tags=[ML_TAG], response_model=ApiResponse[list[dict]], responses=AUTH_ERRORS,
    summary="Versiones entrenadas del modelo",
    description="Lista las versiones guardadas por granularidad con fecha y métricas preliminares."
                + AUTH_DOC.format(scope=SCOPE_READ),
)
def model_versions(_: Principal, granularity: GranularityLiteral = Query("monthly")):
    with api_errors():
        active = model_store.active_version(granularity)
        items = []
        for number in reversed(model_store.versions(granularity)):
            metadata = model_store.read_metadata(granularity, number)
            metrics = {k: v for k, v in (metadata.get("metricas_preliminares") or {}).items() if k != "comparacion"}
            items.append({"version": f"v{number}", "active": number == active,
                          "trained_at": metadata.get("fecha_entrenamiento"),
                          "trained_by": (metadata.get("entrenado_por") or {}).get("name"),
                          "epochs_run": (metadata.get("entrenamiento") or {}).get("epocas_ejecutadas"),
                          "data_source": (metadata.get("preparacion") or {}).get("fuente_datos"),
                          "preliminary_metrics": metrics})
    return _ok("Versiones del modelo", items)


@router.post(
    "/model/train", tags=[ADMIN_TAG], response_model=ApiResponse[TrainingStatus], status_code=202,
    responses={**AUTH_ERRORS, 200: {"description": "Entrenamiento completado (wait=true)"},
               409: _err("Ya hay un entrenamiento en curso"),
               422: _err("Datos insuficientes o inválidos (incluye el resumen de preparación en error.details)")},
    summary="Entrenar una nueva versión del modelo TensorFlow",
    description="Ejecuta las fases 1-5: extracción desde MySQL, limpieza, variables temporales y rezagadas, "
                "partición cronológica (70/15/15), StandardScaler, red Keras 16-8-1 con EarlyStopping, "
                "métricas preliminares y guardado del modelo y del scaler como nueva versión activa. "
                "Por defecto responde **202** y entrena en segundo plano; consulta el avance con "
                "`GET /model/train/status`. Sólo se permite un entrenamiento simultáneo." + ADMIN_DOC,
)
def train_model(payload: TrainRequest, response: Response, principal: Annotated[dict, ADMIN_ONLY],
                db: Session = Depends(get_db)):
    params = TrainingParams(granularity=payload.granularity, data_source=payload.data_source,
                            epochs=payload.epochs, batch_size=payload.batch_size,
                            learning_rate=payload.learning_rate, patience=payload.patience)
    requested_by = {"user_id": principal.get("user_id"), "name": principal.get("name")}
    with api_errors():
        state = training_service.start(db, params, requested_by, wait=payload.wait)
    if payload.wait:
        response.status_code = 200
        if state["status"] == "failed":
            raise PredictionAPIError(500, "TRAINING_FAILED", state.get("error") or "El entrenamiento falló", state)
        return _ok("Entrenamiento completado", state)
    return _ok("Entrenamiento iniciado", state)


@router.get(
    "/model/train/status", tags=[ADMIN_TAG], response_model=ApiResponse[TrainingStatus], responses=AUTH_ERRORS,
    summary="Estado del entrenamiento (épocas, pérdidas, resultado)",
    description="Estado del último entrenamiento: idle, queued, running, completed o failed, con la pérdida "
                "de entrenamiento y validación por época y el resumen de preparación." + ADMIN_DOC,
)
def training_status(_: Annotated[dict, ADMIN_ONLY]):
    return _ok("Estado del entrenamiento", training_service.status())


@router.post(
    "/model/evaluate", tags=[ADMIN_TAG], response_model=ApiResponse[dict],
    responses={**AUTH_ERRORS, 409: _err("No hay modelo entrenado")},
    summary="Evaluar el modelo activo (preliminar y posterior)",
    description="(1) Reevalúa la versión activa sobre los períodos posteriores a su validación que nunca vio "
                "(métrica PRELIMINAR) y (2) compara las predicciones del historial cuyo período ya terminó con "
                "las ventas reales (métrica POSTERIOR), guardando ambos resultados." + ADMIN_DOC,
)
def evaluate_model(payload: EvaluateRequest, _: Annotated[dict, ADMIN_ONLY], db: Session = Depends(get_db)):
    with api_errors():
        result = prediction_service.evaluate_model(db, payload.granularity, payload.data_source,
                                                   payload.include_posterior)
    return _ok("Evaluación completada", result)


@router.post(
    "/generate", tags=[ML_TAG], response_model=ApiResponse[GeneratedPrediction],
    responses={**AUTH_ERRORS,
               200: {"content": {"application/json": {"example": GENERATE_RESPONSE_EXAMPLE}}},
               409: _err("No hay modelo entrenado para la granularidad solicitada"),
               429: _err("Demasiadas inferencias simultáneas"),
               503: _err("TensorFlow o el almacenamiento no disponibles"),
               504: _err("La inferencia superó el tiempo máximo")},
    summary="Generar una predicción de ventas",
    description="Usa el modelo TensorFlow YA entrenado (nunca entrena en esta petición): recupera modelo y "
                "scaler, toma el histórico real de MySQL, aplica la misma transformación del entrenamiento, "
                "ejecuta la red período a período y devuelve las ventas estimadas, la variación frente al "
                "período anterior, las variables usadas y las métricas del modelo.\n\n"
                "Solicitudes idénticas dentro de la ventana de deduplicación devuelven la predicción ya "
                "registrada (`duplicated: true`). Envía `Idempotency-Key` para controlar reintentos."
                + AUTH_DOC.format(scope=SCOPE_GENERATE),
)
def generate_prediction_v1(
    payload: GeneratePredictionRequest,
    principal: Annotated[dict, GENERATE],
    db: Session = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100,
                                                  description="Clave única por solicitud lógica (reintentos seguros)")] = None,
):
    params = GenerateParams(period=payload.period, prediction_type=payload.prediction_type,
                            granularity=payload.granularity, data_source=payload.data_source,
                            register=payload.save_history, idempotency_key=idempotency_key)
    with api_errors():
        result = prediction_service.generate(db, params, principal)
    message = "Predicción recuperada (solicitud duplicada)" if result["duplicated"] else "Predicción generada correctamente"
    return _ok(message, result)


@router.get(
    "/summary", tags=[ML_TAG], response_model=ApiResponse[PredictionSummary], responses=AUTH_ERRORS,
    summary="Resumen para pantallas de predicciones",
    description="Modelos activos con sus métricas, estado del entrenamiento y últimas predicciones registradas."
                + AUTH_DOC.format(scope=SCOPE_READ),
)
def predictions_summary(_: Principal, db: Session = Depends(get_db),
                        limit: int = Query(5, ge=1, le=50, description="Predicciones recientes a incluir")):
    with api_errors():
        warning, latest, total = None, [], None
        try:
            rows, total = repository.list_predictions(db, 0, limit)
            latest = [history_row_to_dict(row) for row in rows]
        except HistoryUnavailableError as exc:
            warning = str(exc)
        data = {"models": prediction_service.model_overview(), "training": training_service.status(),
                "latest_predictions": latest, "total_predictions": total, "history_warning": warning}
    return _ok("Resumen de predicciones", data)


@router.get(
    "/history", tags=[ML_TAG], response_model=ApiResponse[PaginatedPredictions],
    responses={**AUTH_ERRORS, 503: _err("Tablas de historial no creadas")},
    summary="Historial de predicciones (paginado)",
    description="Predicciones registradas, más recientes primero." + AUTH_DOC.format(scope=SCOPE_READ),
)
def predictions_history(
    _: Principal, db: Session = Depends(get_db),
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
    granularity: GranularityLiteral | None = Query(None),
):
    with api_errors():
        rows, total = repository.list_predictions(db, offset, limit, granularity)
    return _ok("Historial de predicciones", {"items": [history_row_to_dict(r) for r in rows],
                                             "total": total, "offset": offset, "limit": limit})


@router.get(
    "/statistics", tags=[ML_TAG], response_model=ApiResponse[dict],
    responses={**AUTH_ERRORS, 503: _err("Tablas de historial no creadas")},
    summary="Estadísticas del historial de predicciones",
    description="Totales por granularidad y canal (JWT / API_KEY), promedio estimado y error promedio de las "
                "predicciones ya contrastadas con ventas reales." + AUTH_DOC.format(scope=SCOPE_READ),
)
def predictions_statistics(_: Principal, db: Session = Depends(get_db)):
    with api_errors():
        data = repository.statistics(db)
    return _ok("Estadísticas de predicciones", data)


@router.get(
    "/compare", tags=[ML_TAG], response_model=ApiResponse[ComparisonResult],
    responses={**AUTH_ERRORS, 503: _err("Tablas de historial no creadas")},
    summary="Comparar predicciones con ventas reales (métricas posteriores)",
    description="Compara las predicciones registradas cuyo período ya terminó con las ventas reales. "
                "Las que aún no pueden contrastarse se marcan como PENDIENTE. No modifica datos; "
                "para persistir la evaluación usa `POST /model/evaluate`." + AUTH_DOC.format(scope=SCOPE_READ),
)
def compare_predictions(
    _: Principal, db: Session = Depends(get_db),
    granularity: GranularityLiteral | None = Query(None), limit: int = Query(50, ge=1, le=200),
):
    with api_errors():
        data = prediction_service.compare(db, granularity, limit, persist=False)
    return _ok("Comparación con ventas reales", data)


# -- credenciales de servicio ----------------------------------------------------

def _client_dict(row) -> dict:
    return {"client_id": row.cliente_id, "name": row.nombre, "prefix": row.prefijo,
            "scopes": [s for s in row.permisos.split(",") if s], "active": row.activo,
            "created_at": row.fecha_creacion, "last_used_at": row.ultimo_uso}


@router.post(
    "/clients", tags=[ADMIN_TAG], status_code=201, response_model=ApiResponse[ApiClientCreated],
    responses={**AUTH_ERRORS, 503: _err("Tablas ML no creadas")},
    summary="Crear una API Key para una integración externa",
    description="Emite una credencial de servicio (p. ej. para Spring Boot) con permisos `predictions:read` "
                "y/o `predictions:generate`. La clave se devuelve UNA sola vez; sólo se guarda su hash SHA-256. "
                "Las API Keys nunca pueden entrenar modelos." + ADMIN_DOC,
)
def create_api_client(payload: ApiClientCreateRequest, principal: Annotated[dict, ADMIN_ONLY],
                      db: Session = Depends(get_db)):
    with api_errors():
        row, raw_key = repository.create_api_client(db, payload.name, list(payload.scopes), principal.get("user_id"))
    return _ok("API Key creada. Guárdala ahora: no se volverá a mostrar", {**_client_dict(row), "api_key": raw_key})


@router.get(
    "/clients", tags=[ADMIN_TAG], response_model=ApiResponse[list[ApiClientInfo]], responses=AUTH_ERRORS,
    summary="Listar API Keys", description="Lista las credenciales de servicio (sin la clave)." + ADMIN_DOC,
)
def list_api_clients(_: Annotated[dict, ADMIN_ONLY], db: Session = Depends(get_db)):
    with api_errors():
        rows = repository.list_api_clients(db)
    return _ok("Clientes de la API", [_client_dict(r) for r in rows])


@router.delete(
    "/clients/{client_id}", tags=[ADMIN_TAG], response_model=ApiResponse[dict],
    responses={**AUTH_ERRORS, 404: _err("Cliente no encontrado")},
    summary="Revocar una API Key", description="Desactiva la credencial de forma inmediata." + ADMIN_DOC,
)
def revoke_api_client(client_id: int, _: Annotated[dict, ADMIN_ONLY], db: Session = Depends(get_db)):
    with api_errors():
        found = repository.revoke_api_client(db, client_id)
    if not found:
        raise PredictionAPIError(404, "NOT_FOUND", "Cliente no encontrado")
    return _ok("API Key revocada", {"client_id": client_id, "active": False})


# Debe declararse al final para no capturar rutas estáticas (/summary, /history, ...).
@router.get(
    "/{prediction_id}", tags=[ML_TAG], response_model=ApiResponse[PredictionRecord],
    responses={**AUTH_ERRORS, 404: _err("Predicción no encontrada")},
    summary="Consultar una predicción del historial",
    description="Detalle de una predicción registrada, incluida la comparación con ventas reales si ya se evaluó."
                + AUTH_DOC.format(scope=SCOPE_READ),
)
def get_prediction(prediction_id: int, _: Principal, db: Session = Depends(get_db)):
    with api_errors():
        row = repository.get_prediction(db, prediction_id)
    if row is None:
        raise PredictionAPIError(404, "NOT_FOUND", "Predicción no encontrada")
    return _ok("Predicción encontrada", history_row_to_dict(row))
