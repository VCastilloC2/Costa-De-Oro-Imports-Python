"""Pronóstico de ventas.

* ``generate_forecast`` / ``forecast_month`` (gráfica de Spring y /admin/prediccion): serie temporal
  mensual con Holt-Winters amortiguado (``timeseries.py``), que sigue la tendencia reciente.
* ``predict_month_from_data`` / ``evaluate`` (endpoint /api/v1/predictions/demand): ensamble
  scikit-learn + TensorFlow/Keras por compra, sin cambios.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.prediction.data_handler import load_dataset
from app.prediction.model import SalesEnsemble, regression_metrics, train_sales_ensemble
from app.prediction.timeseries import METHOD_NAME, backtest, fit_holt_winters, monthly_totals


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


def generate_forecast(
    db: Session,
    years: int = 6,
    forecast_months: int = 12,
    today: date | None = None,
    data: pd.DataFrame | None = None,
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
    data = data if data is not None else load_dataset(db, today)
    history = _history(data, today)
    model = fit_holt_winters(history)

    start = pd.Period(year=today.year - years + 1, month=1, freq="M")
    months = pd.period_range(start, periods=years * 12 + forecast_months, freq="M")
    this_month = pd.Period(year=today.year, month=today.month, freq="M")
    last_hist = history.index[-1]
    horizon = max(0, months[-1].ordinal - last_hist.ordinal)
    future = model.forecast(horizon)
    fitted = pd.Series(model.fitted, index=history.index)
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
        "metricas": {
            "modelo": METHOD_NAME,
            "modelos": [METHOD_NAME],
            "parametros": model.params,
            "meses_historia": len(history),
            "validacion": backtest(history),
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
    data = data if data is not None else load_dataset(db, today)
    history = _history(data, today)
    model = fit_holt_winters(history)
    target = pd.Period(year=year, month=month, freq="M")
    if target < history.index[0]:
        raise ValueError(f"No hay datos de ventas antes de {history.index[0]}")
    if target <= history.index[-1]:
        value = float(model.fitted[target.ordinal - history.index[0].ordinal])
    else:
        value = float(model.forecast(target.ordinal - history.index[-1].ordinal)[-1])
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
