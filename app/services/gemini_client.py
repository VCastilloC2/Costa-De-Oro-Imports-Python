"""Cliente compartido de Gemini Interactions API (google-genai) para asistentes.

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
        # Interactions API acepta input de texto. Serializamos los turnos para
        # conservar el historial que el contrato actual ya recibe desde Flutter.
        conversation = []
        for content in contents:
            role = "Usuario" if content.role == "user" else "Asistente"
            text = " ".join(part.text for part in (content.parts or []) if part.text)
            if text:
                conversation.append(f"{role}: {text}")
        response = client.interactions.create(
            model=model,
            input="\n".join(conversation),
            system_instruction=system_instruction,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens or settings.gemini_max_output_tokens,
                "thinking_level": "low",
            },
            # No guardar datos del negocio en los registros de interacciones.
            store=False,
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

    text = (getattr(response, "output_text", None) or "").strip()
    finish_reason = None
    if not text:
        raise GeminiProviderError("Gemini devolvió una respuesta vacía", 502)
    metadata = getattr(response, "usage", None) or getattr(response, "usage_metadata", None)
    usage = {
        "prompt_tokens": getattr(metadata, "input_tokens", None) or getattr(metadata, "prompt_token_count", None),
        "output_tokens": getattr(metadata, "output_tokens", None) or getattr(metadata, "candidates_token_count", None),
        "total_tokens": getattr(metadata, "total_tokens", None) or getattr(metadata, "total_token_count", None),
    }
    return GeminiResult(text=text, model=getattr(response, "model", None) or model,
                        finish_reason=finish_reason, usage=usage)
