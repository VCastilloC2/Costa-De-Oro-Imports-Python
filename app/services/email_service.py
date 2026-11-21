"""Transactional email rendering, address-domain checks, and SMTP delivery."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import EmailStr, TypeAdapter

from app.core.config import settings

logger = logging.getLogger(__name__)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "emails"
_templates = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
_email_adapter = TypeAdapter(EmailStr)


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
    return _templates.get_template(template).render(**context)


def send_email(to: str, subject: str, html: str, text: str) -> None:
    if not settings.mail_username or not settings.mail_password or not settings.mail_host:
        raise RuntimeError("SMTP no está configurado")
    to = str(_email_adapter.validate_python(to))
    if not validate_email_domain(to):
        raise ValueError("El dominio del destinatario no publica registros de recepción de correo")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.mail_from_name, settings.mail_from or settings.mail_username))
    message["To"] = to
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    try:
        if settings.mail_ssl_tls:
            with smtplib.SMTP_SSL(settings.mail_host, settings.mail_port, timeout=10, context=ssl.create_default_context()) as smtp:
                smtp.login(settings.mail_username, settings.mail_password)
                refused = smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=10) as smtp:
                smtp.ehlo()
                if settings.mail_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(settings.mail_username, settings.mail_password)
                refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except smtplib.SMTPRecipientsRefused:
        logger.warning("El servidor SMTP rechazó el destinatario")
        raise
    except smtplib.SMTPAuthenticationError:
        logger.error("Falló la autenticación del servidor SMTP")
        raise
    except smtplib.SMTPServerDisconnected:
        logger.exception(
            "El servidor SMTP cerró la conexión durante el envío; verifica MAIL_HOST, MAIL_PORT, "
            "MAIL_STARTTLS/MAIL_SSL_TLS y las credenciales SMTP (sin registrar la contraseña)"
        )
        raise
    except (smtplib.SMTPException, OSError, TimeoutError):
        logger.exception("Falló el envío SMTP")
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
