"""Sales forecasting models: scikit-learn and TensorFlow/Keras."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL = ["dia_semana", "categoria_principal", "ciudad_cliente"]
NUMERIC = ["anno", "mes", "cantidad_productos", "total_unidades", "precio_promedio"]
FEATURES = NUMERIC + CATEGORICAL
MODEL_VARIABLES = [{"nombre": "venta_total", "tipo": "numeric", "rol": "objetivo"}] + [
    {"nombre": name, "tipo": ("integer" if name in {"anno", "cantidad_productos", "total_unidades"}
                                 else "numeric" if name in {"mes", "precio_promedio"} else "categorical"),
     "rol": "predictora"}
    for name in NUMERIC + CATEGORICAL
]


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), NUMERIC),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


class SalesRegression:
    def __init__(self) -> None:
        self.estimator = Pipeline([("preprocessor", _preprocessor()), ("regressor", LinearRegression())])
        self.columns: list[str] = []
        self.coeficientes_: pd.Series | None = None

    @staticmethod
    def _matrix(data: pd.DataFrame) -> pd.DataFrame:
        missing = set(FEATURES) - set(data.columns)
        if missing:
            raise ValueError(f"Faltan variables para el modelo: {sorted(missing)}")
        return data[FEATURES].copy()

    def fit(self, data: pd.DataFrame) -> "SalesRegression":
        if data.empty:
            raise ValueError("No hay ventas históricas para entrenar el modelo")
        matrix = self._matrix(data)
        target = pd.to_numeric(data["venta_total"], errors="coerce").fillna(0).to_numpy(dtype=float)
        self.estimator.fit(matrix, target)
        self.columns = list(self.estimator.named_steps["preprocessor"].get_feature_names_out())
        self.coeficientes_ = pd.Series(self.estimator.named_steps["regressor"].coef_, index=self.columns)
        return self

    def predict(self, data: pd.DataFrame) -> np.ndarray:
        if not self.columns:
            raise RuntimeError("El modelo todavía no está entrenado")
        return np.clip(self.estimator.predict(self._matrix(data)), 0.0, None)


class SalesEnsemble:
    """Train and average the scikit-learn and TensorFlow/Keras forecasts."""

    model_names = ("scikit_learn", "tensorflow_keras")

    def __init__(self) -> None:
        self.regression = SalesRegression()
        self.columns: list[str] = []
        self.x_scaler = StandardScaler()
        self.y_scaler = StandardScaler()
        self.keras_model = None
        self.tf = None
        self.loss_history: list[float] = []

    def fit(self, data: pd.DataFrame) -> "SalesEnsemble":
        if data.empty:
            raise ValueError("No hay ventas históricas para entrenar el modelo")

        # Import lazily so non-prediction API routes do not pay framework startup cost.
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise RuntimeError(
                "La predicción requiere TensorFlow/Keras. Instala las dependencias de requirements.txt."
            ) from exc

        self.regression.fit(data)
        self.tf = tf
        matrix = self.regression.estimator.named_steps["preprocessor"].transform(self.regression._matrix(data))
        self.columns = list(self.regression.columns)
        x = np.asarray(matrix, dtype=np.float32)
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
            history = self.keras_model.fit(
                x_scaled, y_scaled, epochs=40, batch_size=min(16, max(1, len(y_scaled))),
                shuffle=False, verbose=0,
            )
        self.loss_history = [float(value) for value in history.history.get("loss", [])]

        return self

    def predict_models(self, data: pd.DataFrame) -> dict[str, np.ndarray]:
        if self.keras_model is None or self.tf is None:
            raise RuntimeError("El ensamble todavía no está entrenado")
        matrix = self.regression.estimator.named_steps["preprocessor"].transform(self.regression._matrix(data))
        x = np.asarray(matrix, dtype=np.float32)
        x_scaled = self.x_scaler.transform(x).astype(np.float32)
        with self.tf.device("/CPU:0"):
            keras_scaled = self.keras_model(self.tf.convert_to_tensor(x_scaled), training=False).numpy().reshape(-1, 1)
        return {
            "scikit_learn": self.regression.predict(data),
            "tensorflow_keras": np.clip(self.y_scaler.inverse_transform(keras_scaled).ravel(), 0.0, None),
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
        return {"mae": None, "mse": None, "rmse": None, "error_porcentual": None,
                "porcentaje_prediccion": None, "r2": None, "n": 0}
    total_actual = float(np.sum(np.abs(actual)))
    error_percentage = float(np.sum(np.abs(actual - predicted)) / total_actual * 100) if total_actual > 0 else None
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "mse": round(float(mean_squared_error(actual, predicted)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted))), 4),
        "error_porcentual": round(error_percentage, 4) if error_percentage is not None else None,
        "porcentaje_prediccion": round(max(0.0, 100.0 - error_percentage), 2) if error_percentage is not None else None,
        "r2": round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else None,
        "n": int(len(actual)),
    }


# Compatibility names for the moved prediction tests and earlier callers.
RegresionLinealMultiple = SalesRegression
metricas_regresion = regression_metrics
