"""FASE 3 — Modelado con TensorFlow / Keras.

Arquitectura de referencia:
    Entrada (n variables) -> Dense(16, ReLU) -> Dense(8, ReLU) -> Dense(1, Linear)
Optimizer Adam, pérdida MSE, métrica MAE, EarlyStopping sobre la pérdida de validación.
TensorFlow se importa de forma diferida para no penalizar el arranque de las rutas no predictivas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

MODEL_NAME = "TensorFlow Sales Prediction"
ARCHITECTURE = [
    {"capa": "entrada", "unidades": "n_variables", "activacion": None},
    {"capa": "oculta_1", "unidades": 16, "activacion": "relu"},
    {"capa": "oculta_2", "unidades": 8, "activacion": "relu"},
    {"capa": "salida", "unidades": 1, "activacion": "linear"},
]
DEFAULT_SEED = 41


class TensorFlowUnavailableError(RuntimeError):
    pass


def import_tensorflow():
    try:
        import tensorflow as tf
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise TensorFlowUnavailableError(
            "TensorFlow no está instalado en el backend. Instala las dependencias de requirements.txt.") from exc
    return tf


def tensorflow_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("tensorflow")
    except Exception:  # noqa: BLE001
        return None


@dataclass
class TrainingConfig:
    epochs: int = 300
    batch_size: int = 16
    learning_rate: float = 0.001
    patience: int = 25
    start_from_epoch: int = 20
    seed: int = DEFAULT_SEED


def build_sales_network(n_features: int, learning_rate: float = 0.001, seed: int = DEFAULT_SEED):
    tf = import_tensorflow()
    tf.keras.utils.set_random_seed(seed)
    model = tf.keras.Sequential(name="costa_de_oro_sales_mlp", layers=[
        tf.keras.layers.Input(shape=(n_features,), name="entrada"),
        tf.keras.layers.Dense(16, activation="relu", name="oculta_1"),
        tf.keras.layers.Dense(8, activation="relu", name="oculta_2"),
        tf.keras.layers.Dense(1, activation="linear", name="salida"),
    ])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="mean_squared_error",
        metrics=["mean_absolute_error"],
    )
    return model


def fit_network(model, data, config: TrainingConfig, on_epoch_end: Callable[[int, dict], None] | None = None) -> dict:
    """Entrena con EarlyStopping (restaura los mejores pesos) y devuelve el historial por época."""
    tf = import_tensorflow()
    # start_from_epoch evita que el ruido de las primeras épocas (pocos datos) detenga el ajuste
    # antes de que la red aprenda; los mejores pesos se eligen a partir de esa época.
    callbacks = [tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=config.patience, restore_best_weights=True, min_delta=1e-6,
        start_from_epoch=min(config.start_from_epoch, max(0, config.epochs // 2)))]
    if on_epoch_end is not None:
        callbacks.append(tf.keras.callbacks.LambdaCallback(
            on_epoch_end=lambda epoch, logs: on_epoch_end(epoch + 1, dict(logs or {}))))
    history = model.fit(
        data.x_train, data.y_train,
        validation_data=(data.x_val, data.y_val),
        epochs=config.epochs,
        batch_size=max(1, min(config.batch_size, len(data.x_train))),
        shuffle=False,  # respeta el orden temporal; la validación es posterior al entrenamiento
        verbose=0,
        callbacks=callbacks,
    )
    early_stopping = callbacks[0]
    hist = {key: [float(v) for v in values] for key, values in history.history.items()}
    val_losses = hist.get("val_loss", [])
    first = early_stopping.start_from_epoch if len(val_losses) > early_stopping.start_from_epoch else 0
    best_epoch = int(min(range(first, len(val_losses)), key=val_losses.__getitem__) + 1) if val_losses else None
    return {
        "epocas_ejecutadas": len(hist.get("loss", [])),
        "mejor_epoca": best_epoch,
        "detenido_anticipadamente": bool(getattr(early_stopping, "stopped_epoch", 0)),
        "historial": hist,
    }


def predict_scaled(model, x):
    tf = import_tensorflow()
    return model(tf.convert_to_tensor(x), training=False).numpy().reshape(-1)


def load_keras_model(path):
    tf = import_tensorflow()
    return tf.keras.models.load_model(path, compile=False)
