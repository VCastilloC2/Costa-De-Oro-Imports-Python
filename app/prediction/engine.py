"""Internal sales forecasting pipeline combining scikit-learn and TensorFlow/Keras."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.prediction.data_handler import load_dataset
from app.prediction.model import SalesEnsemble, regression_metrics, train_sales_ensemble


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


def generate_forecast(
    db: Session,
    years: int = 6,
    forecast_months: int = 12,
    today: date | None = None,
    data: pd.DataFrame | None = None,
) -> dict:
    _validate_window(years, forecast_months)
    today = today or date.today()
    data = data if data is not None else load_dataset(db, today)
    if data.empty:
        raise ValueError("No hay compras pagadas suficientes para generar una predicción")

    model = train_sales_ensemble(data)
    real_monthly = data.groupby(["anno", "mes"])["venta_total"].sum()
    start = pd.Timestamp(today.year - years + 1, 1, 1)
    months = pd.date_range(start, periods=years * 12 + forecast_months, freq="MS")
    this_month = pd.Timestamp(today.year, today.month, 1)
    first_real = pd.Timestamp(int(data["anno"].min()), int(data.loc[data["anno"] == data["anno"].min(), "mes"].min()), 1)
    last_real = pd.Timestamp(int(data["anno"].max()), int(data.loc[data["anno"] == data["anno"].max(), "mes"].max()), 1)
    series = []
    for month in months:
        key = (month.year, month.month)
        forecast = round(_monthly_forecast(model, data, month.year, month.month), 2)
        if month < first_real:
            kind, actual = "sin_datos", None
        elif month < this_month and month <= last_real:
            kind, actual = "real", round(float(real_monthly.get(key, 0.0)), 2)
        elif month == this_month and key in real_monthly.index:
            kind, actual = "parcial", round(float(real_monthly[key]), 2)
        else:
            kind, actual = "prediccion", None
        series.append({"fecha": month.strftime("%Y-%m"), "tipo": kind, "real": actual, "prediccion": forecast})

    return {
        "anios": years,
        "proyeccion_meses": forecast_months,
        "serie": series,
        "metricas": {
            "modelo": "ensamble_promedio",
            "modelos": list(SalesEnsemble.model_names),
            "validacion": evaluate(data, today.year),
        },
    }


def forecast_month(db: Session, year: int, month: int, today: date | None = None) -> dict:
    if not 2019 <= year <= 2035:
        raise ValueError("Año fuera del rango válido (2019-2035)")
    if not 1 <= month <= 12:
        raise ValueError("Mes fuera del rango válido (1-12)")
    data = load_dataset(db, today or date.today())
    return predict_month_from_data(data, year, month)


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
