"""Cliente compartido de Gemini, chat administrativo endurecido y asistente de compras."""
import time
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.core import cache
from app.core.config import settings
from app.core.security import create_token
from app.models import Categoria, Producto, Usuario
from app.services import chatbot_service, gemini_client
from app.services.gemini_client import GeminiBlockedError, GeminiProviderError, GeminiResult

SHOP = "/api/asistente/chat"


class FakeValkey:
    def __init__(self):
        self.data, self.expires = {}, {}

    def get(self, key):
        if key in self.expires and self.expires[key] <= time.monotonic():
            self.data.pop(key, None)
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        if ex:
            self.expires[key] = time.monotonic() + ex
        return True

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key) or 0) + 1)
        return int(self.data[key])

    def expire(self, key, seconds):
        self.expires[key] = time.monotonic() + seconds


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _response(text="Hola", finish="STOP", block=None):
    return SimpleNamespace(
        text=text, model_version="gemini-test-001",
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, total_token_count=15),
    )


@pytest.fixture
def fake_sdk(monkeypatch):
    """Sustituye genai.Client y registra cómo se construye."""
    created = []
    models = FakeModels(_response())

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.models = models

    monkeypatch.setattr(gemini_client.genai, "Client", FakeClient)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    gemini_client._clients.clear()
    yield SimpleNamespace(created=created, models=models)
    gemini_client._clients.clear()


@pytest.fixture
def admin_headers(db_session, seeded_roles):
    db_session.add(Usuario(usuario_id=1, correo="admin@example.com", password="x", rol_id=1, is_enabled=True,
                           account_non_expired=True, account_non_locked=True, credentials_non_expired=True))
    db_session.commit()
    return {"Authorization": f"Bearer {create_token('1', 'ADMIN')}"}


@pytest.fixture
def catalog(db_session):
    db_session.add_all([Categoria(categoria_id=1, nombre="Whisky", descripcion="Whisky"),
                        Categoria(categoria_id=2, nombre="Tequila", descripcion="Tequila")])
    db_session.add_all([
        Producto(producto_id=1, nombre="Johnnie Walker Double Black", precio=180000, precio_regular=200000,
                 stock=3, activo=True, categoria_id=1, marca="Johnnie Walker", pais="Escocia",
                 descripcion="Whisky escocés ahumado", imagen="https://img/jw.png"),
        Producto(producto_id=2, nombre="Tequila Don Julio Reposado", precio=250000, stock=40, activo=True,
                 categoria_id=2, marca="Don Julio", pais="México", descripcion="Tequila reposado"),
        Producto(producto_id=3, nombre="Whisky Retirado", precio=10, stock=9, activo=False, categoria_id=1),
    ])
    db_session.commit()


# ----------------------------------------------------------------------- cliente compartido

def test_client_is_reused_with_timeout_and_retries(fake_sdk, monkeypatch):
    monkeypatch.setattr(settings, "gemini_timeout_seconds", 12.5)
    monkeypatch.setattr(settings, "gemini_max_retries", 3)
    first = gemini_client.generate(system_instruction="s", contents=[])
    gemini_client.generate(system_instruction="s", contents=[])
    assert len(fake_sdk.created) == 1
    options = fake_sdk.created[0]["http_options"]
    assert options.timeout == 12500 and options.retry_options.attempts == 4
    assert 429 in options.retry_options.http_status_codes
    assert first.text == "Hola" and first.finish_reason == "STOP" and first.model == "gemini-test-001"
    assert first.usage == {"prompt_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_quota_errors_and_blocks_are_translated(fake_sdk):
    fake_sdk.models.error = errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    with pytest.raises(GeminiProviderError) as quota:
        gemini_client.generate(system_instruction="s", contents=[])
    assert quota.value.status_code == 503
    fake_sdk.models.error = None
    fake_sdk.models.response = _response(finish="SAFETY")
    with pytest.raises(GeminiBlockedError):
        gemini_client.generate(system_instruction="s", contents=[])
    fake_sdk.models.response = _response(block="SAFETY")
    with pytest.raises(GeminiBlockedError):
        gemini_client.generate(system_instruction="s", contents=[])
    fake_sdk.models.response = _response(text="  ")
    with pytest.raises(GeminiProviderError):
        gemini_client.generate(system_instruction="s", contents=[])


# ----------------------------------------------------------------------- chat administrativo

def test_admin_context_is_cached_in_valkey(client, admin_headers, fake_sdk, monkeypatch):
    fake = FakeValkey()
    monkeypatch.setattr(cache, "get_cache_client", lambda: fake)
    calls = []
    original = chatbot_service.build_business_context
    monkeypatch.setattr(chatbot_service, "build_business_context", lambda db: calls.append(1) or original(db))
    first = client.post("/admin/chatbot/chat", headers=admin_headers, json={"message": "¿Ventas?"}).json()
    second = client.post("/admin/chatbot/chat", headers=admin_headers, json={"message": "¿Stock?"}).json()
    assert len(calls) == 1
    assert first["context_cached"] is False and second["context_cached"] is True
    assert second["usage"]["total_tokens"] == 15


def test_admin_rate_limit_returns_429(client, admin_headers, fake_sdk, monkeypatch):
    monkeypatch.setattr(settings, "chatbot_rate_limit_per_minute", 1)
    assert client.post("/admin/chatbot/chat", headers=admin_headers, json={"message": "a"}).status_code == 200
    blocked = client.post("/admin/chatbot/chat", headers=admin_headers, json={"message": "b"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


def test_admin_blocked_answer_is_422(client, admin_headers, fake_sdk):
    fake_sdk.models.response = _response(finish="SAFETY")
    response = client.post("/admin/chatbot/chat", headers=admin_headers, json={"message": "x"})
    assert response.status_code == 422 and "seguridad" in response.json()["detail"]


def test_status_never_exposes_the_key(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "super-secret")
    body = client.get("/admin/chatbot/status", headers=admin_headers).json()
    assert body["configured"] is True and "super-secret" not in str(body)
    assert client.get("/admin/chatbot/status").status_code == 401


# ----------------------------------------------------------------------- asistente de compras

def test_shop_assistant_is_public_and_suggests_catalog_products(client, catalog, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    seen = {}

    def fake_generate(**kwargs):
        seen.update(kwargs)
        return GeminiResult(text="Te recomiendo el Johnnie Walker Double Black, un whisky escocés.",
                            model="gemini-test", finish_reason="STOP", usage={"total_tokens": 50})

    monkeypatch.setattr(gemini_client, "generate", fake_generate)
    response = client.post(SHOP, json={"message": "Quiero un whisky escocés para regalar"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "catalog"
    assert body["productos"] == [{"producto_id": 1, "nombre": "Johnnie Walker Double Black", "precio": 180000.0,
                                  "precio_antes": 200000.0, "disponibilidad": "pocas_unidades",
                                  "imagen": "https://img/jw.png"}]

    prompt = seen["contents"][-1].parts[0].text
    assert "Johnnie Walker Double Black" in prompt and "Whisky Retirado" not in prompt  # sólo activos
    assert prompt.index("Johnnie Walker") < prompt.index("Don Julio")  # lo relevante primero
    assert '"stock"' not in prompt and "imagen" not in prompt and "https://img" not in prompt
    assert "mayores de 18" in seen["system_instruction"]
    assert seen["max_output_tokens"] == settings.shop_assistant_max_output_tokens


def test_shop_assistant_disabled_or_unconfigured(client, catalog, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    assert client.get("/api/asistente/status").json() == {"available": False}
    assert client.post(SHOP, json={"message": "hola"}).status_code == 503
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(settings, "shop_assistant_enabled", False)
    assert client.post(SHOP, json={"message": "hola"}).status_code == 503
    monkeypatch.setattr(settings, "shop_assistant_enabled", True)
    assert client.get("/api/asistente/status").json()["available"] is True


def test_shop_assistant_limits(client, catalog, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(gemini_client, "generate",
                        lambda **_: GeminiResult(text="Hola", model="m", usage={}))
    monkeypatch.setattr(settings, "shop_assistant_rate_limit_per_minute", 2)
    codes = [client.post(SHOP, json={"message": "hola"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.post(SHOP, json={"message": "x" * 501}).status_code == 422


def test_shop_assistant_daily_cap(client, catalog, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(gemini_client, "generate", lambda **_: GeminiResult(text="Hola", model="m"))
    monkeypatch.setattr(settings, "shop_assistant_daily_limit", 1)
    assert client.post(SHOP, json={"message": "hola"}).status_code == 200
    capped = client.post(SHOP, json={"message": "hola"})
    assert capped.status_code == 429 and "diario" in capped.json()["detail"]
