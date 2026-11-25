"""Transactional email rendering and delivery through the Gmail API."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Lock

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import EmailStr, TypeAdapter
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import resolve_runtime_file, settings

logger = logging.getLogger(__name__)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "emails"
_templates = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
_email_adapter = TypeAdapter(EmailStr)
_GMAIL_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]
_credentials_lock = Lock()


def gmail_credentials_path() -> Path:
    return resolve_runtime_file(settings.gmail_credentials_file)


def gmail_token_path() -> Path:
    return resolve_runtime_file(settings.gmail_token_file)


def gmail_is_configured() -> bool:
    """Check both configured paths and Render's /etc/secrets mount."""
    return gmail_credentials_path().is_file() and gmail_token_path().is_file()


def _email_date() -> str:
    """Return the footer date in the company's local timezone."""
    bogota = timezone(timedelta(hours=-5))
    return datetime.now(bogota).strftime("%d/%m/%Y")


def _email_theme() -> dict[str, str]:
    """Choose a readable email palette using the send time in Colombia."""
    bogota_now = datetime.now(timezone(timedelta(hours=-5)))
    if 6 <= bogota_now.hour < 18:
        return {
            "fondo": "#f8f9fa", "tarjeta": "#ffffff", "texto": "#27272a",
            "secundario": "#52525b", "atenuado": "#71717a", "cabecera": "#18181b",
            "texto_cabecera": "#ffffff", "subtitulo": "#d4d4d8", "pie": "#fafafa",
            "borde": "#e4e4e7", "panel": "#f0f3f2", "panel_acento": "#fffbeb",
            "panel_acento_borde": "#fde68a", "panel_acento_texto": "#92400e",
            "alerta": "#fef2f2", "alerta_borde": "#ef4444", "alerta_texto": "#991b1b",
            "alerta_lista": "#7f1d1d",
        }
    return {
        "fondo": "#111827", "tarjeta": "#1f2937", "texto": "#f9fafb",
        "secundario": "#d1d5db", "atenuado": "#9ca3af", "cabecera": "#111827",
        "texto_cabecera": "#ffffff", "subtitulo": "#d1d5db", "pie": "#111827",
        "borde": "#374151", "panel": "#273449", "panel_acento": "#3b321f",
        "panel_acento_borde": "#a16207", "panel_acento_texto": "#fde68a",
        "alerta": "#3b2328", "alerta_borde": "#f87171", "alerta_texto": "#fecaca",
        "alerta_lista": "#fee2e2",
    }


def validate_email_domain(address: str) -> bool:
    """Return whether the domain publishes MX (or fallback A/AAAA) records.

    This cannot establish that a mailbox exists or accepts mail.
    """
    domain = address.rsplit("@", 1)[-1].rstrip(".")
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 3
        resolver.lifetime = 5
        try:
            records = resolver.resolve(domain, "MX")
            # A null MX (exchange='.') explicitly states that the domain
            # does not accept email, even though an MX record exists.
            return any(str(record.exchange).rstrip(".") for record in records)
        except dns.resolver.NoAnswer:
            # RFC 5321 permits implicit MX when the domain itself resolves.
            for record_type in ("A", "AAAA"):
                try:
                    if resolver.resolve(domain, record_type):
                        return True
                except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                    continue
            return False
    except ImportError:
        logger.error("La validación DNS requiere dnspython")
        return False
    except Exception:
        logger.info("El dominio de correo no publicó registros de recepción", exc_info=True)
        return False


def render_email(template: str, **context: object) -> str:
    context.setdefault("fecha_actual", _email_date())
    context.setdefault("tema", _email_theme())
    return _templates.get_template(template).render(**context)


def send_email(to: str, subject: str, html: str, text: str) -> None:
    to = str(_email_adapter.validate_python(to))
    if not validate_email_domain(to):
        raise ValueError("El dominio del correo no tiene un servidor configurado para recibir mensajes")
    credentials_path = gmail_credentials_path()
    token_path = gmail_token_path()
    if not credentials_path.is_file():
        raise RuntimeError(
            "No se encontró el archivo OAuth. En Render, usa GMAIL_CREDENTIALS_FILE=/etc/secrets/credentials.json "
            "o crea un Secret File llamado credentials.json."
        )
    if not token_path.is_file():
        raise RuntimeError("No existe el token OAuth de Gmail. Ejecuta python -m scripts.authorize_gmail")
    try:
        with _credentials_lock:
            credentials = Credentials.from_authorized_user_file(str(token_path), _GMAIL_SCOPE)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                try:
                    token_path.write_text(credentials.to_json(), encoding="utf-8")
                except OSError:
                    # Render secret files are mounted for reading; a refreshed
                    # access token is still valid for this request even when the
                    # source token file cannot be updated.
                    logger.debug("El archivo OAuth es de solo lectura; se usó el token renovado en memoria")
        message = EmailMessage()
        message["To"] = to
        message["From"] = settings.gmail_sender
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = build("gmail", "v1", credentials=credentials, cache_discovery=False).users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        if not result or not result.get("id"):
            raise RuntimeError("Gmail no confirmó la aceptación del correo")
    except Exception as exc:
        error_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        try:
            status = int(error_code)
        except (TypeError, ValueError):
            status = None
        if status in (401, 403):
            logger.error("Gmail rechazó la autorización o el permiso gmail.send (HTTP %s)", status)
        elif status == 429:
            logger.warning("Gmail alcanzó el límite de envío (HTTP 429)")
        elif status in (400, 422):
            logger.warning("Gmail rechazó el mensaje (HTTP %s)", status)
        elif isinstance(exc, (OSError, TimeoutError, ConnectionError)):
            logger.warning("Error de conexión HTTPS con Gmail: %s", type(exc).__name__)
        else:
            logger.error("Falló el envío mediante Gmail (HTTP %s, tipo %s)", status or "desconocido", type(exc).__name__)
        raise


def send_password_reset(to: str, name: str, code: str) -> None:
    html = render_email("password_reset.html", nombre=name or "", codigo=code)
    text = f"Hola {name or ''}, solicitaste recuperar tu contraseña. Tu código es {code}. Vence en 10 minutos. No lo compartas. Si no hiciste esta solicitud, ignora este mensaje."
    send_email(to, "Código de recuperación de contraseña – Costa De Oro Imports", html, text)


def send_welcome(to: str, name: str, role: str, company: str | None = None) -> None:
    html = render_email("welcome.html", nombre=name, tipo_usuario=role, empresa=company, url_login=settings.frontend_url)
    try:
        send_email(to, "¡Bienvenido a Costa De Oro Imports!", html, f"Hola {name}, bienvenido a Costa De Oro Imports. Accede en {settings.frontend_url}")
    except Exception:
        logger.exception("No se pudo enviar el correo de bienvenida")


def send_login_notice(to: str, name: str, occurred_at: str, device: str | None = None, location: str | None = None) -> None:
    html = render_email("login_successful.html", nombre=name, fecha=occurred_at, dispositivo=device or "No disponible", ubicacion=location or "No disponible")
    try:
        send_email(to, "Nuevo inicio de sesión – Costa De Oro Imports", html, f"Hola {name}, registramos un inicio de sesión el {occurred_at}. Dispositivo: {device or 'No disponible'}. Ubicación: {location or 'No disponible'}. Si no lo reconoces, cambia tu contraseña.")
    except Exception as exc:
        if not gmail_is_configured():
            logger.warning(
                "Se omitió el aviso de inicio de sesión: configura GMAIL_CREDENTIALS_FILE "
                "y GMAIL_TOKEN_FILE para habilitar el correo"
            )
        else:
            logger.warning(
                "No se pudo enviar el aviso de inicio de sesión (%s)",
                type(exc).__name__,
            )
