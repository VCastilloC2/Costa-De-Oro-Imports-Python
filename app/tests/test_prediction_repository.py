from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import PrediccionModelo
from app.prediction.repository import register_model, reserve_model_version


def test_model_version_reservation_advances_from_database_after_filesystem_reset(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'registry.db'}")
    PrediccionModelo.__table__.create(engine)
    try:
        with Session(engine) as session:
            session.add(PrediccionModelo(
                nombre="TensorFlow Sales Prediction", version=1, granularidad="monthly",
                estado="ACTIVO", fecha_entrenamiento=datetime(2026, 1, 1),
            ))
            session.commit()
            assert reserve_model_version(session, "monthly", None, minimum_version=1) == 2
            row = session.scalar(select(PrediccionModelo).where(
                PrediccionModelo.granularidad == "monthly", PrediccionModelo.version == 2,
            ))
            assert row.estado == "ENTRENANDO"
    finally:
        engine.dispose()


def test_register_model_completes_reserved_row_instead_of_inserting_duplicate(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'registry.db'}")
    PrediccionModelo.__table__.create(engine)
    metadata = {
        "nombre": "TensorFlow Sales Prediction", "version": 1, "granularidad": "monthly",
        "fecha_entrenamiento": "2026-01-01T12:00:00", "ruta_artefactos": "/tmp/model/v1",
        "entrenamiento": {"epocas_ejecutadas": 5, "loss_entrenamiento_final": 0.1,
                          "loss_validacion_final": 0.2},
        "metricas_preliminares": {"mae": 1.0, "mse": 1.0, "rmse": 1.0,
                                  "mape_percentage": None, "accuracy_percentage": 99.0},
        "preparacion": {"registros_entrenamiento": 10, "registros_validacion": 2,
                        "registros_prueba": 2, "fuente_datos": "database"},
    }
    try:
        with Session(engine) as session:
            assert reserve_model_version(session, "monthly", None) == 1
            model_id = register_model(session, metadata, None)
            rows = list(session.scalars(select(PrediccionModelo)))
            assert len(rows) == 1
            assert rows[0].modelo_id == model_id
            assert rows[0].estado == "ACTIVO"
            assert rows[0].ruta_artefactos == "/tmp/model/v1"
    finally:
        engine.dispose()
