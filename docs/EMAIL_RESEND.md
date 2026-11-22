# Correo transaccional con Resend

La aplicación envía correo mediante el SDK oficial de Resend y su API HTTPS. No requiere puertos SMTP ni una instancia de Render de pago.

## Configuración local y Render

Configura estas variables en `.env` para desarrollo y en **Render Dashboard → Web Service → Environment → Environment Variables** para producción:

```env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxx
MAIL_FROM=Costa De Oro Imports <notificaciones@tu-dominio-verificado.com>
```

Usa una dirección del dominio que hayas verificado en Resend; el dominio y el remitente definitivos son decisión tuya. No subas la API key al repositorio.

## Preparar Resend

1. Crea una cuenta en Resend.
2. Agrega y verifica el dominio desde el que vas a enviar (configura los registros DNS que Resend indique).
3. Genera una API Key con permiso de envío y guárdala como `RESEND_API_KEY`.
4. Define `MAIL_FROM` con un nombre opcional y una dirección del dominio verificado.
5. Guarda ambas variables en el servicio web de Render y realiza un nuevo despliegue.
6. Prueba registro, inicio de sesión y recuperación de contraseña. Para comprobar entrega, revisa el registro de Emails en Resend.

Render Free permite esta integración porque el SDK llama a la API por HTTPS. Los errores del proveedor se registran sin incluir claves, códigos OTP o contenido privado; los fallos de recuperación responden con error y descartan el OTP pendiente. Bienvenida y notificación de inicio de sesión continúan siendo best effort.

## Prueba automatizada

```powershell
python -m pytest app/tests/test_email_service.py app/tests/test_auth.py
```

Las pruebas sustituyen la llamada al SDK y no envían correos reales.
