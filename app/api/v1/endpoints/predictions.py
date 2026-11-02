"""Publicly documented prediction API (ADMIN authentication required)."""
from datetime import date, datetime, timezone
from importlib.metadata import version
import logging
import math
import platform

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import admin_user
from app.core.database import get_db
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
    summary="Estimar ventas mensuales con metadata y métricas del modelo",
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
        logger.exception("El pipeline de predicción no está disponible")
        raise HTTPException(status_code=503, detail="El motor predictivo no está disponible") from exc
    except Exception as exc:
        logger.exception("Falló la inferencia de ventas")
        raise HTTPException(status_code=503, detail="No se pudo completar la predicción") from exc

    try:
        validation = evaluate(dataset, today.year)
    except Exception:
        logger.exception("No se pudo calcular la validación del modelo")
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
            "Ensamble promedio: Regresión Lineal (Scikit-Learn) + "
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
            f"validación temporal sobre {metrics.sample_count} observaciones"
            if validation
            else "Sin suficientes años históricos para validar fuera de muestra; confianza no estimable"
        ),
        metrics=metrics,
        generated_at=datetime.now(timezone.utc),
    )
