from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.endpoints import auth
from app.services import email_service


def test_reset_codes_are_five_digits_including_zero_padding(monkeypatch):
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: 7)
    assert auth._generate_reset_code() == "00007"


@pytest.mark.parametrize("template,context,expected", [
    ("password_reset.html", {"nombre": "Ana", "codigo": "01234"}, "01234"),
    ("welcome.html", {"nombre": "Ana", "tipo_usuario": "PERSONA_NATURAL", "empresa": None, "url_login": "https://example.com"}, "PERSONA_NATURAL"),
    ("login_successful.html", {"nombre": "Ana", "fecha": "21/11/2026 10:00 UTC", "dispositivo": "No disponible", "ubicacion": "No disponible"}, "No disponible"),
])
def test_email_templates_render(template, context, expected):
    rendered = email_service.render_email(template, **context)
    assert expected in rendered
    assert "th:text" not in rendered


def test_welcome_template_omits_empty_company():
    rendered = email_service.render_email("welcome.html", nombre="Ana", tipo_usuario="INVITADO", empresa=None, url_login="https://example.com")
    assert "Empresa asociada" not in rendered


def test_email_format_is_validated_before_delivery():
    with pytest.raises(ValueError):
        email_service._email_adapter.validate_python("malformed-address")


def test_domain_mx_validation(monkeypatch):
    import dns.resolver

    resolver = MagicMock()
    resolver.resolve.return_value = ["mx.example.com"]
    monkeypatch.setattr(dns.resolver, "Resolver", lambda: resolver)
    assert email_service.validate_email_domain("person@example.com") is True
    resolver.resolve.assert_called_once_with("example.com", "MX")


def _configure_resend(monkeypatch):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test_secret")
    monkeypatch.setattr(email_service.settings, "mail_from", "Costa De Oro <sender@example.com>")


def test_resend_sends_html_and_text_over_sdk(monkeypatch):
    _configure_resend(monkeypatch)
    send = MagicMock(return_value={"id": "email-id"})
    monkeypatch.setattr(email_service.resend.Emails, "send", send)
    email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")
    assert email_service.resend.api_key == "re_test_secret"
    send.assert_called_once_with({"from": "Costa De Oro <sender@example.com>", "to": ["to@example.com"], "subject": "Subject", "html": "<p>HTML</p>", "text": "plain text"})


@pytest.mark.parametrize("address", ["malformed-address", "bad@"])
def test_invalid_recipient_is_rejected_before_resend(monkeypatch, address):
    _configure_resend(monkeypatch)
    send = MagicMock()
    monkeypatch.setattr(email_service.resend.Emails, "send", send)
    with pytest.raises(ValueError):
        email_service.send_email(address, "Subject", "<p>HTML</p>", "plain text")
    send.assert_not_called()


@pytest.mark.parametrize("error", [OSError("connection failed"), TimeoutError("timeout")])
def test_resend_connection_errors_propagate(monkeypatch, error):
    _configure_resend(monkeypatch)
    monkeypatch.setattr(email_service.resend.Emails, "send", MagicMock(side_effect=error))
    with pytest.raises(type(error)):
        email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_resend_http_errors_propagate_without_sensitive_logging(monkeypatch, caplog, status):
    _configure_resend(monkeypatch)
    error = RuntimeError("sensitive response details")
    error.code = str(status)
    monkeypatch.setattr(email_service.resend.Emails, "send", MagicMock(side_effect=error))
    with pytest.raises(RuntimeError):
        email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")
    assert "sensitive response details" not in caplog.text


def test_resend_error_types_are_classified_without_logging_provider_message(monkeypatch, caplog):
    _configure_resend(monkeypatch)
    error = RuntimeError("private provider detail")
    error.code = "invalid_api_key"
    error.error_type = "invalid_api_key"
    monkeypatch.setattr(email_service.resend.Emails, "send", MagicMock(side_effect=error))
    with pytest.raises(RuntimeError):
        email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")
    assert "rechazó la autenticación" in caplog.text
    assert "private provider detail" not in caplog.text


def test_resend_missing_confirmation_is_an_error(monkeypatch):
    _configure_resend(monkeypatch)
    monkeypatch.setattr(email_service.resend.Emails, "send", MagicMock(return_value={}))
    with pytest.raises(RuntimeError, match="no confirmó"):
        email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")


def test_welcome_and_login_notifications_keep_templates_and_swallow_delivery_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(email_service, "send_email", lambda *args: calls.append(args) or (_ for _ in ()).throw(RuntimeError("failed")))
    email_service.send_welcome("to@example.com", "Ana", "ADMIN")
    email_service.send_login_notice("to@example.com", "Ana", "now")
    assert len(calls) == 2
    assert "Bienvenido" in calls[0][1]
    assert "inicio de sesión" in calls[1][1]


def test_reset_code_hash_is_keyed_and_email_scoped(monkeypatch):
    from app.api.v1.endpoints import auth

    monkeypatch.setattr(auth.settings, "jwt_secret_ecommerce", "test-secret")
    first = auth._reset_code_hash("person@example.com", "01234")
    assert first != auth._reset_code_hash("other@example.com", "01234")
    assert first != auth._reset_code_hash("person@example.com", "01235")


def test_password_reset_delivery_failure_returns_502_and_discards_otp(monkeypatch):
    user = SimpleNamespace(nombres="Ana", is_enabled=True, account_non_locked=True,
                           account_non_expired=True, credentials_non_expired=True)
    deleted = []
    monkeypatch.setattr(auth.settings, "valkey_url", "redis://test")
    monkeypatch.setattr(auth.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(auth.settings, "mail_from", "sender@example.com")
    monkeypatch.setattr(auth, "cache_set_json_if_absent", lambda *_: True)
    monkeypatch.setattr(auth, "cache_set_json", lambda *_: True)
    monkeypatch.setattr(auth, "cache_delete", deleted.append)
    monkeypatch.setattr(auth, "send_password_reset", lambda *_: (_ for _ in ()).throw(RuntimeError("provider error")))
    monkeypatch.setattr(auth, "_generate_reset_code", lambda: "01234")

    class Database:
        def scalar(self, _query):
            return user

    request = Request({"type": "http", "method": "POST", "path": "/auth/password/forgot",
                       "headers": [], "client": ("127.0.0.1", 1234), "server": ("test", 80), "scheme": "http"})
    with pytest.raises(HTTPException) as exc:
        auth.request_password_reset(auth.PasswordResetRequest(correo="person@example.com"), request, Database())
    assert exc.value.status_code == 502
    assert auth._reset_email_key("person@example.com") in deleted


def test_wrong_reset_attempts_preserve_remaining_ttl_and_lock_after_five(monkeypatch):
    state = {"hash": auth._reset_code_hash("person@example.com", "01234"), "attempts": 3}
    ttl = 180
    deleted = []
    monkeypatch.setattr(auth, "cache_get_json", lambda _: state)
    monkeypatch.setattr(auth, "cache_ttl", lambda _: ttl)
    monkeypatch.setattr(auth, "cache_set_json", lambda _key, value, _ttl: state.update(value) or True)
    monkeypatch.setattr(auth, "cache_delete", lambda key: deleted.append(key))

    assert auth._valid_reset_code("person@example.com", "99999") is False
    assert state["attempts"] == 4
    assert auth._valid_reset_code("person@example.com", "99999") is False
    assert deleted == [auth._reset_email_key("person@example.com")]


def test_reset_code_rejects_missing_or_expired_cache_entry(monkeypatch):
    monkeypatch.setattr(auth, "cache_get_json", lambda _: None)
    assert auth._valid_reset_code("person@example.com", "01234") is False


def test_registration_rejects_email_already_cached_in_valkey(monkeypatch):
    from app.core.cache import credential_cache_key

    email = "person@example.com"
    monkeypatch.setattr(auth, "cache_get_json", lambda key: {"usuario_id": 8} if key == credential_cache_key(email) else None)

    class Database:
        def scalar(self, _query):
            raise AssertionError("MySQL need not be queried after a Valkey hit")

    assert auth._email_already_registered(Database(), email.upper()) is True


def test_registration_falls_back_to_mysql_when_email_is_not_cached(monkeypatch):
    monkeypatch.setattr(auth, "cache_get_json", lambda _: None)

    class Database:
        def scalar(self, _query):
            return 24

    assert auth._email_already_registered(Database(), "person@example.com") is True


def test_user_phone_column_is_not_unique_but_email_remains_unique():
    from app.models import Usuario

    assert Usuario.__table__.c.telefono.unique is not True
    assert Usuario.__table__.c.correo.unique is True
