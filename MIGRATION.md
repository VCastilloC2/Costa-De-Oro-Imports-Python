# Migración a API REST pura

La aplicación ya no renderiza vistas. Lo único con HTML es Swagger UI (`/swagger-ui.html`).

## Cambios transversales

| Tema | Antes | Ahora |
|---|---|---|
| Autenticación | `formLogin` + cookie `access_token` | `POST /auth/login` (JSON) devuelve JWT. Cabecera `Authorization: Bearer <token>` |
| reCAPTCHA en login | Parámetro `g-recaptcha-response` | Cabecera `X-Recaptcha-Token` (la respuesta de error es JSON 400) |
| Login con Google | Redirecciones a vistas | Redirige a `${FRONTEND_URL}/auth/oauth2/callback#access_token=...` |
| Formularios | `@ModelAttribute` + `redirect:?mensaje=` | `@RequestBody` JSON (o multipart solo cuando hay archivos) + respuesta JSON |
| Acciones por GET | `GET disable/{id}`, `GET delete/{id}` | `PATCH /{id}/disable`, `DELETE /{id}` |
| Errores | Vistas `error/*` | JSON `{ "mensaje": "...", "success": false }` |
| Rutas públicas | `/**` permitAll (dejaba abierto `/perfil`) | Lista explícita; el resto requiere JWT |
| Logout | `POST /auth/logout` de Spring Security | `POST /auth/logout` informativo: el cliente descarta el token |

## Endpoints renombrados (admin y perfil)

| Antes | Ahora |
|---|---|
| `POST /perfil/actualizar-usuario` | `PATCH /perfil/usuario` |
| `POST /perfil/actualizar-empresa` | `PATCH /perfil/empresa` |
| `POST /perfil/colocar-imagen-usuario` | `PUT /perfil/usuario/imagen` |
| `POST /perfil/colocar-imagen-empresa` | `PUT /perfil/empresa/imagen` |
| `POST /perfil/actualizar-contraseña` | `PATCH /perfil/contrasena` |
| `GET /perfil/configuration` | `GET /perfil/configuracion` |
| `GET /admin/compra/detalle-compra/{id}` | `GET /admin/compra/{id}` |
| `GET /admin/compra/detalle-compra/cambiar-estado/{id}` | `PATCH /admin/compra/{id}/estado?estado=` |
| `GET /admin/pqrs/change-estado/{id}` | `PATCH /admin/pqrs/{id}/estado?estadoPeticion=` |
| `GET /admin/pqrs/delete/{id}` | `DELETE /admin/pqrs/{id}` |
| `POST /admin/*/update-*/{id}` | `PUT /admin/*/{id}` |
| `POST /admin/*/create-*` | `POST /admin/*` (responde 201) |
| `POST /admin/provedores/create-compra` | `POST /admin/provedores/compras` |

## Pendiente de tu lado

- Las rutas de `/admin/**` ya están protegidas por rol `ADMIN`. `/api/graficas/**`, `/api/reportes/**` y `/api/compras` solo exigen JWT válido.
- Variables nuevas: `FRONTEND_URL`, `MCP_CLIENT_ENABLED` (por defecto `false`), `PORT` (lo inyecta Vercel).
- Variables eliminadas: `REMEMBER_ME_KEY`, `REMEMBER_ME_TOKEN`.
- Los servicios de Cloudinary, Mercado Pago, correo y Gemini no cambiaron.
- Las plantillas de correo (`src/main/resources/templates`) no vinieron en el ZIP; el motor Thymeleaf se conserva solo para ellas.

## Clientes Flutter (móvil, escritorio y web)

- **Autenticación:** la app guarda el `accessToken` y lo envía en `Authorization: Bearer <token>`. No usa cookies.
- **Login con correo:** `POST /auth/login` con `{ "username": "correo", "password": "..." }` y cabecera `X-Recaptcha-Token` si el login lo exige.
- **Login con Google (recomendado en móvil):** la app obtiene el ID token con `google_sign_in` y lo envía a `POST /auth/google` con `{ "idToken": "..." }`. Si `requiereCompletarRegistro` es `true`, la app debe llevar al usuario a `POST /auth/completar-registro`.
- **Google en web:** `GET /oauth2/authorization/google` redirige a `${FRONTEND_URL}/auth/oauth2/callback#access_token=...`.
- **Flutter web:** el origen debe estar en `CORS_ALLOWED_ORIGINS`. Flutter web en desarrollo usa un puerto que cambia, así que agrégalo explícitamente.
- **Client IDs de Google:** `GOOGLE_ALLOWED_CLIENT_IDS` debe incluir los client IDs web, Android e iOS separados por comas. El ID token de Flutter tiene como `aud` el client ID con el que se configuró `google_sign_in`.
- **Errores:** todas las respuestas de error son JSON `{ "mensaje": "...", "success": false }`, y los formularios de Flutter pueden mostrar `mensaje` directamente.
- **Subidas de imagen:** usa `multipart/form-data` (perfil, productos, blog).
