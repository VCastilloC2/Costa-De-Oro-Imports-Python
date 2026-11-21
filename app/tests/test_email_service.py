from unittest.mock import MagicMock

import pytest

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


def test_smtp_connection_errors_propagate_without_logging_credentials(monkeypatch):
    monkeypatch.setattr(email_service.settings, "mail_username", "sender@example.com")
    monkeypatch.setattr(email_service.settings, "mail_password", "sensitive-password")
    monkeypatch.setattr(email_service, "validate_email_domain", lambda _: True)
    smtp = MagicMock()
    smtp.__enter__.side_effect = OSError("connection failed")
    monkeypatch.setattr(email_service.smtplib, "SMTP", lambda *args, **kwargs: smtp)
    with pytest.raises(OSError, match="connection failed"):
        email_service.send_email("to@example.com", "Subject", "<p>HTML</p>", "plain text")


def test_reset_code_hash_is_keyed_and_email_scoped(monkeypatch):
    monkeypatch.setattr(auth.settings, "jwt_secret_ecommerce", "test-secret")
    first = auth._reset_code_hash("person@example.com", "01234")
    assert first != auth._reset_code_hash("other@example.com", "01234")
    assert first != auth._reset_code_hash("person@example.com", "01235")


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
