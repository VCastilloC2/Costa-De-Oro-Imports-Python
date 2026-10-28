# Costa De Oro Imports — migración FastAPI

## Instalar (Windows)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Completa DB_URL, DB_USERNAME, DB_PASSWORD y secretos de proveedores
uvicorn app.main:app --reload
```
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