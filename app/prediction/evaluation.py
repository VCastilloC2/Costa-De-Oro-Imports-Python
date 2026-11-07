"""FASE 5 — Métricas de desempeño.

* Métricas PRELIMINARES: se calculan sobre el conjunto de prueba (períodos posteriores a
  entrenamiento y validación, nunca vistos por la red) inmediatamente después de entrenar.
* Métricas POSTERIORES: comparan predicciones registradas en el historial con las ventas reales
  que ocurrieron después (``/api/v1/predictions/compare`` y ``/model/evaluate``).

Todos los valores se calculan con datos reales; si no hay muestras suficientes se devuelve ``None``
(nunca se inventan porcentajes).
"""
from __future__ import annotations

import math

import numpy as np

ACCURACY_BASIS = "Porcentaje de acierto aproximado = max(0, 100 - MAPE)"


def _round(value, digits=4):
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def regression_report(actual, predicted) -> dict:
    actual = np.asarray(actual, dtype=float).ravel()
    predicted = np.asarray(predicted, dtype=float).ravel()
    n = int(len(actual))
    if n == 0 or len(predicted) != n:
        return {"mae": None, "mse": None, "rmse": None, "mape_percentage": None, "wape_percentage": None,
                "accuracy_percentage": None, "samples": n, "mape_samples": 0}
    errors = predicted - actual
    mse = float(np.mean(errors ** 2))
    nonzero = actual != 0
    mape = float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100) if nonzero.any() else None
    total = float(np.sum(np.abs(actual)))
    wape = float(np.sum(np.abs(errors)) / total * 100) if total > 0 else None
    return {
        "mae": _round(np.mean(np.abs(errors))),
        "mse": _round(mse),
        "rmse": _round(math.sqrt(mse)),
        "mape_percentage": _round(mape),
        "wape_percentage": _round(wape),
        "accuracy_percentage": _round(max(0.0, 100.0 - mape), 2) if mape is not None else None,
        "samples": n,
        "mape_samples": int(nonzero.sum()),
    }


def comparison_rows(dates, actual, predicted) -> list[dict]:
    """Diferencia entre valores reales y predichos por período."""
    rows = []
    for when, real, pred in zip(dates, np.ravel(actual), np.ravel(predicted)):
        real, pred = float(real), float(pred)
        rows.append({
            "fecha": str(when),
            "real": round(real, 2),
            "predicho": round(pred, 2),
            "diferencia": round(pred - real, 2),
            "error_porcentual": round(abs(pred - real) / real * 100, 2) if real else None,
        })
    return rows
