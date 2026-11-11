"""Contrato servicio-a-servicio con Spring Boot (PrediccionApiClient + FastApiGateway)."""
import threading

import pytest

from app.api.v1.endpoints import spring_integration
from app.prediction import repository
from app.prediction.repository import SCOPE_GENERATE, SCOPE_READ
from app.tests.test_prediction import _seed_admin


@pytest.fixture(autouse=True)
def _limpiar_cache():
    spring_integration.clear_prediction_cache()
    yield
    spring_integration.clear_prediction_cache()


def _service_key(db, scopes):
    _row, raw_key = repository.create_api_client(db, "spring-boot-test", scopes, created_by=None)
    return {"X-API-Key": raw_key}


def test_requires_api_key(client):
    assert client.get("/api/prediccion/datos-grafica").status_code == 401
    assert client.get("/api/prediccion/datos-grafica", headers={"X-API-Key": "cdo_pk_falsa"}).status_code == 401


def test_scope_is_enforced(client, db_session, seeded_roles):
    _seed_admin(db_session)
    read_only = _service_key(db_session, [SCOPE_READ])
    response = client.post("/api/prediccion/generar", headers=read_only, json={"anno": 2026, "mes": 5})
    assert response.status_code == 403


def test_grafica_matches_spring_dto(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)
    # El modelo ML (TensorFlow) se prueba en test_prediction.py; aquí solo el contrato HTTP.
    calls = {}

    def fake_forecast(db, years, forecast_months):
        calls.update(years=years, months=forecast_months)
        return {"anios": years, "proyeccion_meses": forecast_months, "metricas": {},
                "serie": [{"fecha": "2026-01", "tipo": "real", "real": 10.0, "prediccion": 11.0}]}

    monkeypatch.setattr(spring_integration, "generate_forecast", fake_forecast)
    headers = {**_service_key(db_session, [SCOPE_READ]), "X-Request-Id": "test-123"}
    response = client.get("/api/prediccion/datos-grafica", headers=headers,
                          params={"anios": 3, "proyeccion_meses": 4})
    assert response.status_code == 200
    data = response.json()
    # Campos de GraficaMensualResponse (Java)
    assert data["anios"] == 3 and data["proyeccion_meses"] == 4
    assert {"fecha", "tipo", "real", "prediccion"} <= set(data["serie"][0])
    assert "metricas" in data
    assert calls == {"years": 3, "months": 4}


def test_generar_matches_spring_dto(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)
    monkeypatch.setattr(spring_integration, "forecast_month",
                        lambda db, anno, mes: {"anno": anno, "mes": mes, "prediccion": 1234.5})
    headers = _service_key(db_session, [SCOPE_GENERATE])
    response = client.post("/api/prediccion/generar", headers=headers, json={"anno": 2026, "mes": 5})
    assert response.status_code == 200
    body = response.json()
    assert body == {"resultado": 1234.5, "mensaje": "Predicción generada", "success": True}


def test_generar_rejects_out_of_range(client, db_session, seeded_roles):
    _seed_admin(db_session)
    headers = _service_key(db_session, [SCOPE_GENERATE])
    assert client.post("/api/prediccion/generar", headers=headers, json={"anno": 2026, "mes": 13}).status_code == 422


def test_data_error_maps_to_422(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)

    def no_data(db, anno, mes):
        raise ValueError("No hay compras pagadas suficientes")

    monkeypatch.setattr(spring_integration, "forecast_month", no_data)
    headers = _service_key(db_session, [SCOPE_GENERATE])
    assert client.post("/api/prediccion/generar", headers=headers, json={"anno": 2026, "mes": 5}).status_code == 422


def test_prediccion_se_calcula_una_vez_y_se_cachea(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)
    llamadas = []

    def lento(db, anno, mes):
        llamadas.append((anno, mes))
        return {"anno": anno, "mes": mes, "prediccion": 10.0}

    monkeypatch.setattr(spring_integration, "forecast_month", lento)
    headers = _service_key(db_session, [SCOPE_GENERATE])
    for _ in range(3):
        r = client.post("/api/prediccion/generar", headers=headers, json={"anno": 2026, "mes": 7})
        assert r.status_code == 200 and r.json()["resultado"] == 10.0
    assert llamadas == [(2026, 7)]


def test_peticiones_simultaneas_entrenan_una_sola_vez():
    inicio = threading.Event()
    llamadas = []

    def compute():
        llamadas.append(1)
        inicio.wait(1)  # simula el entrenamiento mientras llegan otras peticiones
        return {"ok": True}

    resultados = []
    hilos = [threading.Thread(target=lambda: resultados.append(
        spring_integration.cached_prediction("test:single-flight", compute))) for _ in range(5)]
    for h in hilos:
        h.start()
    inicio.set()
    for h in hilos:
        h.join(5)
    assert resultados == [{"ok": True}] * 5
    assert len(llamadas) == 1
