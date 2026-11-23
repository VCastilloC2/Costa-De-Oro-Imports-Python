# Correo transaccional con Gmail API

FastAPI envía los correos transaccionales desde `costadeoroimports2@gmail.com` usando Gmail API y OAuth de usuario. El archivo JSON descargado desde Google Cloud contiene la identidad del cliente OAuth; por seguridad no se incluye en Git. El token OAuth renovable se crea una vez en cada entorno y también debe guardarse como secreto.

## Configuración de Google Cloud

1. Habilita **Gmail API** en el proyecto de Google Cloud.
2. Configura la pantalla de consentimiento OAuth. Si la app está en modo de prueba, agrega `costadeoroimports2@gmail.com` como usuario de prueba.
3. El JSON recibido es un cliente OAuth de tipo **Web** y no trae URI de redirección. En Google Auth Platform → Clients, agrega `http://localhost:8765/` a **Authorized redirect URIs** para la autorización local. Para autorizar en otro entorno, registra allí su URI HTTPS y configura `GMAIL_OAUTH_REDIRECT_URI` con la misma dirección; debe ser idéntica.
4. El usuario que autoriza debe ser `costadeoroimports2@gmail.com`. El permiso solicitado es solo `https://www.googleapis.com/auth/gmail.send`.

## Variables de entorno

```dotenv
GMAIL_CREDENTIALS_FILE=C:/ruta/segura/client_secret.json
GMAIL_TOKEN_FILE=C:/ruta/persistente/gmail-token.json
GMAIL_SENDER=costadeoroimports2@gmail.com
GMAIL_OAUTH_REDIRECT_URI=http://localhost:8765/
```

Instala las dependencias de `requirements.txt` y ejecuta una vez `python -m scripts.authorize_gmail` desde un equipo con navegador. Inicia sesión con la cuenta remitente y acepta el permiso. El token resultante debe persistir en el servidor; en Render configura el JSON de credenciales y el token en almacenamiento persistente/secreto. Si la pantalla OAuth sigue en modo de prueba, los refresh tokens pueden caducar periódicamente; publica/configura la app conforme a las reglas de Google para uso continuo.

La recuperación de contraseña requiere además Valkey, que guarda el código y los límites de solicitudes.

1. Configura Google Cloud
   En el proyecto de Google Cloud que creó esas credenciales:
1. Habilita Gmail API.
2. Configura la pantalla de consentimiento OAuth. Si está en modo de prueba, agrega costadeoroimports2@gmail.com como usuario de prueba.
3. En el cliente OAuth de tipo Web, agrega estas URI autorizadas:
    - Local: http://localhost:8765/
    - Producción: una URL HTTPS pública de tu aplicación, por ejemplo https://TU-DOMINIO/oauth/callback
      La URI debe coincidir exactamente con la que configures en cada entorno. Para el procedimiento, consulta la guía oficial de Gmail para Python.
2. Autoriza el envío local
   En el .env local configura:
   GMAIL_CREDENTIALS_FILE=C:/ruta/segura/client_secret_....json
   GMAIL_TOKEN_FILE=gmail-token.json
   GMAIL_SENDER=costadeoroimports2@gmail.com
   GMAIL_OAUTH_REDIRECT_URI=http://localhost:8765/
   Instala las dependencias y genera el token:
   pip install -r requirements.txt
   python -m scripts.authorize_gmail
   Se abrirá el navegador para iniciar sesión con la cuenta remitente y aceptar el permiso. El comando guardará gmail-token.json; conserva ese archivo y no lo subas a Git.

3. Configura Render o Azure
   En la configuración de variables del servicio, define:
   GMAIL_SENDER=costadeoroimports2@gmail.com
   GMAIL_CREDENTIALS_FILE=keys/credentials.json
   GMAIL_TOKEN_FILE=keys/gmail-token.json
   GMAIL_OAUTH_REDIRECT_URI=https://TU-DOMINIO/oauth/callback


## Referencias

- [Quickstart Python de Gmail API](https://developers.google.com/workspace/gmail/api/quickstart/python)
- [Crear y enviar mensajes](https://developers.google.com/workspace/gmail/api/guides/sending)
- [Método users.messages.send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send)