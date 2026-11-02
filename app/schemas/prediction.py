from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ForecastRequest(BaseModel):
    anios: int = Field(default=6, ge=1, le=10)
    proyeccion_meses: int = Field(default=12, ge=0, le=24)


class DemandPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_year: int | None = Field(default=None, ge=2019, le=2035)
    target_month: int | None = Field(default=None, ge=1, le=12)


class DemandPredictionMetrics(BaseModel):
    validation_year: int | None = None
    mean_absolute_error: float | None = None
    root_mean_squared_error: float | None = None
    mape_percentage: float | None = None
    r_squared: float | None = None
    sample_count: int = 0


class DemandPredictionResponse(BaseModel):
    predicted_variable: str
    prediction_value: float
    confidence_percentage: float = Field(ge=0, le=100)
    error_margin_percentage: float = Field(ge=0)
    algorithm_name: str
    model_version: str
    tools_used: list[str]
    target_period: str
    confidence_basis: str
    metrics: DemandPredictionMetrics
    generated_at: datetime
