"""Pronóstico de ventas.

* ``generate_forecast`` / ``forecast_month`` (gráfica de Spring y /admin/prediccion): serie temporal
  mensual con Holt-Winters amortiguado (``timeseries.py``), que sigue la tendencia reciente.
* ``predict_month_from_data`` / ``evaluate`` (endpoint /api/v1/predictions/demand): ensamble
  scikit-learn + TensorFlow/Keras por compra, sin cambios.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging

import numpy as np
import pandas as pd
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.prediction.artifacts import ModelNotTrainedError, model_store
from app.prediction.data_handler import load_dataset
from app.models import Compra
from app.prediction.model import SalesEnsemble, regression_metrics, train_sales_ensemble
from app.prediction.preparation import (
    GRANULARITIES, TARGET, aggregate_by_period, build_features, build_history_series,
    clean_transactions, history_signature, load_transactions,
)
from app.prediction.prediction_service import prediction_service
from app.prediction.timeseries import METHOD_NAME, backtest, fit_holt_winters, monthly_totals

logger = logging.getLogger(__name__)


def _validate_window(years: int, forecast_months: int) -> None:
    if not 1 <= years <= 10:
        raise ValueError("anios debe estar entre 1 y 10")
    if not 0 <= forecast_months <= 24:
        raise ValueError("proyeccion_meses debe estar entre 0 y 24")


def _monthly_forecast(model: SalesEnsemble, data: pd.DataFrame, year: int, month: int) -> float:
    historical = data[data["mes"] == month]
    if historical.empty:
        return 0.0
    years_with_data = max(int(historical["anno"].nunique()), 1)
    target = historical.assign(anno=year)
    return max(float(model.predict(target).sum() / years_with_data), 0.0)


def evaluate(data: pd.DataFrame, current_year: int) -> dict | None:
    years = sorted(int(value) for value in data["anno"].unique() if int(value) < current_year)
    if len(years) < 2:
        return None
    test_year = years[-1]
    train, test = data[data["anno"] < test_year], data[data["anno"] == test_year]
    if train.empty or test.empty:
        return None
    model = train_sales_ensemble(train)
    return {"anio_prueba": test_year, **regression_metrics(test["venta_total"], model.predict(test))}


def _history(data: pd.DataFrame, today: date) -> pd.Series:
    """Serie mensual de meses CERRADOS: el mes en curso está incompleto y sesgaría la tendencia."""
    if data.empty:
        raise ValueError("No hay compras pagadas suficientes para generar una predicción")
    last_closed = pd.Period(year=today.year, month=today.month, freq="M") - 1
    last_with_data = pd.Period(year=int(data["anno"].max()),
                               month=int(data.loc[data["anno"] == data["anno"].max(), "mes"].max()), freq="M")
    history = monthly_totals(data, min(last_closed, last_with_data))
    if history.empty:
        raise ValueError("No hay meses cerrados con ventas para generar una predicción")
    return history


def _monthly_paid_sales(db: Session, today: date) -> pd.DataFrame:
    """Aggregate paid revenue directly from compra; detail rows are not required for revenue."""
    query = (
        select(
            extract("year", Compra.fecha).label("anno"),
            extract("month", Compra.fecha).label("mes"),
            func.sum(Compra.total).label("venta_total"),
        )
        .where(Compra.estado == "PAGADO", Compra.fecha.is_not(None), Compra.total > 0,
               Compra.fecha < today + timedelta(days=1))
        .group_by(extract("year", Compra.fecha), extract("month", Compra.fecha))
        .order_by(extract("year", Compra.fecha), extract("month", Compra.fecha))
    )
    rows = db.execute(query).all()
    if not rows:
        raise ValueError("MySQL no tiene compras PAGADO con fecha y total válidos para el pronóstico")
    return pd.DataFrame([{"anno": int(row.anno), "mes": int(row.mes),
                          "venta_total": float(row.venta_total)} for row in rows])


def _forecast_with_trained_tensorflow(db: Session, today: date, years: int, forecast_months: int,
                                     data_source: str) -> dict | None:
    """Use the active monthly TensorFlow model when one was trained from the current DB data."""
    version = model_store.active_version("monthly")
    if not version:
        return None
    loaded = model_store.load("monthly", version)
    extraction = load_transactions(db, data_source)
    reference = datetime.combine(today, time.min)
    cfg = GRANULARITIES["monthly"]
    bounds = tuple(loaded.metadata["limites_atipicos"]) if loaded.metadata.get("limites_atipicos") else None
    history = build_history_series(extraction, "monthly", bounds, reference)
    if len(history) < cfg.warmup:
        raise ValueError(f"El modelo TensorFlow requiere {cfg.warmup} meses completos; MySQL solo entrega {len(history)}")
    trained_signature = loaded.metadata.get("firma_serie")
    if not trained_signature or trained_signature != history_signature(history):
        raise ModelNotTrainedError(
            "El modelo TensorFlow activo no coincide con las ventas pagadas actuales de MySQL; "
            "se usa el pronóstico estadístico actualizado hasta reentrenar con data_source=database"
        )
    origin = pd.Period(loaded.metadata["origen_serie"], freq=cfg.period_freq)
    features = build_features(history, cfg, origin)
    ready = features.iloc[cfg.warmup:]
    fitted_values = loaded.predict(ready) if not ready.empty else np.array([], dtype=float)
    fitted = dict(zip(ready["periodo"], fitted_values))

    # Extract raw actuals separately so chart values are never clipped by training's outlier policy.
    clean, _ = clean_transactions(extraction.transactions, reference)
    raw_series = aggregate_by_period(clean, cfg, reference, drop_incomplete=True)
    actuals = dict(zip(raw_series["periodo"], raw_series[TARGET].astype(float)))
    partial_actuals = clean.groupby(clean["fecha"].dt.to_period("M"))["venta_total"].sum().to_dict()

    steps = max(1, forecast_months)
    future_result = prediction_service.forecast(loaded, extraction, steps, reference)
    future = {
        pd.Period(item["period_start"], freq="M"): float(item["predicted_sales"])
        for item in future_result["breakdown"]
    }
    last_history = history["periodo"].iloc[-1]
    start = pd.Period(year=today.year - years + 1, month=1, freq="M")
    months = pd.period_range(start, periods=years * 12 + forecast_months, freq="M")
    this_month = pd.Period(year=today.year, month=today.month, freq="M")
    series = []
    for period in months:
        if period < history["periodo"].iloc[0]:
            kind, actual, predicted = "sin_datos", None, None
        elif period <= last_history:
            kind, actual = "real", round(float(actuals.get(period, 0.0)), 2)
            predicted = round(float(fitted[period]), 2) if period in fitted else None
        elif period == this_month and period in partial_actuals:
            kind, actual = "parcial", round(float(partial_actuals[period]), 2)
            predicted = round(float(future[period]), 2) if period in future else None
        elif period in future:
            kind, actual, predicted = "prediccion", None, round(float(future[period]), 2)
        else:
            kind, actual, predicted = "sin_datos", None, None
        series.append({"fecha": period.strftime("%Y-%m"), "tipo": kind,
                       "real": actual, "prediccion": predicted})

    metrics = loaded.metadata.get("metricas_preliminares") or {}
    comparisons = metrics.get("comparacion") or []
    return {
        "anios": years,
        "proyeccion_meses": forecast_months,
        "serie": series,
        "historial_datos": future_result["history"],
        "metricas": {
            "modelo": "tensorflow_keras",
            "version_modelo": loaded.metadata.get("version_etiqueta"),
            "modelos": ["tensorflow_keras"],
            "meses_historia": len(history),
            "validacion": {
                "tipo_validacion": "holdout_temporal_entrenamiento",
                "desde": comparisons[0].get("fecha") if comparisons else None,
                "hasta": comparisons[-1].get("fecha") if comparisons else None,
                "mae": metrics.get("mae"),
                "mse": metrics.get("mse"),
                "wape": metrics.get("wape_percentage"),
                "error_porcentual": metrics.get("wape_percentage"),
                "porcentaje_prediccion": metrics.get("accuracy_percentage"),
                "muestras": metrics.get("samples", 0),
                "fuente_datos": extraction.source,
                "ultima_venta_mes": str(last_history),
            },
        },
    }


def generate_forecast(
    db: Session,
    years: int = 6,
    forecast_months: int = 12,
    today: date | None = None,
    data: pd.DataFrame | None = None,
    data_source: str | None = None,
) -> dict:
    """Serie mensual para la gráfica: ventas reales, ajuste del modelo y proyección.

    * ``real``: meses cerrados con su venta real y, en ``prediccion``, el pronóstico a un paso
      (lo que el modelo habría dicho ese mes con los datos anteriores: sirve para medir el error).
    * ``parcial``: mes en curso (venta real incompleta) y su pronóstico.
    * ``prediccion``: meses futuros proyectados.
    * ``sin_datos``: meses anteriores al primer registro (``prediccion`` = None).
    """
    _validate_window(years, forecast_months)
    today = today or date.today()
    source = (data_source or settings.prediction_data_source).strip().lower()
    if source not in {"database", "db", "mysql", "postgresql", "csv"}:
        raise ValueError("data_source debe ser database o csv")
    model_fallback_note = None
    if data is None:
        try:
            neural_result = _forecast_with_trained_tensorflow(db, today, years, forecast_months, source)
            if neural_result is not None:
                return neural_result
        except ModelNotTrainedError as exc:
            logger.info("No se usa el modelo TensorFlow activo: %s", exc)
            model_fallback_note = str(exc)
        except Exception:
            logger.exception("No se pudo usar el modelo TensorFlow mensual; se utilizará el pronóstico estadístico")
            model_fallback_note = "El modelo TensorFlow no coincidía con la fuente actual; el pronóstico se calculó con el histórico MySQL."
    if data is None:
        data = (load_dataset(db, today) if source == "csv"
                else _monthly_paid_sales(db, today))
    history = _history(data, today)
    model = fit_holt_winters(history)
    validation = backtest(history)
    use_seasonal_baseline = bool(validation and validation.get("modelo_elegido", "").startswith("naive_estacional"))

    start = pd.Period(year=today.year - years + 1, month=1, freq="M")
    months = pd.period_range(start, periods=years * 12 + forecast_months, freq="M")
    this_month = pd.Period(year=today.year, month=today.month, freq="M")
    last_hist = history.index[-1]
    horizon = max(0, months[-1].ordinal - last_hist.ordinal)
    future = (np.resize(history.iloc[-12:].to_numpy(dtype=float), horizon)
              if use_seasonal_baseline and horizon else model.forecast(horizon))
    fitted = pd.Series(model.fitted, index=history.index)
    if use_seasonal_baseline:
        seasonal_fitted = history.shift(12)
        fitted.loc[seasonal_fitted.notna()] = seasonal_fitted.loc[seasonal_fitted.notna()]
    real_monthly = data.groupby(["anno", "mes"])["venta_total"].sum()

    series = []
    for month in months:
        key = (month.year, month.month)
        if month < history.index[0]:
            kind, actual, pred = "sin_datos", None, None
        elif month <= last_hist:
            kind, actual, pred = "real", float(history[month]), float(fitted[month])
        else:
            pred = float(future[month.ordinal - last_hist.ordinal - 1])
            if month == this_month and key in real_monthly.index:
                kind, actual = "parcial", float(real_monthly[key])
            else:
                kind, actual = "prediccion", None
        series.append({
            "fecha": month.strftime("%Y-%m"),
            "tipo": kind,
            "real": None if actual is None else round(actual, 2),
            "prediccion": None if pred is None else round(pred, 2),
        })

    return {
        "anios": years,
        "proyeccion_meses": forecast_months,
        "serie": series,
        "historial_datos": {
            "fuente": "csv" if source == "csv" else "database",
            "ultima_venta_mes": str(history.index[-1]),
            "meses_completos": len(history),
        },
        "advertencia_modelo": model_fallback_note,
        "metricas": {
            "modelo": validation.get("modelo_elegido") if validation else METHOD_NAME,
            "modelos": [f"{METHOD_NAME}_rolling", "naive_estacional_rolling"],
            "parametros": model.params if not use_seasonal_baseline else {"referencia_meses": 12},
            "meses_historia": len(history),
            "validacion": validation,
        },
    }


def forecast_month(db: Session, year: int, month: int, today: date | None = None,
                   data: pd.DataFrame | None = None) -> dict:
    """Venta prevista para un mes: ajuste del modelo si ya pasó, proyección si es futuro."""
    if not 2019 <= year <= 2035:
        raise ValueError("Año fuera del rango válido (2019-2035)")
    if not 1 <= month <= 12:
        raise ValueError("Mes fuera del rango válido (1-12)")
    today = today or date.today()
    if data is None:
        data = (load_dataset(db, today) if settings.prediction_data_source.strip().lower() == "csv"
                else _monthly_paid_sales(db, today))
    history = _history(data, today)
    model = fit_holt_winters(history)
    validation = backtest(history)
    use_seasonal_baseline = bool(validation and validation.get("modelo_elegido", "").startswith("naive_estacional"))
    target = pd.Period(year=year, month=month, freq="M")
    if target < history.index[0]:
        raise ValueError(f"No hay datos de ventas antes de {history.index[0]}")
    if target <= history.index[-1]:
        baseline_period = target - 12
        value = (float(history[baseline_period]) if use_seasonal_baseline and baseline_period in history.index
                 else float(model.fitted[target.ordinal - history.index[0].ordinal]))
    else:
        horizon = target.ordinal - history.index[-1].ordinal
        value = (float(np.resize(history.iloc[-12:].to_numpy(dtype=float), horizon)[-1])
                 if use_seasonal_baseline else float(model.forecast(horizon)[-1]))
    return {"anno": year, "mes": month, "prediccion": round(value, 2)}


def predict_month_from_data(data: pd.DataFrame, year: int, month: int) -> dict:
    """Predict a month from an already loaded dataset to share work with metadata."""
    if not 2019 <= year <= 2035:
        raise ValueError("Año fuera del rango válido (2019-2035)")
    if not 1 <= month <= 12:
        raise ValueError("Mes fuera del rango válido (1-12)")
    if data.empty:
        raise ValueError("No hay compras pagadas suficientes para generar una predicción")
    model = train_sales_ensemble(data)
    return {"anno": year, "mes": month, "prediccion": round(_monthly_forecast(model, data, year, month), 2)}
