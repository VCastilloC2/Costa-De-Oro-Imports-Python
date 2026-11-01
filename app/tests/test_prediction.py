from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.core.security import create_token
from app.models import Categoria, Compra, DetalleVenta, Producto, Usuario
from app.prediction.engine import generate_forecast
from app.prediction import data_handler
from app.prediction.model import SalesRegression, regression_metrics, train_sales_ensemble


def _training_data(n=120):
    rng = np.random.default_rng(12)
    frame = pd.DataFrame({
        "anno": rng.choice([2020, 2021, 2022], n),
        "mes": rng.integers(1, 13, n),
        "dia_semana": rng.choice(["LUN", "MAR", "VIE"], n),
        "categoria_principal": rng.choice(["Cerveza", "Ron", "Whisky"], n),
        "ciudad_cliente": rng.choice(["Bogota", "Cali", "Sin_empresa"], n),
        "cantidad_productos": rng.integers(1, 5, n),
        "total_unidades": rng.integers(1, 10, n),
        "precio_promedio": rng.integers(5000, 50000, n).astype(float),
    })
    frame["venta_total"] = 1000 * frame["anno"] + 250 * frame["mes"] + 2 * frame["precio_promedio"] + 100 * frame["total_unidades"]
    return frame


def _seed_admin(db):
    admin = Usuario(
        usuario_id=1, correo="admin@example.com", password="irrelevant", rol_id=1,
        is_enabled=True, account_non_expired=True, account_non_locked=True,
        credentials_non_expired=True,
    )
    db.add(admin)
    db.commit()
    return {"Authorization": f"Bearer {create_token('1', 'ADMIN')}"}


def _seed_sales(db):
    db.add(Categoria(categoria_id=1, nombre="Whisky", descripcion="Bebidas"))
    db.add_all([
        Producto(producto_id=1, nombre="Whisky A", precio=40000, stock=12, activo=True, categoria_id=1),
        Producto(producto_id=2, nombre="Whisky B", precio=50000, stock=8, activo=True, categoria_id=1),
    ])
    db.add_all([
        Compra(compra_id=1, fecha=datetime(2022, 3, 10), iva=0, subtotal=40000, total=40000, estado="PAGADO", usuario_id=1),
        Compra(compra_id=2, fecha=datetime(2023, 3, 11), iva=0, subtotal=60000, total=60000, estado="PAGADO", usuario_id=1),
        Compra(compra_id=3, fecha=datetime(2024, 4, 12), iva=0, subtotal=50000, total=50000, estado="PAGADO", usuario_id=1),
    ])
    db.add_all([
        DetalleVenta(detalle_venta_id=1, compra_id=1, producto_id=1, cantidad=1, precio_unitario=40000, subtotal=40000),
        DetalleVenta(detalle_venta_id=2, compra_id=2, producto_id=1, cantidad=1, precio_unitario=60000, subtotal=60000),
        DetalleVenta(detalle_venta_id=3, compra_id=3, producto_id=2, cantidad=1, precio_unitario=50000, subtotal=50000),
    ])
    db.commit()


def test_sklearn_model_fits_and_predicts_nonnegative_values():
    data = _training_data()
    model = SalesRegression().fit(data)
    predictions = model.predict(data)
    assert len(predictions) == len(data)
    assert np.isfinite(predictions).all()
    assert (predictions >= 0).all()
    assert regression_metrics(data.venta_total, predictions)["n"] == len(data)


def test_prediction_uses_sklearn_tensorflow_keras_and_pytorch():
    data = _training_data(12)
    model = train_sales_ensemble(data)
    predictions = model.predict_models(data)
    assert set(predictions) == {"scikit_learn", "tensorflow_keras", "pytorch"}
    assert all(np.isfinite(values).all() and (values >= 0).all() for values in predictions.values())
    assert np.isfinite(model.predict(data)).all()


def test_dataset_prefers_database_when_it_has_sales(monkeypatch):
    sample = _training_data(2)
    monkeypatch.setattr(settings, "prediction_data_source", "database")
    monkeypatch.setattr(data_handler, "load_from_database", lambda *_args, **_kwargs: sample)
    monkeypatch.setattr(data_handler, "load_from_csv", lambda: pytest.fail("CSV no debe usarse si MySQL tiene datos"))
    assert data_handler.load_dataset(object()).equals(sample)


@pytest.mark.parametrize("db_result", ["error", "empty"])
def test_dataset_falls_back_to_csv_if_database_fails_or_has_no_sales(monkeypatch, db_result):
    sample = _training_data(2)
    monkeypatch.setattr(settings, "prediction_data_source", "database")
    if db_result == "error":
        def fail_database(*_args, **_kwargs):
            raise ConnectionError("MySQL no disponible")
        monkeypatch.setattr(data_handler, "load_from_database", fail_database)
    else:
        monkeypatch.setattr(data_handler, "load_from_database", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(data_handler, "load_from_csv", lambda: sample)
    assert data_handler.load_dataset(object()).equals(sample)


def test_csv_can_be_forced_for_offline_mode(monkeypatch):
    sample = _training_data(2)
    monkeypatch.setattr(settings, "prediction_data_source", "csv")
    monkeypatch.setattr(data_handler, "load_from_csv", lambda: sample)
    monkeypatch.setattr(data_handler, "load_from_database", lambda *_args, **_kwargs: pytest.fail("Modo CSV no debe llamar a MySQL"))
    assert data_handler.load_dataset(object()).equals(sample)


def test_dashboard_keeps_sales_forecast_when_database_is_unavailable(monkeypatch):
    sample = _training_data(4)
    monkeypatch.setattr(settings, "prediction_data_source", "database")
    def database_down(*_args, **_kwargs):
        raise ConnectionError("MySQL no disponible")
    monkeypatch.setattr(data_handler, "load_from_database", database_down)
    monkeypatch.setattr(data_handler, "load_from_csv", lambda: sample)

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise ConnectionError("MySQL no disponible")

    dashboard = data_handler.historical_dashboard_data(BrokenSession())
    assert dashboard["cantidad_compras"] == 4
    assert dashboard["total_ventas"] > 0
    assert dashboard["stock_vs_ventas"] == []


def test_prediction_status_route_is_admin_only(client, db_session, seeded_roles):
    headers = _seed_admin(db_session)
    response = client.get("/admin/prediccion", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"disponible": True, "mensaje": "Motor de predicciones interno activo"}
    assert client.get("/admin/prediccion").status_code == 401


def test_graph_data_uses_database_sales_and_stock(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)
    _seed_sales(db_session)
    monkeypatch.setattr(settings, "prediction_data_source", "database")
    response = client.get("/admin/prediccion/datos-grafica", headers={"Authorization": f"Bearer {create_token('1', 'ADMIN')}"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_ventas"] == 150000.0
    assert data["cantidad_compras"] == 3
    assert len(data["stock_vs_ventas"]) == 2
    assert data["proyeccion_ventas"]


def test_generate_route_returns_forecast_without_503(client, db_session, seeded_roles, monkeypatch):
    _seed_admin(db_session)
    _seed_sales(db_session)
    monkeypatch.setattr(settings, "prediction_data_source", "database")
    response = client.post(
        "/admin/prediccion/generar",
        headers={"Authorization": f"Bearer {create_token('1', 'ADMIN')}"},
        json={"anios": 3, "proyeccion_meses": 4},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["serie"]) == 40
    assert all(point["prediccion"] >= 0 for point in payload["serie"])
    assert payload["metricas"]["modelos"] == ["scikit_learn", "tensorflow_keras", "pytorch"]


def test_generate_forecast_rejects_empty_history():
    class UnusedSession:
        pass

    with pytest.raises(ValueError, match="No hay compras pagadas"):
        generate_forecast(UnusedSession(), data=pd.DataFrame())
