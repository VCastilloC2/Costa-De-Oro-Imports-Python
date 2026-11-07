"""Pruebas del servicio ML de predicciones (fases 1-6 y API REST /api/v1/predictions)."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.core.security import create_token
from app.models import Usuario
from app.prediction import preparation
from app.prediction.evaluation import regression_report
from app.prediction.preparation import (
    TARGET, DataPreparationError, ExtractionResult, load_transactions, prepare_sales_data,
)
from app.prediction.training_service import training_service
from app.prediction.transformation import SalesTensorTransformer

FAST_TRAIN = {"granularity": "monthly", "data_source": "csv", "epochs": 30, "patience": 5, "wait": True}


def _transactions(days=120, start=datetime(2025, 1, 1)):
    rng = np.random.default_rng(7)
    rows = []
    for i in range(days):
        for j in range(int(rng.integers(1, 4))):
            rows.append({"compra_id": len(rows) + 1, "usuario_id": j + 1,
                         "fecha": start + timedelta(days=i, hours=j), "venta_total": float(rng.integers(20000, 90000)),
                         "cantidad_productos": 1, "total_unidades": 2, "precio_promedio": 30000.0,
                         "categoria_principal": "Whisky", "ciudad_cliente": "Bogota"})
    return pd.DataFrame(rows)


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prediction_model_dir", tmp_path / "artifacts")
    monkeypatch.setattr(training_service, "_state", {"status": "idle", "job_id": None})
    return tmp_path / "artifacts"


@pytest.fixture
def admin_headers(db_session, seeded_roles):
    db_session.add(Usuario(usuario_id=1, correo="admin@example.com", password="x", rol_id=1, is_enabled=True,
                           account_non_expired=True, account_non_locked=True, credentials_non_expired=True))
    db_session.add(Usuario(usuario_id=2, correo="cliente@example.com", password="x", rol_id=2, is_enabled=True,
                           account_non_expired=True, account_non_locked=True, credentials_non_expired=True))
    db_session.commit()
    return {"Authorization": f"Bearer {create_token('1', 'ADMIN')}"}


# ----------------------------------------------------------------------- FASE 1 y 2

def test_preparation_summary_cleans_and_splits_chronologically():
    tx = _transactions()
    tx.loc[0, "venta_total"] = None
    tx.loc[1, "fecha"] = None
    tx = pd.concat([tx, tx.iloc[[5]]], ignore_index=True)  # compra duplicada
    prep = prepare_sales_data(ExtractionResult(tx, "database", True), "daily", reference=datetime(2025, 6, 1))
    s = prep.summary
    assert s["registros_originales"] == len(tx)
    assert s["registros_descartados"] == 3
    assert s["detalle_descartes"]["duplicados"] == 1
    assert s["estado_validacion"] == "VALIDO"
    assert s["registros_entrenamiento"] + s["registros_validacion"] + s["registros_prueba"] == s["registros_utilizables"]
    train, val, test = (prep.splits[k] for k in ("entrenamiento", "validacion", "prueba"))
    assert train["fecha_periodo"].max() < val["fecha_periodo"].min() < test["fecha_periodo"].min()


def test_lag_features_only_use_past_values():
    prep = prepare_sales_data(ExtractionResult(_transactions(), "database", True), "daily",
                              reference=datetime(2025, 6, 1))
    full = prep.dataset
    assert (full["ventas_lag_1"].iloc[1:].to_numpy() == full[TARGET].iloc[:-1].to_numpy()).all()
    window = full[TARGET].shift(1).rolling(7).mean()
    assert np.allclose(full["ventas_media_movil_7"].iloc[8:], window.iloc[8:])


def test_insufficient_data_is_rejected_with_summary():
    with pytest.raises(DataPreparationError) as error:
        prepare_sales_data(ExtractionResult(_transactions(days=10), "database", True), "daily",
                           reference=datetime(2025, 6, 1))
    assert error.value.summary["estado_validacion"] == "INVALIDO"


def test_csv_only_supports_monthly_granularity():
    with pytest.raises(DataPreparationError, match="fechas exactas"):
        prepare_sales_data(load_transactions(None, "csv"), "daily")


def test_scaler_is_fitted_on_training_only_and_roundtrips(tmp_path):
    prep = prepare_sales_data(ExtractionResult(_transactions(), "database", True), "daily",
                              reference=datetime(2025, 6, 1))
    transformer = SalesTensorTransformer(prep.feature_names, prep.target)
    data = transformer.prepare(prep)
    assert np.isclose(transformer.y_scaler.mean_[0], prep.splits["entrenamiento"][TARGET].mean())
    assert data.x_train.dtype == np.float32 and data.x_train.shape[1] == len(prep.feature_names)
    transformer.save(tmp_path / "scaler.joblib")
    loaded = SalesTensorTransformer.load(tmp_path / "scaler.joblib")
    assert loaded.feature_names == transformer.feature_names
    assert np.allclose(loaded.transform_features(prep.splits["prueba"]), data.x_test)


def test_regression_report_values_are_computed_not_invented():
    report = regression_report([100, 200], [110, 180])
    assert report["mae"] == 15 and report["mse"] == 250
    assert report["mape_percentage"] == 10 and report["accuracy_percentage"] == 90
    assert regression_report([], [])["accuracy_percentage"] is None


# ----------------------------------------------------------------------- API REST

def test_endpoints_require_credentials_with_json_envelope(client, model_dir):
    response = client.get("/api/v1/predictions/model/status")
    assert response.status_code == 401
    assert response.json()["success"] is False and response.json()["error"]["code"] == "UNAUTHORIZED"
    assert client.get("/api/v1/predictions/health").status_code == 200


def test_non_admin_cannot_train(client, admin_headers, model_dir):
    headers = {"Authorization": f"Bearer {create_token('2')}"}
    assert client.post("/api/v1/predictions/model/train", headers=headers, json=FAST_TRAIN).status_code == 403


def test_generate_without_trained_model_returns_409(client, admin_headers, model_dir):
    response = client.post("/api/v1/predictions/generate", headers=admin_headers,
                           json={"period": "3_months", "data_source": "csv"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_NOT_TRAINED"


def test_period_granularity_mismatch_is_422(client, admin_headers, model_dir):
    response = client.post("/api/v1/predictions/generate", headers=admin_headers,
                           json={"period": "7_days", "granularity": "monthly"})
    assert response.status_code == 422


def test_daily_training_with_csv_reports_invalid_data(client, admin_headers, model_dir):
    response = client.post("/api/v1/predictions/model/train", headers=admin_headers,
                           json={**FAST_TRAIN, "granularity": "daily"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_DATA"
    assert body["error"]["details"]["estado_validacion"] == "INVALIDO"


def test_concurrent_training_is_rejected(client, admin_headers, model_dir, monkeypatch):
    monkeypatch.setattr(training_service, "_state", {"status": "running", "job_id": "abc"})
    response = client.post("/api/v1/predictions/model/train", headers=admin_headers, json=FAST_TRAIN)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRAINING_IN_PROGRESS"


def test_full_flow_train_generate_history_and_api_key(client, admin_headers, model_dir):
    trained = client.post("/api/v1/predictions/model/train", headers=admin_headers, json=FAST_TRAIN)
    assert trained.status_code == 200, trained.text
    state = trained.json()["data"]
    assert state["status"] == "completed" and state["model_version"] == 1
    assert state["epochs"] and "val_loss" in state["epochs"][0]
    assert (model_dir / "monthly" / "v1" / "model.keras").exists()
    assert (model_dir / "monthly" / "v1" / "scaler.joblib").exists()

    metrics = client.get("/api/v1/predictions/model/metrics", headers=admin_headers).json()["data"]
    assert metrics["preliminary"]["tipo"] == "PRELIMINAR"
    assert metrics["preliminary"]["samples"] == metrics["preparation"]["registros_prueba"]
    assert metrics["model"]["architecture"][1]["unidades"] == 16

    status = client.get("/api/v1/predictions/model/status", headers=admin_headers).json()["data"]
    assert status["any_model_trained"] and status["history_storage_available"]

    body = {"period": "3_months", "prediction_type": "sales", "granularity": "monthly", "data_source": "csv"}
    first = client.post("/api/v1/predictions/generate", headers=admin_headers, json=body)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["registered"] and data["prediction_id"] and not data["duplicated"]
    assert len(data["forecast"]["breakdown"]) == 3
    assert data["forecast"]["predicted_sales"] >= 0
    assert data["prediction_variables"][0]["name"] == "periodo_indice"
    second = client.post("/api/v1/predictions/generate", headers=admin_headers, json=body).json()["data"]
    assert second["duplicated"] and second["prediction_id"] == data["prediction_id"]

    pid = data["prediction_id"]
    assert client.get(f"/api/v1/predictions/{pid}", headers=admin_headers).json()["data"]["prediction_id"] == pid
    assert client.get("/api/v1/predictions/999", headers=admin_headers).status_code == 404
    assert client.get("/api/v1/predictions/history", headers=admin_headers).json()["data"]["total"] == 1
    assert client.get("/api/v1/predictions/statistics", headers=admin_headers).json()["data"]["total_predictions"] == 1
    assert client.get("/api/v1/predictions/summary", headers=admin_headers).json()["data"]["latest_predictions"]
    compare = client.get("/api/v1/predictions/compare", headers=admin_headers).json()["data"]
    assert compare["metric_type"] == "POSTERIOR" and compare["pending"] == 1
    evaluated = client.post("/api/v1/predictions/model/evaluate", headers=admin_headers,
                            json={"granularity": "monthly", "data_source": "csv"})
    assert evaluated.status_code == 200

    created = client.post("/api/v1/predictions/clients", headers=admin_headers,
                          json={"name": "erp-spring-boot", "scopes": ["predictions:read", "predictions:generate"]})
    assert created.status_code == 201
    key = created.json()["data"]["api_key"]
    service = {"X-API-Key": key}
    external = client.post("/api/v1/predictions/generate", headers={**service, "Idempotency-Key": "req-1"},
                           json={**body, "period": "1_month"})
    assert external.status_code == 200, external.text
    assert client.post("/api/v1/predictions/model/train", headers=service, json=FAST_TRAIN).status_code == 403
    assert client.get("/api/v1/predictions/history", headers={"X-API-Key": "cdo_pk_invalida"}).status_code == 401

    read_only = client.post("/api/v1/predictions/clients", headers=admin_headers,
                            json={"name": "reportes", "scopes": ["predictions:read"]}).json()["data"]
    response = client.post("/api/v1/predictions/generate", headers={"X-API-Key": read_only["api_key"]}, json=body)
    assert response.status_code == 403
    client_id = created.json()["data"]["client_id"]
    assert client.delete(f"/api/v1/predictions/clients/{client_id}", headers=admin_headers).status_code == 200
    assert client.get("/api/v1/predictions/history", headers=service).status_code == 401


def test_legacy_demand_route_keeps_its_contract(client, admin_headers):
    response = client.post("/api/v1/predictions/demand", headers=admin_headers, json={"target_month": 13})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_openapi_documents_both_auth_schemes(client):
    schema = client.get("/v3/api-docs").json()
    schemes = schema["components"]["securitySchemes"]
    assert "ApiKeyAuth" in schemes and "HTTPBearer" in schemes
    assert "/api/v1/predictions/generate" in schema["paths"]


def test_monthly_csv_extraction_has_no_exact_dates():
    extraction = load_transactions(None, "csv")
    assert extraction.has_exact_dates is False
    assert (extraction.transactions["fecha"].dt.day == 1).all()
    assert preparation.GRANULARITIES["monthly"].warmup == 3
