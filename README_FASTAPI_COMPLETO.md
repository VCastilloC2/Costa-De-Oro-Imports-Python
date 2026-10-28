# Costa De Oro Imports — FastAPI 3.1

Migración modular de la API de Costa De Oro Imports desde Spring Boot. Se mantienen los nombres de las tablas y las rutas administrativas principales; los controladores de administración requieren JWT y rol `ADMIN`.

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
