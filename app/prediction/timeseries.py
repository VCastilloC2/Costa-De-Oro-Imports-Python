"""Pronóstico mensual de ventas con Holt-Winters multiplicativo y tendencia amortiguada.

Por qué este modelo y no el promedio por mes que se usaba antes:

* El promedio de "todos los eneros" da una línea casi plana: ignora si las ventas vienen
  subiendo o cayendo. Aquí el **nivel** y la **tendencia** se actualizan mes a mes, de modo
  que la proyección parte de las ventas recientes.
* La **estacionalidad** (qué meses venden más) se estima aparte, como un índice por mes del
  calendario, y se aplica de forma multiplicativa.
* La tendencia está **amortiguada** (phi < 1): a largo plazo se aplana en lugar de crecer o
  caer sin límite, que es lo razonable para proyecciones de 1-2 años.
* Los parámetros (alpha, beta, phi) se eligen minimizando el error de pronóstico a un paso,
  y la calidad se mide con un **backtest**: se entrena sin los últimos 12 meses cerrados y se
  comparan esos 12 meses con lo que el modelo habría predicho.

Solo depende de numpy/pandas: no necesita TensorFlow y tarda milisegundos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd

METHOD_NAME = "holt_winters_amortiguado"
SEASON = 12
MIN_MONTHS_SEASONAL = 2 * SEASON  # con menos de 2 años no se puede estimar la estacionalidad
BACKTEST_MONTHS = 12
MIN_MONTHS_BACKTEST = 3 * SEASON

_ALPHAS = np.round(np.arange(0.1, 1.0, 0.1), 2)
# beta y phi acotados: una tendencia muy reactiva o poco amortiguada sobrerreacciona a un par de
# meses atípicos y puede llevar la proyección a 0 (o dispararla) durante años.
_BETAS = (0.0, 0.05, 0.1, 0.2)
_PHIS = (0.8, 0.85, 0.9, 0.95)


def monthly_totals(data: pd.DataFrame, last_month: pd.Period) -> pd.Series:
    """Ventas totales por mes (PeriodIndex mensual) desde el primer mes con datos hasta ``last_month``.

    Los meses intermedios sin ventas quedan en 0 (no se saltan: el modelo necesita una serie continua).
    """
    if data.empty:
        return pd.Series(dtype=float)
    grouped = data.groupby(["anno", "mes"])["venta_total"].sum()
    periods = pd.PeriodIndex(
        [pd.Period(year=int(a), month=int(m), freq="M") for a, m in grouped.index], freq="M")
    totals = pd.Series(grouped.to_numpy(dtype=float), index=periods).groupby(level=0).sum()
    totals = totals[totals.index <= last_month]
    if totals.empty:
        return totals
    full = pd.period_range(totals.index.min(), last_month, freq="M")
    return totals.reindex(full, fill_value=0.0)


def seasonal_indices(y: pd.Series) -> np.ndarray:
    """Índice estacional multiplicativo por mes del calendario (posición 0 = enero), media 1.

    Descomposición clásica: cada mes se divide por la media móvil centrada de 12 meses y se toma
    la mediana de esos cocientes por mes del calendario (la mediana resiste meses atípicos).
    """
    if len(y) < MIN_MONTHS_SEASONAL or (y <= 0).mean() > 0.25:
        return np.ones(SEASON)
    trend = y.rolling(SEASON, center=True).mean().rolling(2).mean().shift(-1)
    ratios = (y / trend).replace([np.inf, -np.inf], np.nan)
    by_month = pd.Series(ratios.to_numpy(), index=[p.month for p in y.index]).groupby(level=0).median()
    idx = np.array([by_month.get(m, np.nan) for m in range(1, SEASON + 1)], dtype=float)
    idx = np.where(np.isfinite(idx) & (idx > 0), idx, 1.0)
    idx = np.clip(idx, 0.3, 3.0)
    return idx / idx.mean()


@dataclass
class HoltWintersFit:
    alpha: float
    beta: float
    phi: float
    seasonal: np.ndarray            # índices por mes del calendario (0 = enero)
    fitted: np.ndarray              # pronóstico a un paso de cada mes de la historia
    level: float
    trend: float
    last_period: pd.Period
    residual_std: float = 0.0       # desviación del error a un paso (escala desestacionalizada)
    params: dict = field(default_factory=dict)

    def forecast(self, horizon: int) -> np.ndarray:
        """Pronóstico de los ``horizon`` meses siguientes a ``last_period`` (nunca negativo)."""
        if horizon <= 0:
            return np.array([], dtype=float)
        damp = np.cumsum(self.phi ** np.arange(1, horizon + 1))
        base = self.level + damp * self.trend
        months = [(self.last_period + h).month for h in range(1, horizon + 1)]
        return np.maximum(base * self.seasonal[np.array(months) - 1], 0.0)


def _run(d: np.ndarray, alpha: float, beta: float, phi: float) -> tuple[np.ndarray, float, float]:
    """Holt amortiguado sobre la serie desestacionalizada. Devuelve (pronósticos a un paso, nivel, tendencia)."""
    n = len(d)
    warm = min(SEASON, n)
    level = float(d[:warm].mean())
    trend = 0.0
    if n >= 2 * SEASON:
        trend = float((d[SEASON:2 * SEASON].mean() - d[:SEASON].mean()) / SEASON)
    preds = np.empty(n)
    for t in range(n):
        preds[t] = level + phi * trend
        prev = level
        level = max(alpha * d[t] + (1 - alpha) * (level + phi * trend), 0.0)  # ventas nunca negativas
        trend = beta * (level - prev) + (1 - beta) * phi * trend
    return preds, level, trend


def fit_holt_winters(y: pd.Series) -> HoltWintersFit:
    """Ajusta el modelo eligiendo alpha/beta/phi por mínimo error cuadrático a un paso."""
    if y.empty:
        raise ValueError("No hay ventas mensuales para ajustar el modelo")
    seasonal = seasonal_indices(y)
    s = seasonal[np.array([p.month for p in y.index]) - 1]
    d = y.to_numpy(dtype=float) / s
    skip = min(SEASON, max(len(d) - 1, 0))  # no puntuar el arranque (el nivel inicial aún no se ha adaptado)

    best = None
    for alpha, beta, phi in product(_ALPHAS, _BETAS, _PHIS):
        preds, level, trend = _run(d, alpha, beta, phi)
        sse = float(np.sum((d[skip:] - preds[skip:]) ** 2)) if len(d) > skip else 0.0
        if best is None or sse < best[0]:
            best = (sse, float(alpha), float(beta), float(phi), preds, level, trend)

    _, alpha, beta, phi, preds, level, trend = best
    residuals = d[skip:] - preds[skip:]
    return HoltWintersFit(
        alpha=alpha, beta=beta, phi=phi, seasonal=seasonal,
        fitted=np.maximum(preds * s, 0.0), level=level, trend=trend,
        last_period=y.index[-1],
        residual_std=float(np.std(residuals)) if len(residuals) > 1 else 0.0,
        params={"alpha": alpha, "beta": beta, "phi": phi, "estacionalidad": len(y) >= MIN_MONTHS_SEASONAL},
    )


def _error_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    total = float(np.sum(np.abs(actual)))
    abs_err = np.abs(actual - predicted)
    return {
        "mae": round(float(abs_err.mean()), 2),
        "wape": round(float(abs_err.sum() / total * 100), 2) if total > 0 else None,
    }


def backtest(y: pd.Series, months: int = BACKTEST_MONTHS) -> dict | None:
    """Entrena sin los últimos ``months`` meses y mide el error al pronosticarlos.

    Se compara con el método ingenuo estacional (repetir el mismo mes del año anterior):
    si el modelo no mejora a ese baseline, la proyección no aporta mucho.
    """
    if len(y) < MIN_MONTHS_BACKTEST:
        return None
    train, test = y.iloc[:-months], y.iloc[-months:]
    model = fit_holt_winters(train)
    predicted = model.forecast(months)
    actual = test.to_numpy(dtype=float)
    naive = y.iloc[-months - SEASON:-SEASON].to_numpy(dtype=float)
    result = {
        "metodo": "backtest",
        "meses": months,
        "desde": str(test.index[0]),
        "hasta": str(test.index[-1]),
        **_error_metrics(actual, predicted),
    }
    result["wape_ingenuo_estacional"] = _error_metrics(actual, naive)["wape"]
    return result
