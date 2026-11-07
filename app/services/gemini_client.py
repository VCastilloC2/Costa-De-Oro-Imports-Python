"""Cliente compartido de Gemini (google-genai) para todos los asistentes de la API.

* Un único ``genai.Client`` por clave de API (se reutilizan conexiones HTTP).
* Tiempo máximo por petición (``GEMINI_TIMEOUT_SECONDS``) y reintentos automáticos del SDK con
  espera exponencial ante 429/5xx (``GEMINI_MAX_RETRIES``).
* Errores traducidos a excepciones propias, con un mensaje apto para el usuario.
* Devuelve el texto, el motivo de finalización y el consumo de tokens.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

from app.core.config import settings

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = [408, 429, 500, 502, 503, 504]
BLOCKED_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY"}


class GeminiNotConfigured(Exception):
    """Falta GEMINI_API_KEY."""


class GeminiProviderError(Exception):
    """Gemini no respondió (red, cuota, 5xx) o devolvió una respuesta vacía."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeminiBlockedError(Exception):
    """La pregunta o la respuesta fueron bloqueadas por los filtros de seguridad."""


@dataclass
class GeminiResult:
    text: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int | None] = field(default_factory=dict)


def is_configured() -> bool:
    return bool(settings.gemini_api_key and settings.gemini_api_key.strip())


_clients: dict[tuple, genai.Client] = {}
_clients_lock = threading.Lock()


def get_client() -> genai.Client:
    if not is_configured():
        raise GeminiNotConfigured("El asistente no está configurado: falta GEMINI_API_KEY")
    key = (settings.gemini_api_key.strip(), settings.gemini_timeout_seconds, settings.gemini_max_retries)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            _clients.clear()  # si cambió la configuración, descarta el cliente anterior
            client = genai.Client(
                api_key=key[0],
                http_options=types.HttpOptions(
                    timeout=int(settings.gemini_timeout_seconds * 1000),  # milisegundos
                    retry_options=types.HttpRetryOptions(
                        attempts=settings.gemini_max_retries + 1, initial_delay=1.0, max_delay=8.0,
                        http_status_codes=RETRYABLE_STATUS,
                    ),
                ),
            )
            _clients[key] = client
        return client


def _enum_name(value) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def generate(
    *,
    system_instruction: str,
    contents: list[types.Content],
    max_output_tokens: int | None = None,
    temperature: float = 0.2,
) -> GeminiResult:
    client = get_client()
    model = settings.gemini_model
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens or settings.gemini_max_output_tokens,
            ),
        )
    except errors.ClientError as exc:
        logger.warning("Gemini rechazó la petición (HTTP %s): %s", exc.code, exc)
        if exc.code == 429:
            raise GeminiProviderError("El asistente recibió demasiadas consultas. Intenta en un minuto.", 503) from exc
        if exc.code in (401, 403):
            raise GeminiProviderError("La clave de Gemini no es válida o no tiene permisos", 503) from exc
        raise GeminiProviderError("Gemini rechazó la consulta", 502) from exc
    except Exception as exc:  # noqa: BLE001 - ServerError, timeouts, red
        logger.exception("Gemini no respondió")
        raise GeminiProviderError("El asistente no está disponible en este momento", 502) from exc

    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise GeminiBlockedError("La consulta fue bloqueada por los filtros de seguridad.")
    candidates = getattr(response, "candidates", None) or []
    finish_reason = _enum_name(getattr(candidates[0], "finish_reason", None)) if candidates else None
    if finish_reason in BLOCKED_REASONS:
        raise GeminiBlockedError("La respuesta fue bloqueada por los filtros de seguridad.")
    try:
        text = (response.text or "").strip()
    except Exception:  # noqa: BLE001 - .text falla si no hay partes de texto
        text = ""
    if not text:
        raise GeminiProviderError("Gemini devolvió una respuesta vacía", 502)
    metadata = getattr(response, "usage_metadata", None)
    usage = {
        "prompt_tokens": getattr(metadata, "prompt_token_count", None),
        "output_tokens": getattr(metadata, "candidates_token_count", None),
        "total_tokens": getattr(metadata, "total_token_count", None),
    }
    return GeminiResult(text=text, model=getattr(response, "model_version", None) or model,
                        finish_reason=finish_reason, usage=usage)
