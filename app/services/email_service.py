"""Transactional email rendering and delivery through the Resend HTTPS API."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import EmailStr, TypeAdapter
import resend

from app.core.config import settings

logger = logging.getLogger(__name__)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "emails"
_templates = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
_email_adapter = TypeAdapter(EmailStr)


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
            return bool(resolver.resolve(domain, "MX"))
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
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY no está configurada")
    if not settings.mail_from:
        raise RuntimeError("MAIL_FROM no está configurado")
    to = str(_email_adapter.validate_python(to))
    resend.api_key = settings.resend_api_key
    try:
        result = resend.Emails.send({
            "from": settings.mail_from,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        })
        # The SDK raises ResendError for HTTP/API failures. Guard against unexpected
        # response shapes so a failed request is never reported as delivered.
        if not result or not (result.get("id") if isinstance(result, dict) else getattr(result, "id", None)):
            raise RuntimeError("Resend no confirmó la aceptación del correo")
    except Exception as exc:
        error_code = getattr(exc, "code", None)
        try:
            status = int(getattr(exc, "status_code", None) or error_code)
        except (TypeError, ValueError):
            status = None
        error_type = str(getattr(exc, "error_type", "") or "").lower()
        error_name = type(exc).__name__.lower()
        if status == 401 or "api_key" in error_type or "api_key" in error_name or "unauthorized" in error_type:
            logger.error("Resend rechazó la autenticación (HTTP %s)", status or "desconocido")
        elif status == 429 or "rate" in error_type or "rate" in error_name:
            logger.warning("Resend alcanzó el límite de envío (HTTP %s)", status or "desconocido")
        elif status in (400, 422) or "recipient" in error_type or "email_invalid" in error_type:
            logger.warning("Resend rechazó los datos del correo (HTTP %s)", status or "desconocido")
        elif isinstance(exc, (OSError, TimeoutError, ConnectionError)):
            logger.warning("Error de conexión HTTPS con Resend: %s", type(exc).__name__)
        else:
            logger.error("Falló el envío mediante Resend (HTTP %s, tipo %s)", status or "desconocido", type(exc).__name__)
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
    except Exception:
        logger.exception("No se pudo enviar el aviso de inicio de sesión")
