# Costa De Oro Imports — migración FastAPI

## Instalar (Windows)
El proyecto usa Python 3.13 y TensorFlow 2.21 o 2.22 (`requirements.txt`).
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Completa DB_URL, DB_USERNAME, DB_PASSWORD y secretos de proveedores
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Con `PREDICTION_TRAIN_BEFORE_STARTUP=true`, el arranque inicia en segundo plano la comprobación y el
entrenamiento mensual de MySQL (hasta 500 épocas, con parada temprana), así el servidor puede enlazar
su puerto antes de que termine TensorFlow. Si cambian las ventas, vuelve a entrenar antes de usar el
modelo; asegúrate de crear primero las tablas ML descritas en `docs/API_PREDICCIONES.md`.
Docs: `/docs`; OpenAPI JSON: `/openapi.json`; alternativa ReDoc: `/redoc`.

## MySQL existente
No ejecuta `create_all`, no borra tablas ni carga SQL seed automáticamente. Usa el esquema existente y verifica nombres/tipos con `src/main/resources/sql/schema.sql` del proyecto original. Si el esquema real difiere, genera migraciones Alembic tras inspeccionarlo.

## API actualmente implementada
- `GET /health`, `GET /health/db`
- `POST /auth/login`, `POST /auth/registro`, `POST /auth/logout`
- `GET /api/productos`, `GET /api/productos/{id}`
- `GET /admin/producto`, `GET /admin/producto/{id}`
- `GET /admin/categoria`, `GET /admin/categoria/{id}`
- `GET /perfil`, `GET /perfil/configuracion`
- Swagger UI y OpenAPI.
- Servicio ML de predicciones (TensorFlow) en `/api/v1/predictions/*`: entrenamiento, métricas,
  generación, historial y API Keys para integraciones externas. Ver [docs/API_PREDICCIONES.md](docs/API_PREDICCIONES.md).
  Antes de usarlo crea las tablas nuevas con `app/prediction/sql/ml_tables.sql`.
- Passkeys (WebAuthn) con Valkey + MySQL en `/api/v1/auth/passkey/*` y `GET /api/v1/auth/session/validate`.
  Ver [docs/PASSKEYS.md](docs/PASSKEYS.md); tablas en `app/sql/passkeys.sql`.
