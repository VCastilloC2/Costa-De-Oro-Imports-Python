# Asistentes con Gemini

La API usa Google Gemini (`google-genai`) en dos asistentes que comparten un mismo cliente:

| Asistente | Endpoint | Quién | Datos que ve Gemini |
|---|---|---|---|
| Chatbot administrativo | `POST /admin/chatbot/chat` | JWT con rol `ADMIN` | Resumen agregado de MySQL: inventario, ventas por mes, más vendidos, totales. Sin datos personales |
| Asistente de compras | `POST /api/asistente/chat` | Público (sin sesión) | Sólo el catálogo **activo**: nombre, categoría, marca, país, precio, disponibilidad aproximada y descripción corta |

| Archivo | Responsabilidad |
|---|---|
| `app/services/gemini_client.py` | Cliente compartido: reutilización, timeout, reintentos, errores, tokens |
| `app/services/chatbot_service.py` | Resumen de MySQL (con caché en Valkey) y chat administrativo |
| `app/services/shop_assistant_service.py` | Catálogo (con caché), selección de productos relevantes, sugerencias |
| `app/core/rate_limit.py` | Límite de peticiones (Valkey, con memoria local como respaldo) |
| `app/api/v1/endpoints/chatbot.py` | Endpoints |
| `app/schemas/chat.py` | Contratos JSON |

## 1. Configuración

```env
GEMINI_API_KEY=                     # obligatorio; sin él los endpoints responden 503
GEMINI_MODEL=gemini-3.8-flash
GEMINI_TIMEOUT_SECONDS=30           # tiempo máximo por intento
GEMINI_MAX_RETRIES=2                # reintentos con espera exponencial ante 408/429/5xx
GEMINI_MAX_OUTPUT_TOKENS=800        # chat administrativo
CHATBOT_CONTEXT_CACHE_SECONDS=60    # reutiliza el resumen de MySQL (0 = siempre consulta)
CHATBOT_RATE_LIMIT_PER_MINUTE=20    # por administrador
SHOP_ASSISTANT_ENABLED=true
SHOP_ASSISTANT_RATE_LIMIT_PER_MINUTE=10   # por IP
SHOP_ASSISTANT_DAILY_LIMIT=2000           # global por día (controla el costo)
SHOP_ASSISTANT_MAX_OUTPUT_TOKENS=500
```

Sin `VALKEY_URL`, las cachés se desactivan y los límites se cuentan en la memoria de cada proceso.

## 2. Endpoints

### `GET /admin/chatbot/status` (ADMIN)

Muestra la configuración y no consume tokens. Nunca devuelve la clave.

```json
{ "configured": true, "model": "gemini-3.8-flash", "timeout_seconds": 30.0, "max_retries": 2,
  "context_cache_seconds": 60, "admin_rate_limit_per_minute": 20, "shop_assistant_enabled": true,
  "shop_rate_limit_per_minute": 10, "shop_daily_limit": 2000 }
```

### `POST /admin/chatbot/chat` (ADMIN)

Entrada (`history`: hasta 12 turnos, `role` = `user` o `model`):

```json
{ "message": "¿Qué productos tienen menos stock?",
  "history": [ { "role": "user", "content": "Hablemos de inventario." },
               { "role": "model", "content": "Claro, ¿qué quieres saber?" } ] }
```

Salida (los campos nuevos son opcionales; `answer`, `model` y `source` no cambian):

```json
{ "answer": "Los productos con menos stock son…", "model": "gemini-3.8-flash", "source": "database",
  "context_cached": true, "finish_reason": "STOP",
  "usage": { "prompt_tokens": 1450, "output_tokens": 120, "total_tokens": 1570 } }
```

`finish_reason: "MAX_TOKENS"` indica que la respuesta se cortó; sube `GEMINI_MAX_OUTPUT_TOKENS`.

### `GET /api/asistente/status` (público)

`{ "available": true, "model": "gemini-3.8-flash" }`. La app puede ocultar el botón del asistente si `available` es `false`.

### `POST /api/asistente/chat` (público)

Entrada (`message` ≤ 500 caracteres; `history` ≤ 8 turnos de ≤ 1000):

```json
{ "message": "¿Qué whisky escocés me recomiendas para regalar?", "history": [] }
```

Salida: `productos` trae los artículos del catálogo que la respuesta menciona por nombre, para que la app los muestre como tarjetas y enlace a `GET /api/productos/{producto_id}`.

```json
{
  "answer": "Te recomiendo Johnnie Walker Double Black (COP 180.000)…",
  "model": "gemini-3.8-flash",
  "source": "catalog",
  "productos": [
    { "producto_id": 1, "nombre": "Johnnie Walker Double Black", "precio": 180000.0,
      "precio_antes": 200000.0, "disponibilidad": "pocas_unidades", "imagen": "https://…" }
  ],
  "finish_reason": "STOP",
  "usage": { "prompt_tokens": 2100, "output_tokens": 90, "total_tokens": 2190 }
}
```

`disponibilidad` puede ser `disponible`, `pocas_unidades` (5 o menos) o `agotado`. El stock exacto nunca se envía a Gemini ni a la app.

### Errores (`{"detail": "mensaje"}`)

| HTTP | Causa |
|---|---|
| 401 / 403 | Sin JWT o sin rol ADMIN (sólo chat administrativo) |
| 422 | Mensaje inválido, o pregunta/respuesta bloqueada por los filtros de seguridad |
| 429 | Límite por minuto o diario; la cabecera `Retry-After` indica los segundos de espera |
| 502 | Gemini devolvió un error o una respuesta vacía |
| 503 | Falta `GEMINI_API_KEY`, el asistente está desactivado, se agotó la cuota de Gemini o falló MySQL |

## 3. Seguridad y costo

- **Inyección de instrucciones:** el resumen, el catálogo y el historial viajan marcados como datos, no como instrucciones, y las instrucciones del sistema prohíben seguir lo que aparezca dentro de ellos.
- **Datos mínimos:** el chat administrativo sólo recibe agregados. El asistente público sólo recibe productos activos, sin stock exacto, sin ventas y sin clientes.
- **Venta de alcohol:** el asistente de compras sólo recomienda a mayores de 18 años, promueve el consumo responsable y no da consejos médicos.
- **Costo:** límites por usuario o IP y un tope diario global para el endpoint público. El catálogo enviado se limita a los 60 productos más relevantes para la pregunta, y la respuesta reporta los tokens usados.
- **Solo lectura:** ningún asistente puede modificar la base de datos ni crear pedidos.
