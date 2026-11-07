"""Isolated SQLite fixtures; tests never connect to the configured production database."""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ["PREDICTION_DATA_SOURCE"] = "csv"
os.environ["PREDICTION_DATASET_CSV"] = str(PROJECT_ROOT / "app" / "prediction" / "data" / "costa_de_oro_ventas.csv")
os.environ.pop("VALKEY_URL", None)
os.environ.pop("REDIS_URL", None)

from app.core.database import Base, get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.cache import get_cache_client  # noqa: E402
from app.main import app  # noqa: E402

settings.valkey_url = None
get_cache_client.cache_clear()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.core import rate_limit
    rate_limit.reset_local()
    yield


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = testing_session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def seeded_roles(db_session):
    from app.models import Rol
    db_session.add_all([Rol(rol_id=1, rol="ADMIN"), Rol(rol_id=2, rol="PERSONA_NATURAL")])
    db_session.commit()
    return {"ADMIN": 1, "PERSONA_NATURAL": 2}
