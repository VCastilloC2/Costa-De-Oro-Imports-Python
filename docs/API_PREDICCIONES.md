# API de Predicciones de Ventas — Costa De Oro Imports

Servicio de Machine Learning (TensorFlow/Keras) expuesto como API REST en FastAPI. Cualquier
aplicación capaz de enviar HTTP y leer JSON (Flutter, Spring Boot, Java, Python, Node.js, React,
Angular, apps móviles u otros servicios REST) puede consumirlo **sin instalar TensorFlow** ni conocer la
red neuronal.

- Swagger UI: `GET /doc` · OpenAPI JSON: `GET /v3/api-docs` · ReDoc: `GET /redoc`
- Prefijo: `/api/v1/predictions`

## 1. Arquitectura

```text
                  API DE PREDICCIONES
                       FASTAPI
                          |
              ------------------------
              |                      |
         API REST                TensorFlow
              |                      |
   app/api/v1/endpoints/        Modelo Keras (.keras)
      predictions.py            + scaler (.joblib)
              |                      |
   PredictionService  <---------  ModelStore (versiones)
   TrainingService
              |
   MySQL: compras/detalle_venta (histórico)
          prediccion_* (historial, modelos, evaluaciones, API Keys, accesos)
              |
       Respuesta JSON
              |
    ---------------------------
    |           |             |
  Flutter   Spring Boot   Otra API
```

| Fase | Módulo | Responsabilidad |
|---|---|---|
| 1. Preparación y validación | `app/prediction/preparation.py` | Extracción MySQL, limpieza, nulos, duplicados, atípicos (IQR con límites de entrenamiento), agrupación por período, variables temporales y rezagadas, partición cronológica 70/15/15, validación y resumen |
| 2. Transformación | `app/prediction/transformation.py` | Matrices X/Y float32, `StandardScaler` ajustado sólo con entrenamiento, orden de variables persistido, transformación idéntica en predicción |
| 3. Modelado | `app/prediction/tf_model.py` | Entrada → Dense(16, ReLU) → Dense(8, ReLU) → Dense(1, Linear); Adam, MSE, MAE, EarlyStopping |
| 4. Entrenamiento | `app/prediction/training_service.py` | Operación independiente, sólo ADMIN, un entrenamiento a la vez, registro de épocas/pérdidas/versión/fecha |
| 5. Métricas preliminares | `app/prediction/evaluation.py` | MAE, MSE, RMSE, MAPE, % de acierto aproximado sobre el conjunto de prueba |
| 6. Integración | `app/prediction/prediction_service.py` | Carga modelo + scaler, valida, transforma, ejecuta TensorFlow, variación %, métricas, historial |
| Persistencia | `app/prediction/artifacts.py`, `app/prediction/repository.py` | Artefactos versionados en disco; historial y registro en MySQL |

### Prevención de fuga de información (data leakage)

- Las variables históricas (`ventas_lag_N`, medias y desviaciones móviles) se calculan con `shift(1)`: cada fila sólo ve períodos anteriores.
- Las variables que sólo se conocen al cerrar el período (número de compras, unidades) se **excluyen** como predictoras.
- La partición es cronológica (entrenamiento < validación < prueba), sin mezclar (`shuffle=False`).
- `StandardScaler` y los límites de atípicos se ajustan **sólo** con el conjunto de entrenamiento.
- El período en curso (incompleto) se descarta.

### Granularidades y períodos

| Granularidad | Períodos válidos | Requisitos |
|---|---|---|
| `daily` | `7_days`, `14_days`, `30_days` | Fechas exactas (MySQL) |
| `weekly` | `4_weeks`, `8_weeks`, `12_weeks` | Fechas exactas (MySQL) |
| `monthly` | `1_month`, `3_months`, `6_months`, `12_months` | MySQL o CSV de respaldo |

Cada granularidad tiene su propio modelo; entrena la que vayas a consumir. El CSV de respaldo sólo
tiene año y mes, por eso con él sólo se puede entrenar `monthly`.

## 2. Puesta en marcha

1. Crea las tablas nuevas (no modifican las existentes):
   ```bash
   mysql -u <usuario> -p db_beer < app/prediction/sql/ml_tables.sql
   ```
   o bien `python -m app.prediction.scripts_pred --create-ml-tables`.
2. Configura en `.env` (ver `.env.example`): `PREDICTION_MODEL_DIR`, `PREDICTION_ALLOWED_ROLES`,
   `PREDICTION_MAX_CONCURRENT`, `PREDICTION_INFERENCE_TIMEOUT_SECONDS`, `PREDICTION_DEDUP_WINDOW_SECONDS`.
3. Entrena (ADMIN): `POST /api/v1/predictions/model/train` o
   `python -m app.prediction.scripts_pred --train-tf --granularity monthly`.
4. Genera predicciones: `POST /api/v1/predictions/generate`.

> **Despliegues serverless (Vercel):** el sistema de archivos es efímero y los hilos de fondo no
> sobreviven a la respuesta. Usa `"wait": true` al entrenar y apunta `PREDICTION_MODEL_DIR` a un
> almacenamiento persistente, o entrena en un servidor con disco persistente (Render, VM, contenedor).

## 3. Endpoints

| Método | Ruta | Autenticación | Descripción |
|---|---|---|---|
| GET | `/health` | Pública | Disponibilidad y si existe algún modelo entrenado |
| GET | `/model/status` | JWT o API Key (`predictions:read`) | TensorFlow, modelos activos, entrenamiento en curso |
| GET | `/model/metrics?granularity=monthly` | JWT o API Key (`predictions:read`) | Métricas preliminares, entrenamiento, preparación y última evaluación posterior |
| GET | `/model/versions?granularity=monthly` | JWT o API Key (`predictions:read`) | Versiones entrenadas |
| POST | `/model/train` | **JWT ADMIN** | Entrena una nueva versión (202 asíncrono o 200 con `wait=true`) |
| GET | `/model/train/status` | **JWT ADMIN** | Estado, épocas y pérdidas del entrenamiento |
| POST | `/model/evaluate` | **JWT ADMIN** | Reevaluación preliminar + evaluación posterior persistida |
| POST | `/generate` | JWT o API Key (`predictions:generate`) | Genera una predicción |
| GET | `/summary` | JWT o API Key (`predictions:read`) | Resumen para pantallas (modelos + últimas predicciones) |
| GET | `/history?offset=0&limit=20` | JWT o API Key (`predictions:read`) | Historial paginado |
| GET | `/statistics` | JWT o API Key (`predictions:read`) | Estadísticas del historial |
| GET | `/compare?granularity=monthly` | JWT o API Key (`predictions:read`) | Predicciones vs. ventas reales (métricas posteriores) |
| GET | `/{prediction_id}` | JWT o API Key (`predictions:read`) | Detalle de una predicción |
| POST/GET/DELETE | `/clients` | **JWT ADMIN** | Emitir, listar y revocar API Keys |
| POST | `/demand` | JWT ADMIN | Ruta previa (ensamble); se mantiene por compatibilidad con Flutter |

### Contrato de respuesta

```json
{ "success": true, "message": "Predicción generada correctamente", "data": { } }
```

Errores:

```json
{ "success": false, "message": "No hay un modelo entrenado para la granularidad 'daily'...",
  "error": { "code": "MODEL_NOT_TRAINED", "details": null } }
```

| HTTP | `error.code` | Causa |
|---|---|---|
| 401 | `UNAUTHORIZED` | Sin credencial, JWT expirado o API Key inválida/revocada |
| 403 | `FORBIDDEN` | Rol o permiso insuficiente (p. ej. API Key intentando entrenar) |
| 404 | `NOT_FOUND` | Predicción o cliente inexistente |
| 409 | `MODEL_NOT_TRAINED` / `TRAINING_IN_PROGRESS` | No hay modelo / ya hay un entrenamiento |
| 422 | `VALIDATION_ERROR` / `INVALID_DATA` | Solicitud inválida / datos insuficientes (`details` trae el resumen de la Fase 1) |
| 429 | `SERVICE_BUSY` | Demasiadas inferencias simultáneas |
| 503 | `HISTORY_UNAVAILABLE` / `TENSORFLOW_UNAVAILABLE` | Tablas ML no creadas / TensorFlow no instalado |
| 504 | `INFERENCE_TIMEOUT` | Se superó `PREDICTION_INFERENCE_TIMEOUT_SECONDS` |

### Generar una predicción

Solicitud:

```json
{ "period": "3_months", "prediction_type": "sales", "granularity": "monthly" }
```

Campos opcionales: `data_source` (`auto` | `database` | `csv`, por defecto `auto`) y
`save_history` (por defecto `true`). Cabecera opcional `Idempotency-Key` para reintentos seguros.

Respuesta (estructura; los valores dependen de tus datos reales):

```json
{
  "success": true,
  "message": "Predicción generada correctamente",
  "data": {
    "prediction_id": 1,
    "duplicated": false,
    "registered": true,
    "model": { "name": "TensorFlow Sales Prediction", "version": "v1", "granularity": "monthly",
               "trained_at": "...", "framework": "TensorFlow 2.x", "architecture": [ ], "features": [ ] },
    "forecast": { "period": "3_months", "granularity": "monthly", "start_date": "...", "end_date": "...",
                  "predicted_sales": 0.0, "currency": "COP", "previous_period_sales": 0.0,
                  "variation_percentage": 0.0, "breakdown": [ { "period_start": "...", "period_end": "...", "predicted_sales": 0.0 } ] },
    "performance": { "metric_type": "PRELIMINAR", "mae": 0.0, "mse": 0.0, "rmse": 0.0,
                     "mape_percentage": 0.0, "accuracy_percentage": 0.0, "evaluated_samples": 0 },
    "prediction_variables": [ { "name": "ventas_lag_1", "value": 0.0, "description": "..." } ],
    "history": { "data_source": "database", "last_complete_period": "...", "periods_available": 0 },
    "generated_at": "..."
  }
}
```

### Métricas: preliminares vs. posteriores

- **PRELIMINAR**: se calculan al entrenar sobre el conjunto de prueba (períodos que la red nunca vio),
  prediciendo un paso adelante con las ventas reales como rezagos. Un pronóstico de varios períodos
  encadena sus propias estimaciones, por lo que su error real suele ser mayor.
- **POSTERIOR**: `GET /compare` (sólo lectura) y `POST /model/evaluate` (persiste) comparan cada
  predicción del historial con las ventas reales una vez que su período terminó.
- `accuracy_percentage = max(0, 100 − MAPE)`; es aproximado. Si no hay muestras suficientes los campos
  son `null`: el servicio nunca rellena métricas que no pudo calcular.

## 4. Seguridad

- **Usuarios** (Flutter, paneles web): JWT de `POST /auth/login` en `Authorization: Bearer <token>`.
  Roles permitidos para consultar/generar: `PREDICTION_ALLOWED_ROLES` (por defecto `ADMIN`).
- **Integraciones entre sistemas** (Spring Boot, Node.js…): API Key de servicio en `X-API-Key`.
  Un ADMIN la emite con `POST /api/v1/predictions/clients` indicando permisos `predictions:read`
  y/o `predictions:generate`. La clave se muestra una sola vez; sólo se guarda su hash SHA-256.
  Revócala con `DELETE /api/v1/predictions/clients/{id}`.
- **Entrenar, evaluar y gestionar API Keys** exige siempre un JWT de ADMIN; las API Keys nunca pueden.
- Todas las solicitudes autenticadas se registran (log + tabla `prediccion_acceso`).
- No incluyas API Keys en apps Flutter/móviles ni en el repositorio: la app móvil usa el JWT del usuario;
  las API Keys viven en el backend del cliente (variables de entorno o gestor de secretos).

Emitir una API Key (como ADMIN):

```bash
curl -X POST "$PREDICCION_API_URL/api/v1/predictions/clients" \
  -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" \
  -d '{"name": "erp-spring-boot", "scopes": ["predictions:read", "predictions:generate"]}'
```

## 5. Disponibilidad y rendimiento

- El modelo se carga una vez y queda en memoria por versión; nunca se reentrena al predecir.
- `PREDICTION_MAX_CONCURRENT` limita inferencias simultáneas (429 si se satura) y
  `PREDICTION_INFERENCE_TIMEOUT_SECONDS` acota cada inferencia (504).
- Solicitudes idénticas dentro de `PREDICTION_DEDUP_WINDOW_SECONDS` devuelven la predicción ya
  registrada (`duplicated: true`); con `Idempotency-Key` la deduplicación es por clave.
- Un único entrenamiento a la vez, incluso con varios workers (archivo de bloqueo en `PREDICTION_MODEL_DIR`).
- `GET /api/v1/predictions/health` sirve para balanceadores y monitores.

## 6. Ejemplos de consumo

Todos los clientes usan el mismo endpoint y el mismo contrato JSON. La URL base se configura con la
variable de entorno `PREDICCION_API_URL` y la credencial con `PREDICCION_API_KEY`.

### Java / Spring Boot (WebClient)

`application.yml`:

```yaml
prediccion:
  api:
    base-url: ${PREDICCION_API_URL}
    key: ${PREDICCION_API_KEY}
    timeout-seconds: 35
```

DTOs (Jackson):

```java
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;
import java.util.List;

public record GeneratePredictionRequest(
        String period,
        @JsonProperty("prediction_type") String predictionType,
        String granularity) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record ApiResponse<T>(boolean success, String message, T data) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record ApiError(boolean success, String message, ErrorDetail error) {
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ErrorDetail(String code, Object details) {}
}

@JsonIgnoreProperties(ignoreUnknown = true)
public record PredictionData(
        @JsonProperty("prediction_id") Long predictionId,
        boolean duplicated,
        ModelInfo model,
        Forecast forecast,
        Performance performance,
        @JsonProperty("prediction_variables") List<PredictionVariable> predictionVariables,
        @JsonProperty("generated_at") String generatedAt) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record ModelInfo(String name, String version, String granularity,
                        @JsonProperty("trained_at") String trainedAt) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record Forecast(String period, String granularity,
                       @JsonProperty("start_date") String startDate,
                       @JsonProperty("end_date") String endDate,
                       @JsonProperty("predicted_sales") BigDecimal predictedSales,
                       String currency,
                       @JsonProperty("previous_period_sales") BigDecimal previousPeriodSales,
                       @JsonProperty("variation_percentage") BigDecimal variationPercentage) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record Performance(@JsonProperty("metric_type") String metricType,
                          BigDecimal mae, BigDecimal mse, BigDecimal rmse,
                          @JsonProperty("mape_percentage") BigDecimal mapePercentage,
                          @JsonProperty("accuracy_percentage") BigDecimal accuracyPercentage,
                          @JsonProperty("evaluated_samples") Integer evaluatedSamples) {}

@JsonIgnoreProperties(ignoreUnknown = true)
public record PredictionVariable(String name, BigDecimal value, String description) {}
```

Cliente:

```java
import java.time.Duration;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@Service
public class PrediccionClient {
    private final WebClient webClient;
    private final Duration timeout;

    public PrediccionClient(WebClient.Builder builder,
                            @Value("${prediccion.api.base-url}") String baseUrl,
                            @Value("${prediccion.api.key}") String apiKey,
                            @Value("${prediccion.api.timeout-seconds:35}") long timeoutSeconds) {
        this.webClient = builder.baseUrl(baseUrl)
                .defaultHeader("X-API-Key", apiKey)
                .defaultHeader("Accept", MediaType.APPLICATION_JSON_VALUE)
                .build();
        this.timeout = Duration.ofSeconds(timeoutSeconds);
    }

    public PredictionData generar(String period, String granularity) {
        ApiResponse<PredictionData> response = webClient.post()
                .uri("/api/v1/predictions/generate")
                .header("Idempotency-Key", UUID.randomUUID().toString())
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(new GeneratePredictionRequest(period, "sales", granularity))
                .retrieve()
                .onStatus(HttpStatusCode::isError, r -> r.bodyToMono(ApiError.class)
                        .defaultIfEmpty(new ApiError(false, "Error HTTP " + r.statusCode().value(), null))
                        .flatMap(err -> Mono.error(new PrediccionException(r.statusCode().value(), err))))
                .bodyToMono(new ParameterizedTypeReference<ApiResponse<PredictionData>>() {})
                .timeout(timeout)
                .block();
        return response.data();
    }
}

public class PrediccionException extends RuntimeException {
    private final int status;
    private final String code;

    public PrediccionException(int status, ApiError error) {
        super(error.message());
        this.status = status;
        this.code = error.error() != null ? error.error().code() : null;
    }
    public int getStatus() { return status; }
    public String getCode() { return code; }   // MODEL_NOT_TRAINED, SERVICE_BUSY, ...
}
```

Uso: `PredictionData p = prediccionClient.generar("7_days", "daily");`

### Java / Spring Boot 3.2+ (RestClient, sin WebFlux)

```java
RestClient restClient = RestClient.builder()
        .baseUrl(System.getenv("PREDICCION_API_URL"))
        .defaultHeader("X-API-Key", System.getenv("PREDICCION_API_KEY"))
        .build();

ApiResponse<PredictionData> respuesta = restClient.post()
        .uri("/api/v1/predictions/generate")
        .contentType(MediaType.APPLICATION_JSON)
        .body(new GeneratePredictionRequest("3_months", "sales", "monthly"))
        .retrieve()
        .onStatus(HttpStatusCode::isError, (req, res) -> {
            throw new IllegalStateException("Predicciones respondió " + res.getStatusCode());
        })
        .body(new ParameterizedTypeReference<ApiResponse<PredictionData>>() {});
```

Si la integración actúa en nombre de un usuario, sustituye `X-API-Key` por
`Authorization: Bearer <JWT>` obtenido en `POST /auth/login`.

### Python (requests)

```python
import os
import requests

BASE_URL = os.environ["PREDICCION_API_URL"]
HEADERS = {"X-API-Key": os.environ["PREDICCION_API_KEY"]}

response = requests.post(
    f"{BASE_URL}/api/v1/predictions/generate",
    json={"period": "7_days", "prediction_type": "sales", "granularity": "daily"},
    headers=HEADERS,
    timeout=35,
)
body = response.json()
if not body.get("success"):
    raise RuntimeError(f"{response.status_code} {body['error']['code']}: {body['message']}")
forecast = body["data"]["forecast"]
print(forecast["predicted_sales"], forecast["variation_percentage"])
```

### JavaScript (fetch — navegador con JWT o Node.js 18+ con API Key)

```javascript
const BASE_URL = process.env.PREDICCION_API_URL;   // en navegador, desde la configuración de la app

async function generarPrediccion() {
  const res = await fetch(`${BASE_URL}/api/v1/predictions/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Servidor (Node.js): API Key. Navegador/React/Angular: Authorization: `Bearer ${jwt}`
      "X-API-Key": process.env.PREDICCION_API_KEY,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({ period: "7_days", prediction_type: "sales", granularity: "daily" }),
    signal: AbortSignal.timeout(35000),
  });
  const body = await res.json();
  if (!res.ok || !body.success) {
    throw new Error(`${res.status} ${body.error?.code}: ${body.message}`);
  }
  return body.data;
}
```

Nunca expongas una API Key en código que se ejecuta en el navegador o en una app móvil.
