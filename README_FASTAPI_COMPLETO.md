# Costa De Oro Imports — FastAPI 3.1

Migración modular de la API de Costa De Oro Imports desde Spring Boot. Se mantienen los nombres de las tablas y las rutas administrativas principales; los controladores de administración requieren JWT y rol `ADMIN`.

## Arquitectura actualizada

- `app/models/` contiene los modelos SQLAlchemy; `app/schemas/` contiene los contratos Pydantic.
- `app/api/v1/endpoints/auth.py` reúne login, registro y OAuth Google/Apple; `admin.py` reúne rutas administrativas y predicción.
- `app/prediction/` carga y procesa las ventas con Pandas/NumPy y combina Scikit-Learn, TensorFlow/Keras y PyTorch.
- `app/core/cache.py` usa Valkey mediante `VALKEY_URL` (URI estándar `redis://` o `rediss://`). El caché se puede omitir en desarrollo y usa TTL de 30 segundos para credenciales/perfil de usuario y 300 segundos para dashboards por defecto.
- `app/tests/` mantiene pruebas aisladas con SQLite; ninguna prueba abre conexión con el `.env` real.

El motor ajusta tres modelos sobre el historial y calcula el promedio de sus proyecciones mensuales. Usa TensorFlow con su API Keras y PyTorch; ambos se ejecutan en CPU. Las dependencias están en `requirements.txt` y `.python-version` fija Python 3.13, compatible con los dos frameworks.

### Variables nuevas

Configura `VALKEY_URL` con la URI privada de Layerbase y no la subas al repositorio. Para OAuth configura `GOOGLE_ALLOWED_CLIENT_IDS` y `APPLE_ALLOWED_CLIENT_IDS` con los audiencias/client IDs de tus aplicaciones. La API verifica los ID tokens firmados contra los JWKS oficiales; no acepta tokens OAuth sin validar.

Por defecto, `PREDICTION_DATA_SOURCE=database` intenta obtener ventas de `compra`, `detalle_venta`, `producto`, `categoria`, `usuario` y `empresa`. Si MySQL falla o no devuelve compras pagadas, el motor cambia automáticamente al CSV incluido. `PREDICTION_DATA_SOURCE=csv` fuerza el modo offline para desarrollo.

Registro directo requiere `tipoIdentificacion`, `numeroIdentificacion`, `nombres`, `apellidos`, `telefono`, `correo` y `password`. En Google/Apple, el ID token aporta el correo verificado; para crear una cuenta nueva, el formulario social también debe enviar esos siete campos y el correo debe coincidir con el token.

Pruebas: `python -m pytest app/tests`.

## Ejecutar

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edita .env y configura DB_URL, DB_USERNAME, DB_PASSWORD y JWT_SECRET_ECOMMERCE
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Documentación: `http://localhost:8080/doc`; OpenAPI: `/v3/api-docs`; salud: `/health` y `/health/db`.

## Autenticación y roles

- `POST /auth/login`: `{"username":"correo@dominio.com","password":"..."}`. Devuelve `accessToken` y el rol asignado.
- `POST /auth/registro`: crea cuentas con rol `PERSONA_NATURAL` por defecto; acepta `INVITADO`, `PERSONA_CONTACTO`, `PERSONA_JURIDICA`, `PERSONA_NATURAL` o `PROVEEDOR`.
- `ADMIN` no se puede asignar desde el registro público. Créalo mediante una operación de administración segura directamente en la base de datos o desde una cuenta administradora existente.
- Solo `PERSONA_NATURAL` queda activado automáticamente. Los demás roles quedan pendientes (`is_enabled=false`) hasta aprobación administrativa.
- `GET /admin/usuario/pendientes`, `PATCH /admin/usuario/{id}/activar`, `PATCH /admin/usuario/{id}/desactivar` son exclusivos de `ADMIN`.
- `POST /auth/logout` exige una sesión válida y recuerda borrar el token del cliente. El JWT es stateless y no se revoca de forma global inmediata; para eso se necesita una tabla de revocación persistente compartida por todas las instancias.

## Controladores administrativos migrados

CRUD genérico protegido para `/admin/rol`, `/admin/empresa`, `/admin/usuario`, `/admin/categoria`, `/admin/subcategoria`, `/admin/producto`, `/admin/compra`, `/admin/detalle-venta`, `/admin/historia`, `/admin/factura-proveedor`, `/admin/detalle-factura`, `/admin/comentario` y `/admin/peticion`.

Rutas adicionales basadas en Spring:

- Productos/categorías: opciones, subcategorías y activar/desactivar.
- Clientes: listar, consultar, crear, actualizar, desactivar y eliminar lógicamente.
- Proveedores: listar, consultar, crear, actualizar, desactivar y registrar factura.
- Compras: listado, detalle y cambio de estado.
- Blog: CRUD y desactivar.
- PQRS y reseñas: listado, cambio de estado o desactivación.
- Dashboard: `/admin/principal`.
- Gráficas: `/api/graficas/*`.
- Reportes: `/api/reportes/*`.
- Búsqueda: `/api/search/universal`.
- Predicción: `/admin/prediccion/*` (el cálculo requiere configurar el motor externo).

## Importante: validación pendiente en entorno real

La sintaxis de Python se ha comprobado. No fue posible ejecutar integración real con MySQL en este entorno, porque no hay acceso de red para instalar dependencias. Antes de producción, ejecuta las pruebas contra una copia de `db_beer`, revisa que el esquema SQL coincide con `app/models.py` y completa los contratos DTO exactos donde Spring usa cargas multipart, pagos Mercado Pago, Cloudinary, correo, OAuth, IA o predicciones externas. El endpoint de mapa de ventas indica explícitamente que faltan coordenadas en el modelo y no inventa datos geográficos.
