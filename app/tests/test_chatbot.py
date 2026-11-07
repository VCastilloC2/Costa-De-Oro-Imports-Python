from datetime import datetime

from app.core.config import settings
from app.core.security import create_token
from app.models import Categoria, Compra, DetalleVenta, Producto, Usuario
from app.services.chatbot_service import build_business_context
from app.services.gemini_client import GeminiResult


def _seed_admin(db_session, role_id=1, user_id=1):
    admin = Usuario(
        usuario_id=user_id,
        correo=f"admin{user_id}@example.com",
        password="unused",
        rol_id=role_id,
        is_enabled=True,
        account_non_expired=True,
        account_non_locked=True,
        credentials_non_expired=True,
    )
    db_session.add(admin)
    db_session.commit()
    return {"Authorization": f"Bearer {create_token(str(user_id), 'ADMIN')}"}


def _seed_business_data(db_session):
    db_session.add(Categoria(categoria_id=1, nombre="Whisky", descripcion="Bebidas"))
    db_session.add(Producto(
        producto_id=1, nombre="Whisky A", precio=40000, stock=8, activo=True,
        categoria_id=1, marca="Marca A", descripcion="Whisky de prueba",
    ))
    db_session.add(Compra(
        compra_id=1, fecha=datetime(2026, 1, 10), iva=0, subtotal=80000,
        total=80000, estado="PAGADO", usuario_id=1,
    ))
    db_session.add(DetalleVenta(
        detalle_venta_id=1, compra_id=1, producto_id=1,
        cantidad=2, precio_unitario=40000, subtotal=80000,
    ))
    db_session.commit()


def test_chatbot_context_contains_mysql_catalog_and_sales_without_customer_pii(db_session):
    _seed_admin(db_session)
    _seed_business_data(db_session)

    context = build_business_context(db_session)

    assert context["inventario"]["productos_activos"] == 1
    assert context["inventario"]["productos"][0]["nombre"] == "Whisky A"
    assert context["ventas"]["total_pagado"] == 80000
    assert context["ventas"]["productos_mas_vendidos"][0]["unidades_vendidas"] == 2
    assert "correo" not in str(context).lower()
    assert "password" not in str(context).lower()


def test_chatbot_requires_admin_role(client, db_session, seeded_roles, monkeypatch):
    headers = _seed_admin(db_session, role_id=2, user_id=2)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    response = client.post("/admin/chatbot/chat", headers=headers, json={"message": "¿Cuánto vendimos?"})
    assert response.status_code == 403
    assert client.post("/admin/chatbot/chat", json={"message": "Hola"}).status_code == 401


def test_admin_chatbot_uses_mysql_context_and_gemini_reply(client, db_session, seeded_roles, monkeypatch):
    headers = _seed_admin(db_session)
    _seed_business_data(db_session)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    observed = {}

    def fake_gemini(message, context, history):
        observed.update(message=message, context=context, history=history)
        return GeminiResult(text="Las ventas pagadas suman 80.000.", model=settings.gemini_model,
                            finish_reason="STOP",
                            usage={"prompt_tokens": 120, "output_tokens": 12, "total_tokens": 132})

    monkeypatch.setattr("app.api.v1.endpoints.chatbot.generate_chat_response", fake_gemini)
    response = client.post(
        "/admin/chatbot/chat",
        headers=headers,
        json={
            "message": "¿Cuánto se vendió?",
            "history": [{"role": "user", "content": "Hablemos de ventas."}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Las ventas pagadas suman 80.000.",
        "model": settings.gemini_model,
        "source": "database",
        "context_cached": False,
        "finish_reason": "STOP",
        "usage": {"prompt_tokens": 120, "output_tokens": 12, "total_tokens": 132},
    }
    assert observed["context"]["ventas"]["total_pagado"] == 80000
    assert observed["history"][0].content == "Hablemos de ventas."


def test_chatbot_reports_missing_gemini_key(client, db_session, seeded_roles, monkeypatch):
    headers = _seed_admin(db_session)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    response = client.post("/admin/chatbot/chat", headers=headers, json={"message": "Hola"})
    assert response.status_code == 503
