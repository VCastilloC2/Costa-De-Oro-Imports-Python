"""Contratos JSON de la API REST de predicciones (/api/v1/predictions).

Todas las respuestas usan el sobre ``{"success": bool, "message": str, "data": ...}`` y los errores
``{"success": false, "message": str, "error": {"code": str, "details": ...}}``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

PeriodLiteral = Literal[
    "7_days", "14_days", "30_days", "4_weeks", "8_weeks", "12_weeks",
    "1_month", "3_months", "6_months", "12_months",
]
GranularityLiteral = Literal["daily", "weekly", "monthly"]
DataSourceLiteral = Literal["auto", "database", "csv"]
ScopeLiteral = Literal["predictions:read", "predictions:generate"]


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str
    data: T | None = None


class ErrorDetail(BaseModel):
    code: str = Field(description="Código estable para manejo programático del error")
    details: Any | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "success": False, "message": "No hay un modelo entrenado para la granularidad 'daily'",
        "error": {"code": "MODEL_NOT_TRAINED", "details": None}}})
    success: bool = False
    message: str
    error: ErrorDetail


# --------------------------------------------------------------------------- generación

class GeneratePredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"period": "7_days", "prediction_type": "sales", "granularity": "daily"},
        {"period": "3_months", "prediction_type": "sales", "granularity": "monthly"},
    ]})
    period: PeriodLiteral = Field(description=(
        "Horizonte a predecir. daily: 7_days, 14_days, 30_days · weekly: 4_weeks, 8_weeks, 12_weeks · "
        "monthly: 1_month, 3_months, 6_months, 12_months"))
    prediction_type: Literal["sales"] = Field("sales", description="Variable a predecir (ventas en COP)")
    granularity: GranularityLiteral | None = Field(
        None, description="Opcional; si se envía debe coincidir con la unidad del período")
    data_source: DataSourceLiteral = Field(
        "auto", description="Origen del histórico: auto (MySQL con respaldo CSV), database o csv")
    save_history: bool = Field(True, description="Registrar la predicción en el historial")


class ModelInfo(BaseModel):
    name: str | None
    version: str
    version_number: int | None = None
    granularity: str | None = None
    trained_at: str | None = None
    framework: str | None = None
    architecture: list[dict[str, Any]] | None = None
    features: list[str] | None = None
    target: str | None = None


class BreakdownItem(BaseModel):
    period_start: date
    period_end: date
    predicted_sales: float


class Forecast(BaseModel):
    period: str | None
    prediction_type: str = "sales"
    granularity: str | None
    start_date: str
    end_date: str
    predicted_sales: float = Field(description="Ventas estimadas totales del horizonte (COP)")
    currency: str = "COP"
    previous_period_sales: float | None = Field(
        None, description="Ventas reales del período anterior de igual duración")
    variation_percentage: float | None = Field(
        None, description="(estimado - anterior) / anterior * 100; null si el anterior es 0")
    breakdown: list[BreakdownItem] = []


class Performance(BaseModel):
    metric_type: str = Field("PRELIMINAR", description="PRELIMINAR = conjunto de prueba al entrenar")
    evaluation_set: str | None = None
    mae: float | None = None
    mse: float | None = None
    rmse: float | None = None
    mape_percentage: float | None = None
    wape_percentage: float | None = None
    accuracy_percentage: float | None = None
    accuracy_basis: str | None = None
    evaluated_samples: int | None = None
    train_loss: float | None = None
    validation_loss: float | None = None
    evaluated_at: str | None = None


class PredictionVariable(BaseModel):
    name: str
    value: float
    description: str


class GeneratedPrediction(BaseModel):
    prediction_id: int | None = Field(None, description="null si no se registró en el historial")
    duplicated: bool = Field(False, description="true si se devolvió una predicción idéntica reciente")
    registered: bool = False
    model: ModelInfo
    forecast: Forecast
    performance: Performance
    prediction_variables: list[PredictionVariable] = []
    history: dict[str, Any] | None = None
    generated_at: datetime
    warnings: list[str] | None = None


GENERATE_RESPONSE_EXAMPLE = {
    "success": True,
    "message": "Predicción generada correctamente",
    "data": {
        "prediction_id": 25, "duplicated": False, "registered": True,
        "model": {"name": "TensorFlow Sales Prediction", "version": "v1", "version_number": 1,
                  "granularity": "daily", "trained_at": "2026-11-07T00:00:00", "framework": "TensorFlow 2.21.0"},
        "forecast": {"period": "7_days", "prediction_type": "sales", "granularity": "daily",
                     "start_date": "2026-11-07", "end_date": "2026-11-13", "predicted_sales": 0.0,
                     "currency": "COP", "previous_period_sales": 0.0, "variation_percentage": None,
                     "breakdown": [{"period_start": "2026-11-07", "period_end": "2026-11-07", "predicted_sales": 0.0}]},
        "performance": {"metric_type": "PRELIMINAR", "mae": None, "mse": None, "rmse": None,
                        "mape_percentage": None, "accuracy_percentage": None, "evaluated_samples": 0},
        "prediction_variables": [{"name": "ventas_lag_1", "value": 0.0, "description": "Ventas de hace 1 período(s) (rezago)"}],
        "generated_at": "2026-11-07T00:00:00",
    },
}


# --------------------------------------------------------------------------- historial

class PredictionRecord(BaseModel):
    prediction_id: int
    generated_at: datetime
    model_version: str
    granularity: str
    period: str
    prediction_type: str
    start_date: date
    end_date: date
    predicted_sales: float
    previous_period_sales: float | None
    variation_percentage: float | None
    currency: str = "COP"
    breakdown: list[dict[str, Any]] = []
    prediction_variables: list[dict[str, Any]] = []
    channel: str
    requested_by: str | None
    real_sales: float | None = Field(None, description="Ventas reales ocurridas (métrica posterior)")
    error_percentage: float | None = None
    evaluated_at: datetime | None = None


class PaginatedPredictions(BaseModel):
    items: list[PredictionRecord]
    total: int
    offset: int
    limit: int


class ComparisonItem(BaseModel):
    prediction_id: int
    granularity: str
    period: str
    start_date: date
    end_date: date
    model_version: str
    predicted_sales: float
    real_sales: float | None
    difference: float | None
    error_percentage: float | None
    status: Literal["EVALUADA", "PENDIENTE"]


class MetricsReport(BaseModel):
    mae: float | None = None
    mse: float | None = None
    rmse: float | None = None
    mape_percentage: float | None = None
    wape_percentage: float | None = None
    accuracy_percentage: float | None = None
    samples: int = 0
    mape_samples: int = 0


class ComparisonResult(BaseModel):
    metric_type: Literal["POSTERIOR"] = "POSTERIOR"
    description: str
    evaluated: int
    pending: int
    metrics: MetricsReport
    items: list[ComparisonItem]


# --------------------------------------------------------------------------- modelo

class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"granularity": "monthly", "epochs": 300, "batch_size": 16, "learning_rate": 0.001, "patience": 25},
        {"granularity": "daily", "data_source": "database", "wait": False},
    ]})
    granularity: GranularityLiteral = "monthly"
    data_source: DataSourceLiteral = "auto"
    epochs: int = Field(300, ge=10, le=5000)
    batch_size: int = Field(16, ge=1, le=1024)
    learning_rate: float = Field(0.001, gt=0, le=1)
    patience: int = Field(25, ge=1, le=500, description="Épocas sin mejora antes de EarlyStopping")
    wait: bool = Field(False, description=(
        "false: responde 202 y entrena en segundo plano · true: espera a que termine "
        "(útil en despliegues serverless sin hilos persistentes)"))


class EpochLog(BaseModel):
    model_config = ConfigDict(extra="allow")
    epoch: int
    loss: float | None = None
    val_loss: float | None = None
    mean_absolute_error: float | None = None
    val_mean_absolute_error: float | None = None


class TrainingStatus(BaseModel):
    status: Literal["idle", "queued", "running", "completed", "failed"]
    job_id: str | None = None
    granularity: str | None = None
    params: dict[str, Any] | None = None
    requested_by: dict[str, Any] | None = None
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    current_epoch: int | None = None
    max_epochs: int | None = None
    epochs: list[EpochLog] = []
    model_version: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    preparation: dict[str, Any] | None = Field(None, description="Resumen de la FASE 1")


class GranularityModelStatus(BaseModel):
    granularity: str
    trained: bool
    active_version: str | None = None
    available_versions: list[str] = []
    trained_at: str | None = None
    performance: Performance | None = None


class ModelStatus(BaseModel):
    service: str = "online"
    tensorflow_available: bool
    tensorflow_version: str | None
    any_model_trained: bool
    models: list[GranularityModelStatus]
    training: TrainingStatus
    supported_periods: dict[str, list[str]]
    history_storage_available: bool


class ModelMetrics(BaseModel):
    model: ModelInfo
    preliminary: dict[str, Any] = Field(description="Métricas sobre el conjunto de prueba al entrenar")
    training: dict[str, Any] = Field(description="Épocas, pérdidas y configuración del entrenamiento")
    preparation: dict[str, Any] = Field(description="Resumen de la preparación de datos (FASE 1)")
    latest_reevaluation: dict[str, Any] | None = None
    latest_posterior: dict[str, Any] | None = Field(
        None, description="Última evaluación contra ventas reales posteriores (POSTERIOR)")


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    granularity: GranularityLiteral = "monthly"
    data_source: DataSourceLiteral = "auto"
    include_posterior: bool = True


class PredictionSummary(BaseModel):
    models: list[GranularityModelStatus]
    training: TrainingStatus
    latest_predictions: list[PredictionRecord]
    total_predictions: int | None
    history_warning: str | None = None


# --------------------------------------------------------------------------- clientes API

class ApiClientCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "name": "erp-spring-boot", "scopes": ["predictions:read", "predictions:generate"]}})
    name: str = Field(min_length=3, max_length=120)
    scopes: list[ScopeLiteral] = Field(min_length=1)


class ApiClientInfo(BaseModel):
    client_id: int
    name: str
    prefix: str
    scopes: list[str]
    active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ApiClientCreated(ApiClientInfo):
    api_key: str = Field(description="Clave en claro. Se muestra UNA sola vez; guárdala en un gestor de secretos")
