# Passkeys (WebAuthn / FIDO2) — Backend FastAPI

Inicio de sesión sin contraseña (Face ID / Touch ID / huella) para la app Flutter. Usa la librería
oficial `webauthn` (py_webauthn), MySQL como persistencia principal y Valkey como caché y almacén de
sesiones.

| Archivo | Responsabilidad |
|---|---|
| `app/api/v1/endpoints/passkey.py` | Endpoints, alias para Flutter y validación de sesión |
| `app/services/passkey_service.py` | Ceremonias WebAuthn, emisión y validación de sesiones, rate limit |
| `app/services/passkey_store.py` | Estrategia Valkey → MySQL (challenges, credenciales, `sign_count`) |
| `app/models/passkey.py` | Modelos SQLAlchemy `PasskeyCredencial`, `PasskeyChallenge` |
| `app/schemas/passkey.py` | Contratos Pydantic de entrada y salida |
| `app/sql/passkeys.sql` | Tablas nuevas de MySQL (no modifican `usuario`) |
| `app/core/cache.py` | Cliente Valkey (`valkey-py`, con `redis-py` como respaldo), `GETDEL`, TTL |
| `app/tests/test_passkeys.py` | Flujo completo con un autenticador por software (firmas P-256 reales) |

## 1. Puesta en marcha

```bash
pip install -r requirements.txt
mysql -u <usuario> -p db_beer < app/sql/passkeys.sql
```

`.env`:

```env
PASSKEY_RP_ID=costadeoroimports.com
PASSKEY_RP_NAME=Costa de Oro Imports
# iOS usa https://<dominio>; Android usa android:apk-key-hash:<sha256 del certificado en base64url>
PASSKEY_EXPECTED_ORIGINS=https://costadeoroimports.com,android:apk-key-hash:XXXXXXXX
PASSKEY_CHALLENGE_TTL_SECONDS=300
PASSKEY_CACHE_TTL_SECONDS=3600
PASSKEY_SESSION_TTL_SECONDS=3600
VALKEY_URL=rediss://usuario:clave@host:6379
```

- `PASSKEY_RP_ID` debe ser igual al `PASSKEY_RP_ID` de Flutter. Si está vacío, los endpoints responden `503`.
- Para calcular el origen de Android a partir del SHA-256 del certificado:
  ```bash
  python -c "import base64,sys;print('android:apk-key-hash:'+base64.urlsafe_b64encode(bytes.fromhex(sys.argv[1].replace(':',''))).decode().rstrip('='))" AA:BB:...:FF
  ```
- El dominio debe publicar `/.well-known/apple-app-site-association` y `/.well-known/assetlinks.json`
  (ver `docs/passkeys.md` del repositorio Flutter).

## 2. Estrategia Valkey → MySQL

| Dato | Escritura | Lectura | Clave Valkey | TTL |
|---|---|---|---|---|
| Challenge | Valkey (respaldo: tabla `passkey_challenge` si Valkey no responde) | `GETDEL` atómico, un solo uso; si no está, se busca en MySQL | `passkey:challenge:<id>` | `PASSKEY_CHALLENGE_TTL_SECONDS` (300 s) |
| Credencial | MySQL y, de inmediato, Valkey | Valkey; si falta (cache miss) MySQL y se re-puebla Valkey | `passkey:cred:<credential_id>` | `PASSKEY_CACHE_TTL_SECONDS` |
| Passkeys del usuario | Se invalida y re-puebla al registrar o revocar | Valkey → MySQL | `passkey:user:<usuario_id>` | `PASSKEY_CACHE_TTL_SECONDS` |
| `sign_count` | `UPDATE` en MySQL condicionado al valor anterior + escritura en Valkey | — | `passkey:cred:<credential_id>` | — |
| Sesión | Valkey | Valkey (sin MySQL) | `auth:token:<sha256 del token>` | `PASSKEY_SESSION_TTL_SECONDS` |
| Rate limit | Valkey | Valkey | `passkey:rate:login:<ip>:<minuto>` | 61 s |

Si Valkey cae, el login sigue funcionando (challenges en MySQL, credenciales desde MySQL). Sólo
`/api/v1/auth/session/validate` responde `503`, porque por diseño valida únicamente contra Valkey.

## 3. Endpoints y contrato JSON

Las rutas `/api/v1/auth/passkey/*` son las principales. Los alias `/auth/passkey/*` son las rutas
que **la app Flutter ya llama** (`AuthRepository`); ambas ejecutan el mismo código.

| Paso | Ruta principal | Alias usado por Flutter | Autenticación |
|---|---|---|---|
| Registro 1 | `POST /api/v1/auth/passkey/register/start` | `POST /auth/passkey/register/options` | `Authorization: Bearer <JWT>` |
| Registro 2 | `POST /api/v1/auth/passkey/register/finish` | `POST /auth/passkey/register/verify` | `Authorization: Bearer <JWT>` |
| Login 1 | `POST /api/v1/auth/passkey/login/start` | `POST /auth/passkey/login/options` | Pública |
| Login 2 | `POST /api/v1/auth/passkey/login/finish` | `POST /auth/passkey/login/verify` | Pública |
| Sesión | `GET /api/v1/auth/session/validate` | — | `Authorization: Bearer <token>` |
| Mis passkeys | `GET /api/v1/auth/passkey/credentials` | — | `Authorization: Bearer <JWT>` |
| Revocar | `DELETE /api/v1/auth/passkey/credentials/{passkey_id}` | — | `Authorization: Bearer <JWT>` |

Todos los binarios van en **base64url sin relleno**. Los errores usan el formato del resto de `/auth`:
`{"detail": "mensaje para el usuario"}`.

### 3.1 Registro — paso 1

Entrada:

```json
{ "device_name": "iOS" }
```

Salida `200`: Flutter lee `challenge_id` y `options` y pasa `options` a `PasskeyService.createCredential`.

```json
{
  "challenge_id": "3f6c1b7e2a9d4c0f8e1a5b2c7d9e0f11",
  "expires_in": 300,
  "options": {
    "rp": { "name": "Costa de Oro Imports", "id": "costadeoroimports.com" },
    "user": { "id": "q2VZbXkx…", "name": "ana@example.com", "displayName": "Ana Prueba" },
    "challenge": "rNw4m2pW…",
    "pubKeyCredParams": [ { "type": "public-key", "alg": -7 }, { "type": "public-key", "alg": -257 } ],
    "timeout": 120000,
    "excludeCredentials": [ { "id": "AbCd…", "type": "public-key", "transports": ["internal"] } ],
    "authenticatorSelection": { "residentKey": "required", "requireResidentKey": true, "userVerification": "required" },
    "attestation": "none"
  }
}
```

- `user.id` es un identificador opaco y estable del usuario (no su ID de base de datos ni su correo).
- `excludeCredentials` evita registrar dos veces el mismo dispositivo; Flutter lo trata como "ya vinculada".

### 3.2 Registro — paso 2

Entrada (`credential` es el `RegistrationResponseJSON` de `createCredential`):

```json
{
  "challenge_id": "3f6c1b7e2a9d4c0f8e1a5b2c7d9e0f11",
  "device_name": "iOS",
  "credential": {
    "id": "AbCd…", "rawId": "AbCd…", "type": "public-key",
    "response": {
      "clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uY3JlYXRlIi4uLn0",
      "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10oGhhdXRoRGF0YVi…",
      "transports": ["internal", "hybrid"]
    },
    "clientExtensionResults": {},
    "authenticatorAttachment": "platform"
  }
}
```

Salida `200` (Flutter sólo necesita el código 200):

```json
{
  "success": true,
  "message": "Passkey registrada correctamente",
  "passkey": {
    "passkey_id": 7, "credential_id": "AbCd…", "device_name": "iOS",
    "device_type": "multi_device", "backed_up": true,
    "created_at": "2026-11-07T10:30:00", "last_used_at": null
  }
}
```

Errores: `400` la verificación falló · `401` challenge expirado, ya usado o de otro usuario · `409` passkey ya registrada.

### 3.3 Login — paso 1

Entrada: `{}`. Flutter no envía correo porque las passkeys son descubribles; así el endpoint no revela
qué cuentas existen. Opcionalmente se puede enviar `{"correo": "..."}`, y un correo desconocido
produce la misma respuesta que `{}`.

Salida `200`:

```json
{
  "challenge_id": "9a1d3c5e7f2b4a6c8e0d1f3b5a7c9e11",
  "expires_in": 300,
  "options": {
    "rpId": "costadeoroimports.com",
    "challenge": "Zk9pQ3Vs…",
    "timeout": 120000,
    "allowCredentials": [],
    "userVerification": "required"
  }
}
```

### 3.4 Login — paso 2

Entrada (`credential` es el `AuthenticationResponseJSON` de `getAssertion`):

```json
{
  "challenge_id": "9a1d3c5e7f2b4a6c8e0d1f3b5a7c9e11",
  "credential": {
    "id": "AbCd…", "rawId": "AbCd…", "type": "public-key",
    "response": {
      "clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uZ2V0Ii4uLn0",
      "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_krrmihjLHmVzzuoMdl2MFAAAAAQ",
      "signature": "MEUCIQ…",
      "userHandle": "q2VZbXkx…"
    },
    "clientExtensionResults": {},
    "authenticatorAttachment": "platform"
  }
}
```

Salida `200`: **el mismo formato que `POST /auth/login`**, así Flutter reutiliza `_authenticate`:
toma `accessToken` y construye `UserModel.fromJson(usuario)`.

```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…",
  "token_type": "bearer",
  "expires_in": 3600,
  "auth_method": "passkey",
  "usuario": {
    "usuario_id": 10, "correo": "ana@example.com", "nombres": "Ana",
    "apellidos": "Prueba", "telefono": "3005550000", "rol": "PERSONA_NATURAL"
  }
}
```

El `accessToken` es el mismo tipo de JWT que el de `/auth/login` (con claims adicionales
`amr: ["pop","user"]` y `auth_method: "passkey"`), así que funciona en todos los endpoints protegidos.

Errores: `401` challenge expirado o reutilizado, passkey desconocida o revocada, firma, origen,
`userHandle` o contador inválidos (Flutter deja de lanzar la passkey automáticamente) · `403` cuenta
deshabilitada · `429` demasiados intentos.

### 3.5 Validar sesión

`GET /api/v1/auth/session/validate` con `Authorization: Bearer <accessToken>`. Consulta sólo Valkey.

```json
{ "valid": true, "usuario_id": 10, "rol": "PERSONA_NATURAL", "auth_method": "passkey", "expires_in": 3412 }
```

`401` sesión inexistente, expirada o revocada (`/auth/logout`) · `503` Valkey no disponible.
También valida tokens de `/auth/login` (en ese caso `auth_method` es `null`).

## 4. Controles de seguridad

| Control | Implementación |
|---|---|
| Firma | `verify_authentication_response` comprueba la firma con la clave pública guardada |
| Anti-replay | Challenge de 32 bytes, un solo uso (`GETDEL` / `DELETE` con `rowcount`), TTL de 5 min, ligado al usuario en el registro |
| Autenticadores clonados | `sign_count` debe aumentar; el `UPDATE` es condicional (concurrencia optimista) |
| Origen y dominio | `expected_origin` (iOS y Android) y `expected_rp_id` (rpIdHash) |
| Biometría o PIN | `userVerification: required` y `require_user_verification=True` |
| Passkeys descubribles | `residentKey: required`; el login no pide correo |
| `userHandle` | Debe coincidir con el de la credencial |
| Estado de la cuenta | Se lee de MySQL en cada login (cuenta deshabilitada → `403`) |
| Rate limit | 30 peticiones por minuto e IP en `login/*` (Valkey) |
| Revocación | `DELETE /api/v1/auth/passkey/credentials/{id}` invalida MySQL y Valkey al instante |
| Datos guardados | Sólo la clave pública; la clave privada nunca sale del Secure Enclave / Keystore |
