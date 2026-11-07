"""Almacenamiento versionado de modelos entrenados.

Estructura (``PREDICTION_MODEL_DIR``, por defecto ``app/prediction/artifacts``)::

    <dir>/<granularidad>/v<N>/model.keras     modelo Keras
    <dir>/<granularidad>/v<N>/scaler.joblib   orden de variables + StandardScaler X/Y
    <dir>/<granularidad>/v<N>/metadata.json   resumen de preparación, entrenamiento y métricas
    <dir>/<granularidad>/active.json          versión activa usada por el servicio de predicción
    <dir>/.training.lock                      bloqueo entre procesos (un entrenamiento a la vez)

Los artefactos los genera el propio backend; no cargues aquí archivos de terceros.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.config import PROJECT_ROOT, settings
from app.prediction.tf_model import load_keras_model, predict_scaled
from app.prediction.transformation import SalesTensorTransformer


class ModelNotTrainedError(LookupError):
    pass


@dataclass
class LoadedModel:
    granularity: str
    version: int
    keras_model: object
    transformer: SalesTensorTransformer
    metadata: dict

    def predict(self, frame) -> np.ndarray:
        """Transforma con el scaler del entrenamiento, ejecuta la red y desescala."""
        x = self.transformer.transform_features(frame)
        return self.transformer.inverse_target(predict_scaled(self.keras_model, x))


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


class ModelStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else None
        self._cache: dict[str, tuple[float, LoadedModel]] = {}
        self._lock = threading.Lock()

    @property
    def base_dir(self) -> Path:
        path = self._base_dir or Path(settings.prediction_model_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def granularity_dir(self, granularity: str) -> Path:
        return self.base_dir / granularity

    def version_dir(self, granularity: str, version: int) -> Path:
        return self.granularity_dir(granularity) / f"v{version}"

    def versions(self, granularity: str) -> list[int]:
        root = self.granularity_dir(granularity)
        if not root.exists():
            return []
        found = []
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit() \
                    and (child / "metadata.json").exists():
                found.append(int(child.name[1:]))
        return sorted(found)

    def next_version(self, granularity: str) -> int:
        existing = self.versions(granularity)
        return (existing[-1] + 1) if existing else 1

    def save(self, granularity: str, version: int, keras_model, transformer: SalesTensorTransformer,
             metadata: dict, activate: bool = True) -> Path:
        target = self.version_dir(granularity, version)
        staging = target.with_name(target.name + ".partial")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        keras_model.save(staging / "model.keras")
        transformer.save(staging / "scaler.joblib")
        _write_json(staging / "metadata.json", metadata)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
        if activate:
            self.activate(granularity, version)
        return target

    def activate(self, granularity: str, version: int) -> None:
        if version not in self.versions(granularity):
            raise ModelNotTrainedError(f"No existe la versión v{version} para {granularity}")
        _write_json(self.granularity_dir(granularity) / "active.json",
                    {"version": version, "activado_en": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def active_version(self, granularity: str) -> int | None:
        pointer = self.granularity_dir(granularity) / "active.json"
        if not pointer.exists():
            return None
        try:
            version = int(json.loads(pointer.read_text(encoding="utf-8"))["version"])
        except (ValueError, KeyError, json.JSONDecodeError):
            return None
        return version if (self.version_dir(granularity, version) / "metadata.json").exists() else None

    def read_metadata(self, granularity: str, version: int | None = None) -> dict:
        version = version or self.active_version(granularity)
        if not version:
            raise ModelNotTrainedError(f"No hay un modelo entrenado para la granularidad '{granularity}'")
        path = self.version_dir(granularity, version) / "metadata.json"
        if not path.exists():
            raise ModelNotTrainedError(f"No existe la versión v{version} para {granularity}")
        return json.loads(path.read_text(encoding="utf-8"))

    def update_metadata(self, granularity: str, version: int, updates: dict) -> dict:
        metadata = self.read_metadata(granularity, version)
        metadata.update(updates)
        _write_json(self.version_dir(granularity, version) / "metadata.json", metadata)
        with self._lock:
            cached = self._cache.get(str(self.version_dir(granularity, version).resolve()))
            if cached:
                cached[1].metadata = metadata
        return metadata

    def load(self, granularity: str, version: int | None = None) -> LoadedModel:
        """Recupera el modelo y el scaler SIN reentrenar (caché en memoria por versión)."""
        version = version or self.active_version(granularity)
        if not version:
            raise ModelNotTrainedError(
                f"No hay un modelo entrenado para la granularidad '{granularity}'. "
                "Un administrador debe ejecutar POST /api/v1/predictions/model/train")
        folder = self.version_dir(granularity, version)
        model_path = folder / "model.keras"
        if not model_path.exists():
            raise ModelNotTrainedError(f"Faltan los artefactos de la versión v{version} ({granularity})")
        key = str(folder.resolve())
        stamp = model_path.stat().st_mtime
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == stamp:
                return cached[1]
            loaded = LoadedModel(
                granularity=granularity, version=version,
                keras_model=load_keras_model(model_path),
                transformer=SalesTensorTransformer.load(folder / "scaler.joblib"),
                metadata=json.loads((folder / "metadata.json").read_text(encoding="utf-8")),
            )
            self._cache[key] = (stamp, loaded)
            return loaded

    # -- bloqueo de entrenamiento entre procesos ------------------------------
    @property
    def lock_path(self) -> Path:
        return self.base_dir / ".training.lock"

    def acquire_training_lock(self, job_id: str) -> bool:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > settings.prediction_training_lock_ttl_seconds:
                    self.lock_path.unlink(missing_ok=True)  # bloqueo huérfano de un proceso caído
                    continue
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"job_id": job_id, "pid": os.getpid(), "inicio": time.time()}))
            return True
        return False

    def release_training_lock(self, job_id: str) -> None:
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if data.get("job_id") == job_id:
            self.lock_path.unlink(missing_ok=True)


model_store = ModelStore()
