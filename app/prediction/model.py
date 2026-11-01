"""Sales forecasting models: scikit-learn, TensorFlow/Keras, and PyTorch."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

CATEGORICAL = ["dia_semana", "categoria_principal", "ciudad_cliente"]
NUMERIC = ["anno", "mes", "cantidad_productos", "total_unidades", "precio_promedio"]
FEATURES = NUMERIC + CATEGORICAL


class SalesRegression:
    def __init__(self) -> None:
        self.estimator = LinearRegression()
        self.columns: list[str] = []
        self.coeficientes_: pd.Series | None = None

    @staticmethod
    def _matrix(data: pd.DataFrame) -> pd.DataFrame:
        missing = set(FEATURES) - set(data.columns)
        if missing:
            raise ValueError(f"Faltan variables para el modelo: {sorted(missing)}")
        return pd.get_dummies(data[FEATURES], columns=CATEGORICAL, dtype=float)

    def fit(self, data: pd.DataFrame) -> "SalesRegression":
        if data.empty:
            raise ValueError("No hay ventas históricas para entrenar el modelo")
        matrix = self._matrix(data)
        target = pd.to_numeric(data["venta_total"], errors="coerce").fillna(0).to_numpy(dtype=float)
        self.columns = list(matrix.columns)
        self.estimator.fit(matrix.to_numpy(dtype=float), target)
        self.coeficientes_ = pd.Series(self.estimator.coef_, index=self.columns)
        return self

    def predict(self, data: pd.DataFrame) -> np.ndarray:
        if not self.columns:
            raise RuntimeError("El modelo todavía no está entrenado")
        matrix = self._matrix(data).reindex(columns=self.columns, fill_value=0)
        return np.clip(self.estimator.predict(matrix.to_numpy(dtype=float)), 0.0, None)


class SalesEnsemble:
    """Train and combine three models; both neural frameworks are required."""

    model_names = ("scikit_learn", "tensorflow_keras", "pytorch")

    def __init__(self) -> None:
        self.regression = SalesRegression()
        self.columns: list[str] = []
        self.x_scaler = StandardScaler()
        self.y_scaler = StandardScaler()
        self.keras_model = None
        self.tf = None
        self.torch_model = None
        self.torch = None

    def fit(self, data: pd.DataFrame) -> "SalesEnsemble":
        if data.empty:
            raise ValueError("No hay ventas históricas para entrenar el modelo")

        # Import lazily so non-prediction API routes do not pay framework startup cost.
        try:
            import tensorflow as tf
            import torch
            from torch import nn
        except ImportError as exc:
            raise RuntimeError(
                "La predicción requiere TensorFlow y PyTorch. Instala las dependencias de requirements.txt."
            ) from exc

        self.regression.fit(data)
        self.tf = tf
        matrix = self.regression._matrix(data)
        self.columns = list(matrix.columns)
        x = matrix.to_numpy(dtype=np.float32)
        y = pd.to_numeric(data["venta_total"], errors="coerce").fillna(0).to_numpy(dtype=np.float32).reshape(-1, 1)
        x_scaled = self.x_scaler.fit_transform(x).astype(np.float32)
        y_scaled = self.y_scaler.fit_transform(y).astype(np.float32)

        tf.keras.utils.set_random_seed(41)
        with tf.device("/CPU:0"):
            self.keras_model = tf.keras.Sequential([
                tf.keras.layers.Input(shape=(x_scaled.shape[1],)),
                tf.keras.layers.Dense(32, activation="relu"),
                tf.keras.layers.Dense(16, activation="relu"),
                tf.keras.layers.Dense(1),
            ])
            self.keras_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.01), loss="mse")
            self.keras_model.fit(
                x_scaled, y_scaled, epochs=40, batch_size=min(16, max(1, len(y_scaled))),
                shuffle=False, verbose=0,
            )

        torch.manual_seed(41)
        self.torch = torch
        self.torch_model = nn.Sequential(
            nn.Linear(x_scaled.shape[1], 32), nn.ReLU(),
            nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1),
        ).to(torch.device("cpu"))
        tx = torch.from_numpy(x_scaled)
        ty = torch.from_numpy(y_scaled)
        optimizer = torch.optim.Adam(self.torch_model.parameters(), lr=0.01)
        loss_fn = nn.MSELoss()
        self.torch_model.train()
        for _ in range(60):
            optimizer.zero_grad()
            loss = loss_fn(self.torch_model(tx), ty)
            loss.backward()
            optimizer.step()
        self.torch_model.eval()
        return self

    def predict_models(self, data: pd.DataFrame) -> dict[str, np.ndarray]:
        if self.keras_model is None or self.tf is None or self.torch_model is None or self.torch is None:
            raise RuntimeError("El ensamble todavía no está entrenado")
        matrix = self.regression._matrix(data).reindex(columns=self.columns, fill_value=0)
        x = matrix.to_numpy(dtype=np.float32)
        x_scaled = self.x_scaler.transform(x).astype(np.float32)
        with self.tf.device("/CPU:0"):
            keras_scaled = self.keras_model(self.tf.convert_to_tensor(x_scaled), training=False).numpy().reshape(-1, 1)
        with self.torch.no_grad():
            torch_scaled = self.torch_model(self.torch.from_numpy(x_scaled)).cpu().numpy()
        return {
            "scikit_learn": self.regression.predict(data),
            "tensorflow_keras": np.clip(self.y_scaler.inverse_transform(keras_scaled).ravel(), 0.0, None),
            "pytorch": np.clip(self.y_scaler.inverse_transform(torch_scaled).ravel(), 0.0, None),
        }

    def predict(self, data: pd.DataFrame) -> np.ndarray:
        predictions = self.predict_models(data)
        return np.mean(np.stack(list(predictions.values())), axis=0)


_ENSEMBLE_CACHE: OrderedDict[str, SalesEnsemble] = OrderedDict()
_ENSEMBLE_CACHE_LOCK = threading.Lock()


def train_sales_ensemble(data: pd.DataFrame) -> SalesEnsemble:
    """Reuse a trained ensemble for identical history to avoid retraining per request."""
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(data, index=True).values.tobytes()).hexdigest()
    with _ENSEMBLE_CACHE_LOCK:
        model = _ENSEMBLE_CACHE.get(fingerprint)
        if model is not None:
            _ENSEMBLE_CACHE.move_to_end(fingerprint)
            return model
        model = SalesEnsemble().fit(data)
        _ENSEMBLE_CACHE[fingerprint] = model
        while len(_ENSEMBLE_CACHE) > 2:
            _ENSEMBLE_CACHE.popitem(last=False)
        return model


def regression_metrics(actual, predicted) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) == 0:
        return {"mae": None, "rmse": None, "mape": None, "r2": None, "n": 0}
    nonzero = actual != 0
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted))), 4),
        "mape": round(float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100), 4) if nonzero.any() else None,
        "r2": round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else None,
        "n": int(len(actual)),
    }


# Compatibility names for the moved prediction tests and earlier callers.
RegresionLinealMultiple = SalesRegression
metricas_regresion = regression_metrics
