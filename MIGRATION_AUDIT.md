# Auditoría de migración — Costa De Oro Imports

El inventario se generó leyendo los `@RequestMapping` y mappings HTTP de los controladores del ZIP original. La API original contiene **100 combinaciones únicas de método/ruta detectadas**. No todas son API JSON: algunas rutas son páginas legales o controladores de administración; deben verificarse contra las anotaciones completas y los DTO antes de replicarlas.

## Variables de entorno oficiales

Se copiaron únicamente los nombres; no se incluyeron los valores sensibles del `.env`.

```text
PuertoServidor
PREDICCION_API_URL
PREDICCION_API_KEY
DB_URL
DB_USERNAME
DB_PASSWORD
SPRING_JPA_HIBERNATE_DDL_AUTO
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
REMEMBER_ME_KEY
REMEMBER_ME_TOKEN
PASSWORD_URL_RECAPTCHA
PASSWORD_KEY_RECAPTCHA
MAIL_USERNAME
MAIL_PASSWORD
CLOUD_NAME
CLOUD_API_KEY
CLOUD_API_SECRET
GEMINI_API_KEY
MERCADO_PAGO_ACCESS_TOKEN
PORT
NombreAplicacion
FRONTEND_URL
CORS_ALLOWED_ORIGINS
GOOGLE_ALLOWED_CLIENT_IDS
JWT_SECRET_ECOMMERCE
JWT_ISSUER_ECOMMERCE
SPRINGDOC_API_DOCS_ENABLED
SPRINGDOC_SWAGGER_UI_ENABLED
MCP_CLIENT_ENABLED
GEMINI_MODEL
```

## Inventario de rutas detectadas

| Método | Ruta | Controlador Java | Estado en esta migración |
|---|---|---|---|
| `GET` | `/admin/blog/` | `BlogController` | Pendiente de portar y probar |
| `GET` | `/admin/blog/{id}` | `BlogController` | Parcial/implementación base |
| `POST` | `/admin/blog/` | `BlogController` | Pendiente de portar y probar |
| `PUT` | `/admin/blog/{id}` | `BlogController` | Pendiente de portar y probar |
| `PATCH` | `/admin/blog/{id}/disable` | `BlogController` | Pendiente de portar y probar |
| `DELETE` | `/admin/blog/{id}` | `BlogController` | Pendiente de portar y probar |
| `GET` | `/admin/categoria/` | `CategoriaController` | Pendiente de portar y probar |
| `GET` | `/admin/categoria/{id}` | `CategoriaController` | Parcial/implementación base |
| `POST` | `/admin/categoria/` | `CategoriaController` | Pendiente de portar y probar |
| `PUT` | `/admin/categoria/{id}` | `CategoriaController` | Pendiente de portar y probar |
| `PATCH` | `/admin/categoria/{id}/disable` | `CategoriaController` | Pendiente de portar y probar |
| `DELETE` | `/admin/categoria/{id}` | `CategoriaController` | Pendiente de portar y probar |
| `GET` | `/admin/clientes/` | `ClientesController` | Pendiente de portar y probar |
| `GET` | `/admin/clientes/{id}` | `ClientesController` | Parcial/implementación base |
| `POST` | `/admin/clientes/` | `ClientesController` | Pendiente de portar y probar |
| `PUT` | `/admin/clientes/{id}` | `ClientesController` | Pendiente de portar y probar |
| `PATCH` | `/admin/clientes/{id}/disable` | `ClientesController` | Pendiente de portar y probar |
| `DELETE` | `/admin/clientes/{id}` | `ClientesController` | Pendiente de portar y probar |
| `GET` | `/admin/compra/` | `CompraController` | Pendiente de portar y probar |
| `GET` | `/admin/compra/{id}` | `CompraController` | Parcial/implementación base |
| `PATCH` | `/admin/compra/{id}/estado` | `CompraController` | Pendiente de portar y probar |
| `GET` | `/admin/principal/` | `DashboardController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/dashboard` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/ingresos-gastos` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/ventas-totales` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/stock-compras` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/mapa-ventas` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/graficas/historico-ventas` | `DashboardRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/ventas-clientes` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/ventas-producto` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/ventas-cliente-producto` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/rentabilidad-producto` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/cuentas-pagar` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/api/reportes/reporte-compras` | `GenerarReporteRestController` | Pendiente de portar y probar |
| `GET` | `/admin/pqrs/` | `PQRS_Controller` | Pendiente de portar y probar |
| `PATCH` | `/admin/pqrs/{id}/estado` | `PQRS_Controller` | Pendiente de portar y probar |
| `DELETE` | `/admin/pqrs/{id}` | `PQRS_Controller` | Pendiente de portar y probar |
| `GET` | `/admin/prediccion/` | `PrediccionesController` | Pendiente de portar y probar |
| `GET` | `/admin/prediccion/datos-grafica` | `PrediccionesController` | Pendiente de portar y probar |
| `POST` | `/admin/prediccion/generar` | `PrediccionesController` | Pendiente de portar y probar |
| `GET` | `/admin/producto/` | `ProductoController` | Pendiente de portar y probar |
| `GET` | `/admin/producto/opciones` | `ProductoController` | Pendiente de portar y probar |
| `GET` | `/admin/producto/{id}` | `ProductoController` | Parcial/implementación base |
| `GET` | `/admin/producto/subcategorias/{categoriaId}` | `ProductoController` | Pendiente de portar y probar |
| `POST` | `/admin/producto/` | `ProductoController` | Pendiente de portar y probar |
| `PUT` | `/admin/producto/{id}` | `ProductoController` | Pendiente de portar y probar |
| `PATCH` | `/admin/producto/{id}/disable` | `ProductoController` | Pendiente de portar y probar |
| `DELETE` | `/admin/producto/{id}` | `ProductoController` | Pendiente de portar y probar |
| `GET` | `/admin/provedores/` | `ProvedoresController` | Pendiente de portar y probar |
| `GET` | `/admin/provedores/{id}` | `ProvedoresController` | Parcial/implementación base |
| `GET` | `/admin/provedores/productos/{proveedorId}` | `ProvedoresController` | Pendiente de portar y probar |
| `POST` | `/admin/provedores/compras` | `ProvedoresController` | Pendiente de portar y probar |
| `POST` | `/admin/provedores/` | `ProvedoresController` | Pendiente de portar y probar |
| `PUT` | `/admin/provedores/{id}` | `ProvedoresController` | Pendiente de portar y probar |
| `PATCH` | `/admin/provedores/{id}/disable` | `ProvedoresController` | Pendiente de portar y probar |
| `DELETE` | `/admin/provedores/{id}` | `ProvedoresController` | Pendiente de portar y probar |
| `GET` | `/admin/resenna/` | `ResennaController` | Pendiente de portar y probar |
| `PATCH` | `/admin/resenna/{id}/disable` | `ResennaController` | Pendiente de portar y probar |
| `DELETE` | `/admin/resenna/{id}` | `ResennaController` | Pendiente de portar y probar |
| `GET` | `/api/search/universal` | `SearchController` | Pendiente de portar y probar |
| `POST` | `/api/chat` | `AIController` | Pendiente de portar y probar |
| `POST` | `/auth/login` | `AuthenticationController` | Parcial/implementación base |
| `POST` | `/auth/google` | `AuthenticationController` | Pendiente de portar y probar |
| `POST` | `/auth/logout` | `AuthenticationController` | Parcial/implementación base |
| `GET` | `/auth/catalogos` | `AuthenticationController` | Parcial/implementación base |
| `POST` | `/auth/completar-registro` | `AuthenticationController` | Pendiente de portar y probar |
| `POST` | `/auth/registrar-empresa` | `AuthenticationController` | Pendiente de portar y probar |
| `POST` | `/auth/registro` | `AuthenticationController` | Parcial/implementación base |
| `POST` | `/api/compras/` | `CompraRestController` | Pendiente de portar y probar |
| `GET` | `/legal/terminos-condiciones` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/politica-privacidad` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/cookies` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/autorizacion-datos` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/proteccion-consumidor` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/retracto` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/reversion-pago` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/pqrs` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/mayoria-edad` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/ecommerce-cervezas` | `LegalController` | Pendiente de portar y probar |
| `GET` | `/legal/ecommerce-licores` | `LegalController` | Pendiente de portar y probar |
| `POST` | `/api/mercado-pago/iniciar-compra` | `MercadoPagoRestController` | Pendiente de portar y probar |
| `POST` | `/api/mercado-pago/notificacion` | `MercadoPagoRestController` | Pendiente de portar y probar |
| `GET` | `/perfil/` | `PerfilController` | Pendiente de portar y probar |
| `GET` | `/perfil/configuracion` | `PerfilController` | Parcial/implementación base |
| `PATCH` | `/perfil/usuario` | `PerfilController` | Pendiente de portar y probar |
| `PATCH` | `/perfil/empresa` | `PerfilController` | Pendiente de portar y probar |
| `PUT` | `/perfil/usuario/imagen` | `PerfilController` | Pendiente de portar y probar |
| `PUT` | `/perfil/empresa/imagen` | `PerfilController` | Pendiente de portar y probar |
| `PATCH` | `/perfil/contrasena` | `PerfilController` | Pendiente de portar y probar |
| `GET` | `/` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/packs` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos` | `PrincipalController` | Parcial/implementación base |
| `GET` | `/productos/mas-vendidos` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos/precio-asc` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos/precio-desc` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos/nombre-asc` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos/nombre-desc` | `PrincipalController` | Pendiente de portar y probar |
| `POST` | `/productos/filtrar` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/blog` | `PrincipalController` | Pendiente de portar y probar |
| `GET` | `/productos/{productoId}` | `PrincipalController` | Parcial/implementación base |

## Funcionalidad no equivalente todavía
- Login Google (`POST /auth/google`), validación de ID token, completar registro y flujo OAuth web.
- reCAPTCHA en login mediante `X-Recaptcha-Token`.
- Gestión de roles/permisos completa y formato de errores `{mensaje, success}` en todos los handlers.
- CRUD completo de productos/categorías/clientes/proveedores/blog/reseñas/PQRS/historias.
- Compras con transacción, stock, IVA, cupones, detalle de venta, notificaciones y estados.
- Preferencias/webhooks de Mercado Pago con validación de firma y conciliación.
- Cloudinary, carga multipart, Gemini chat, correo SMTP, búsqueda universal.
- Reportes SQL, gráficas, predicciones y contratos exactos de DTO.
- Pruebas de contrato comparando el backend Java y FastAPI.

## Notas de compatibilidad
- Se mapearon tablas y columnas según `src/main/resources/sql/schema.sql`. La entidad `Empresa` usa la tabla `empresa` (singular), y `Usuario.empresa_id` es única según el esquema.
- El esquema de la tabla `SPRING_AI_CHAT_MEMORY` requiere migración aparte si se decide conservar memoria conversacional.
- Los secretos deben rotarse si el `.env` real se compartió públicamente. Este paquete no reproduce secretos.
