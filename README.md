# Costa De Oro Imports — migración FastAPI

## Importante
Este paquete parte de una inspección del ZIP Java original. Conserva nombres reales de variables de entorno, genera un inventario de rutas detectadas y mapea el esquema MySQL principal. No contiene secretos del `.env` original.

**No es todavía una equivalencia de negocio certificada 1:1.** Los controladores Java tienen lógica extensa (inventario, transacciones de compra, permisos ADMIN, OAuth, pago, correo, reportes y gráficas). Esos comportamientos requieren migrar sus servicios y validar los contratos con pruebas. No se exponen rutas ficticias que aparenten funcionar cuando no lo hacen.

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

Los endpoints restantes del controlador Java están listados en `MIGRATION_AUDIT.md`; no se marcan como migrados hasta portar y probar sus reglas de negocio.
