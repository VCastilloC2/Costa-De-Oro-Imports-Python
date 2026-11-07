"""FASE 2 — Preparación y transformación de datos al formato requerido por TensorFlow.

``SalesTensorTransformer`` es el ÚNICO punto donde se convierten DataFrames a tensores. Se usa
igual en entrenamiento y en predicción: el orden de las variables y los scalers se persisten junto
al modelo y se recargan, de modo que la transformación en inferencia es idéntica a la de
entrenamiento.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from app.prediction.preparation import PreparationResult

TRANSFORMER_FORMAT_VERSION = 1


class TransformationError(ValueError):
    pass


@dataclass
class TensorDatasets:
    x_train: np.ndarray
    y_train: np.ndarray
    x_val: np.ndarray
    y_val: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    test_dates: list[str]

    def shapes(self) -> dict[str, list[int]]:
        return {name: list(getattr(self, name).shape)
                for name in ("x_train", "y_train", "x_val", "y_val", "x_test", "y_test")}


class SalesTensorTransformer:
    """Matrices X/Y numéricas float32 con StandardScaler (X e Y) ajustados sólo con entrenamiento."""

    def __init__(self, feature_names: list[str], target_name: str) -> None:
        if not feature_names:
            raise TransformationError("Se requiere al menos una variable predictora")
        self.feature_names = list(feature_names)
        self.target_name = target_name
        self.x_scaler = StandardScaler()
        self.y_scaler = StandardScaler()
        self.fitted = False

    # -- conversión ---------------------------------------------------------
    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [name for name in self.feature_names if name not in frame.columns]
        if missing:
            raise TransformationError(f"Faltan variables de entrada: {missing}")
        matrix = frame[self.feature_names].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
        if not np.isfinite(matrix).all():
            bad = [self.feature_names[i] for i in np.where(~np.isfinite(matrix).all(axis=0))[0]]
            raise TransformationError(f"Variables con valores nulos o no finitos: {bad}")
        return matrix

    def _target(self, frame: pd.DataFrame) -> np.ndarray:
        values = pd.to_numeric(frame[self.target_name], errors="coerce").to_numpy(dtype=np.float64).reshape(-1, 1)
        if not np.isfinite(values).all():
            raise TransformationError("La variable objetivo contiene valores nulos o no finitos")
        return values

    # -- ajuste y transformación -------------------------------------------
    def fit(self, train: pd.DataFrame) -> "SalesTensorTransformer":
        if train.empty:
            raise TransformationError("No hay datos de entrenamiento para ajustar el scaler")
        self.x_scaler.fit(self._matrix(train))
        self.y_scaler.fit(self._target(train))
        self.fitted = True
        return self

    def _require_fitted(self) -> None:
        if not self.fitted:
            raise TransformationError("El transformador no ha sido ajustado")

    def transform_features(self, frame: pd.DataFrame) -> np.ndarray:
        """Transforma datos nuevos con el scaler YA entrenado (nunca se reajusta)."""
        self._require_fitted()
        return self.x_scaler.transform(self._matrix(frame)).astype(np.float32)

    def transform_target(self, frame: pd.DataFrame) -> np.ndarray:
        self._require_fitted()
        return self.y_scaler.transform(self._target(frame)).astype(np.float32)

    def inverse_target(self, scaled: np.ndarray) -> np.ndarray:
        self._require_fitted()
        values = self.y_scaler.inverse_transform(np.asarray(scaled, dtype=np.float64).reshape(-1, 1)).ravel()
        return np.clip(values, 0.0, None)

    def prepare(self, prepared: PreparationResult) -> TensorDatasets:
        """Ajusta con entrenamiento y produce X/Y de entrenamiento, validación y prueba."""
        self.fit(prepared.splits["entrenamiento"])
        parts = {}
        for key, name in (("train", "entrenamiento"), ("val", "validacion"), ("test", "prueba")):
            frame = prepared.splits[name]
            parts[f"x_{key}"] = self.transform_features(frame)
            parts[f"y_{key}"] = self.transform_target(frame)
        test_dates = [d.date().isoformat() for d in pd.to_datetime(prepared.splits["prueba"]["fecha_periodo"])]
        return TensorDatasets(**parts, test_dates=test_dates)

    # -- persistencia -------------------------------------------------------
    def to_dict(self) -> dict:
        return {"format_version": TRANSFORMER_FORMAT_VERSION, "feature_names": self.feature_names,
                "target_name": self.target_name, "x_scaler": self.x_scaler, "y_scaler": self.y_scaler}

    def save(self, path: Path) -> None:
        self._require_fitted()
        joblib.dump(self.to_dict(), path)

    @classmethod
    def load(cls, path: Path) -> "SalesTensorTransformer":
        data = joblib.load(path)
        if data.get("format_version") != TRANSFORMER_FORMAT_VERSION:
            raise TransformationError("Versión de scaler incompatible; vuelve a entrenar el modelo")
        transformer = cls(data["feature_names"], data["target_name"])
        transformer.x_scaler = data["x_scaler"]
        transformer.y_scaler = data["y_scaler"]
        transformer.fitted = True
        return transformer
