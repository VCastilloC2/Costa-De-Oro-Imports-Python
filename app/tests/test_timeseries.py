"""Modelo de serie temporal (Holt-Winters amortiguado) usado por la gráfica de predicciones."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.prediction.engine import forecast_month, generate_forecast
from app.prediction.timeseries import backtest, fit_holt_winters, monthly_totals, seasonal_indices

ESTACION = np.array([0.9, 0.85, 1.0, 1.0, 1.05, 1.0, 0.95, 0.95, 1.0, 1.05, 1.1, 1.25])


def _filas(niveles: dict[tuple[int, int], float]) -> pd.DataFrame:
    """Una compra por mes con el total indicado (el modelo trabaja con totales mensuales)."""
    return pd.DataFrame([{"venta_total": v, "anno": a, "mes": m} for (a, m), v in niveles.items()])


def _serie(meses: int, inicio=(2020, 1), nivel=100.0, pendiente=0.0, ruido=0.0, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periodo = pd.Period(year=inicio[0], month=inicio[1], freq="M")
    datos = {}
    for i in range(meses):
        p = periodo + i
        valor = (nivel + pendiente * i) * ESTACION[p.month - 1] * (1 + rng.normal(0, ruido))
        datos[(p.year, p.month)] = max(valor, 1.0)
    return _filas(datos)


def test_monthly_totals_rellena_meses_sin_ventas():
    data = _filas({(2024, 1): 10.0, (2024, 3): 30.0})
    y = monthly_totals(data, pd.Period("2024-04", freq="M"))
    assert list(y.index.astype(str)) == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert y.tolist() == [10.0, 0.0, 30.0, 0.0]


def test_estacionalidad_se_recupera_y_tiene_media_1():
    data = _serie(48)
    y = monthly_totals(data, pd.Period("2023-12", freq="M"))
    idx = seasonal_indices(y)
    assert idx.mean() == pytest.approx(1.0)
    assert np.argmax(idx) == 11 and np.argmin(idx) == 1   # diciembre el más alto, febrero el más bajo


def test_sigue_la_tendencia_creciente():
    data = _serie(48, nivel=100, pendiente=5)
    y = monthly_totals(data, pd.Period("2023-12", freq="M"))
    fc = fit_holt_winters(y).forecast(12)
    # Desestacionalizado, el último año real ronda 100 + 5*42 = 310; un promedio histórico daría ~220.
    assert (fc / ESTACION).mean() > 290


def test_sigue_una_caida_reciente_en_vez_de_volver_al_promedio():
    niveles = {}
    for i, p in enumerate(pd.period_range("2021-01", "2026-10", freq="M")):
        base = 12e6 if p < pd.Period("2025-09", freq="M") else 2e6
        niveles[(p.year, p.month)] = base * ESTACION[p.month - 1]
    out = generate_forecast(None, years=6, forecast_months=12, today=date(2026, 11, 10), data=_filas(niveles))
    futuros = [p["prediccion"] for p in out["serie"] if p["tipo"] == "prediccion"]
    assert len(futuros) == 14                                 # nov-dic 2026 + 12 meses
    assert max(futuros) < 5e6                                 # el método anterior proyectaba ~12M


def test_proyeccion_nunca_negativa_ni_explota():
    data = _serie(36, nivel=100, pendiente=-3)                # cae hasta casi 0
    y = monthly_totals(data, pd.Period("2022-12", freq="M"))
    fc = fit_holt_winters(y).forecast(24)
    assert (fc >= 0).all()
    assert fc.max() < y.max() * 2


def test_backtest_mejora_al_metodo_ingenuo_con_tendencia():
    data = _serie(60, nivel=100, pendiente=4, ruido=0.03)
    y = monthly_totals(data, pd.Period("2024-12", freq="M"))
    bt = backtest(y)
    assert bt["meses"] == 12 and bt["desde"] == "2024-01"
    assert bt["wape"] < bt["wape_ingenuo_estacional"]


def test_backtest_requiere_tres_anios():
    y = monthly_totals(_serie(24), pd.Period("2021-12", freq="M"))
    assert backtest(y) is None


def test_generate_forecast_tipos_y_mes_en_curso_excluido():
    data = _serie(35, inicio=(2023, 1))                       # ene-2023 .. nov-2025 (nov = mes en curso)
    out = generate_forecast(None, years=3, forecast_months=6, today=date(2025, 11, 15), data=data)
    tipos = {p["fecha"]: p["tipo"] for p in out["serie"]}
    assert tipos["2025-10"] == "real"
    assert tipos["2025-11"] == "parcial"                      # no entra al entrenamiento
    assert tipos["2026-05"] == "prediccion"
    assert len(out["serie"]) == 3 * 12 + 6
    assert out["metricas"]["meses_historia"] == 34


def test_meses_antes_del_primer_dato_no_tienen_prediccion():
    data = _serie(20, inicio=(2024, 6))
    out = generate_forecast(None, years=3, forecast_months=0, today=date(2026, 3, 1), data=data)
    primero = out["serie"][0]
    assert primero["fecha"] == "2024-01" and primero["tipo"] == "sin_datos" and primero["prediccion"] is None


def test_forecast_month_pasado_y_futuro():
    data = _serie(36)
    pasado = forecast_month(None, 2022, 6, today=date(2023, 1, 10), data=data)
    futuro = forecast_month(None, 2023, 12, today=date(2023, 1, 10), data=data)
    assert pasado["prediccion"] > 0 and futuro["prediccion"] > 0
    with pytest.raises(ValueError, match="No hay datos"):
        forecast_month(None, 2019, 1, today=date(2023, 1, 10), data=data)
