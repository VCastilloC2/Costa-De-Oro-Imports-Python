# 🆘 Help - Guía de Troubleshooting

Bienvenido a la guía de ayuda de **Costa de Oro Imports**. Aquí encontrarás soluciones a los problemas más comunes y pasos para resolver issues rápidamente.

---

## 📋 Tabla de Contenidos

1. [Inicio Rápido](#-inicio-rápido)
2. [Problemas de Instalación](#-problemas-de-instalación)
3. [Problemas de Base de Datos](#-problemas-de-base-de-datos)
4. [Problemas de Ollama/IA](#-problemas-de-ollama-ia)
5. [Problemas de Autenticación](#-problemas-de-autenticación)
6. [Problemas de Docker](#-problemas-de-docker)
7. [Problemas de Pago (Mercado Pago)](#-problemas-de-pago-mercado-pago)
8. [Problemas de Cloudinary](#-problemas-de-cloudinary)
9. [Problemas de Rendimiento](#-problemas-de-rendimiento)
10. [FAQ](#-faq)
11. [Contacto y Escalación](#-contacto-y-escalación)

---

## 🚀 Inicio Rápido

### Opción 1: Desarrollo Local (Recomendado)

```bash
# 1. Clonar repositorio
git clone https://github.com/tuusuario/CostaDeOroImports.git
cd CostaDeOroImports

# 2. Crear archivo .env (copia del .env.example)
cp .env.example .env

# 3. Editar .env con tus valores
nano .env

# 4. Iniciar Ollama en terminal separada
ollama serve

# 5. En otra terminal, construir y ejecutar
mvn clean install
mvn spring-boot:run

# 6. Acceder a la app
open http://localhost:8080
```

### Opción 2: Docker Compose (Todo integrado)

```bash
# 1. Clonar repositorio
git clone https://github.com/tuusuario/CostaDeOroImports.git
cd CostaDeOroImports

# 2. Crear .env
cp .env.example .env
nano .env

# 3. Levantar todo
docker-compose up -d

# 4. Acceder
open http://localhost:8080
```

> [!TIP]
> Usa la Opción 1 si haces desarrollo frecuente (hot reload). Usa Opción 2 si solo quieres ejecutar el proyecto.

---

## ⚙️ Problemas de Instalación

### Error: `mvn: comando no encontrado`

**Causa:** Maven no está instalado o no está en el PATH.

**Solución:**

```bash
# Verificar si Maven está instalado
mvn --version

# Si no: Instalar Maven
# En macOS con Homebrew
brew install maven

# En Windows (descarga desde)
# https://maven.apache.org/download.cgi
# Y agrega M2_HOME a tu PATH

# En Linux (Ubuntu/Debian)
sudo apt-get install maven
```

### Error: `Java version not supported`

**Causa:** Java 21 no está instalado.

**Solución:**

```bash
# Verificar versión actual
java -version

# Descargar Java 21 desde Adoptium
# https://adoptium.net/

# O instalar via Homebrew (macOS)
brew install openjdk@21

# O via apt (Ubuntu/Debian)
sudo apt-get install openjdk-21-jdk
```

### Error: `No such file or directory: .env`

**Causa:** El archivo .env no existe.

**Solución:**

```bash
# Crear .env basado en el template
cp .env.example .env

# Editar con tu editor favorito
nano .env  # o vim, code, etc.

# Verificar que existe
ls -la .env
```

> [!IMPORTANT]
> El archivo `.env` es crítico. Sin él, la app no funcionará.

---

## 🗄️ Problemas de Base de Datos

### Error: `Connection refused: localhost:3306`

**Causa:** MySQL no está corriendo o no está accesible.

**Solución 1: Usar Docker para MySQL**

```bash
# Levantar solo MySQL
docker run -d \
  -e MYSQL_ROOT_PASSWORD=tu_password \
  -e MYSQL_DATABASE=costa_de_oro \
  -p 3306:3306 \
  mysql:8.0

# O usar docker-compose
docker-compose up -d mysql
```

**Solución 2: Usar H2 (desarrollo local)**

```properties
# application.properties
spring.datasource.url=jdbc:h2:mem:costa_de_oro
spring.datasource.driverClassName=org.h2.Driver
spring.jpa.database-platform=org.hibernate.dialect.H2Dialect
spring.h2.console.enabled=true
```

Luego accede a: http://localhost:8080/h2-console

**Solución 3: MySQL instalado localmente**

```bash
# Verificar que MySQL esté corriendo
mysql -u root -p

# Si no está corriendo, iniciar
# En macOS
brew services start mysql@8.0

# En Linux
sudo systemctl start mysql

# En Windows (Powershell admin)
net start MySQL80
```

### Error: `Access denied for user 'root'@'localhost'`

**Causa:** Credenciales incorrectas en .env

**Solución:**

```bash
# 1. Verificar credenciales
cat .env | grep DB_

# 2. Si olvidaste password de MySQL
mysql -u root --skip-password
# Luego en MySQL
ALTER USER 'root'@'localhost' IDENTIFIED BY 'nueva_password';

# 3. Actualizar .env
nano .env
# Cambiar DB_PASSWORD=nueva_password
```

### Error: `Table doesn't exist`

**Causa:** Las migraciones de base de datos no se ejecutaron.

**Solución:**

```bash
# Opción 1: Borrar y recrear base de datos
mysql -u root -p -e "DROP DATABASE costa_de_oro; CREATE DATABASE costa_de_oro CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Opción 2: Ejecutar SQL de inicialización
mysql -u root -p costa_de_oro < src/main/resources/schema.sql

# Opción 3: Dejar que Hibernate la cree
# En application.properties
spring.jpa.hibernate.ddl-auto=create-drop  # o 'create'
```

> [!WARNING]
> `create-drop` borra datos cada vez que se reinicia. Úsalo solo en desarrollo.

---

## 🤖 Problemas de Ollama/IA

### Error: `Connection refused: http://localhost:11434`

**Causa:** Ollama no está ejecutándose.

**Solución:**

```bash
# Terminal 1: Iniciar Ollama
ollama serve

# Terminal 2: Probar conexión
curl http://localhost:11434/api/tags

# Si curl devuelve JSON con modelos, Ollama está OK
```

### Error: `Model not found: gemma3:latest`

**Causa:** El modelo no está descargado.

**Solución:**

```bash
# Ver modelos disponibles
ollama list

# Descargar el modelo
ollama pull gemma3:latest

# O descargar alternativo
ollama pull llama3
ollama pull mistral

# Verificar descarga
ollama list
```

> [!NOTE]
> La primera descarga puede tardar 5-30 minutos según tu conexión. Los modelos ocupan 3-10 GB.

### Error: `Response is empty`

**Causa:** El modelo tardó demasiado o agotó recursos.

**Solución:**

```bash
# 1. Verificar recursos disponibles
# En macOS
top

# En Linux
htop

# En Windows (Powershell)
Get-Process | Sort-Object WorkingSet -Descending | Select -First 10

# 2. Si Ollama usa mucha RAM/CPU, usar modelo más pequeño
ollama pull tinyllama  # Muy rápido, ~2GB
ollama pull neural-chat  # Balanceado

# 3. Aumentar timeout en application.properties
spring.ai.ollama.chat.options.num-predict=150
```

### Error: `Model is too large for available memory`

**Causa:** El modelo requiere más VRAM de la disponible.

**Solución:**

```bash
# Usar modelo más pequeño
ollama pull tinyllama
ollama pull neural-chat

# En application.properties
spring.ai.ollama.chat.options.model=tinyllama:latest
```

> [!TIP]
> Para desarrollo: `tinyllama` (2GB). Para producción: `llama3` (8GB) o `mistral` (7GB).

---

## 🔐 Problemas de Autenticación

### Error: `JWT token expired`

**Causa:** El token JWT expiró.

**Solución:**

```bash
# En cliente (browser/app)
# 1. Refrescar el token
POST /api/auth/refresh
Header: Authorization: Bearer <tu_token_viejo>

# 2. O re-loguéate
POST /api/auth/login
Body: { "email": "...", "password": "..." }
```

### Error: `Invalid JWT signature`

**Causa:** Token corrupto o secreto diferente.

**Solución:**

```bash
# 1. Verificar que JWT_SECRET es igual en todas partes
# En application.properties, Docker, CI/CD
grep JWT_SECRET .env
echo $JWT_SECRET  # En terminal

# 2. Si cambió el secreto, los tokens viejos son inválidos
# Los usuarios deben re-loguear
```

### Error: `Access Denied` en endpoints admin

**Causa:** El usuario no tiene rol ADMIN.

**Solución:**

```bash
# En base de datos, actualizar rol
mysql -u root -p costa_de_oro -e "UPDATE users SET role='ROLE_ADMIN' WHERE email='tumail@example.com';"

# O en la app, usar una cuenta admin existente
```

---

## 🐳 Problemas de Docker

### Error: `docker: command not found`

**Solución:**

```bash
# Descargar Docker desde
# https://www.docker.com/products/docker-desktop/

# O instalar via script (Linux)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

### Error: `docker-compose: command not found`

**Solución:**

```bash
# Docker Desktop incluye compose. Si lo instalaste manual:
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### Error: `Port 8080 already in use`

**Solución:**

```bash
# Opción 1: Matar proceso que usa puerto 8080
# En macOS/Linux
lsof -i :8080
kill -9 <PID>

# En Windows (Powershell admin)
Get-Process -Id (Get-NetTCPConnection -LocalPort 8080).OwningProcess | Stop-Process

# Opción 2: Cambiar puerto en docker-compose.yml
# Cambiar:   "8080:8080"
# Por:       "9090:8080"  # Acceder en localhost:9090
```

### Error: `Can't connect to database from container`

**Solución:**

```bash
# En docker-compose.yml, asegúrate que:
# 1. mysql y app estén en el mismo network (por defecto, lo están)
# 2. El connection string sea correcto:
DB_URL=jdbc:mysql://mysql:3306/costa_de_oro  # 'mysql' es el service name

# 3. Ver logs
docker-compose logs mysql
docker-compose logs app
```

### Error: `docker-compose up` tarda mucho

**Solución:**

```bash
# Ver qué está tomando tiempo
docker-compose up  # Sin -d para ver logs

# Si es Ollama que descarga modelo:
# Paciencia, puede tardar 15-30 minutos la primera vez

# Si es Maven que compila:
# Usa cache: docker-compose up --build
```

---

## 💳 Problemas de Pago (Mercado Pago)

### Error: `Invalid Mercado Pago credentials`

**Causa:** Token de acceso incorrecto o vencido.

**Solución:**

```bash
# 1. Obtener nuevas credenciales
# https://www.mercadopago.com/developers/panel/credentials

# 2. Copiar credenciales sandbox (para desarrollo)
# En .env
MERCADOPAGO_ACCESS_TOKEN=APP_USR-...  # sandbox token
MERCADOPAGO_PUBLIC_KEY=APP_USR-...    # sandbox public key

# 3. Verificar que Mercado Pago SDK esté actualizado
mvn dependency:tree | grep mercado

# 4. Reiniciar la aplicación
```

### Error: `Payment preference creation failed`

**Causa:** Datos de pago incompletos.

**Solución:**

```bash
# En el controller, verificar que envías:
{
  "amount": 100.00,
  "description": "Producto X",
  "currency": "ARS",
  "buyerEmail": "cliente@example.com"
}

# Si falta algún campo, la API rechaza
```

### Error: `Callback webhook not received`

**Causa:** Webhook no configurado o URL incorrecta.

**Solución:**

```bash
# 1. En panel de Mercado Pago
# https://www.mercadopago.com/developers/panel/webhooks

# 2. Configurar URLs:
# - Success: https://tudominio.com/api/payment/success
# - Failure: https://tudominio.com/api/payment/failure
# - Pending: https://tudominio.com/api/payment/pending

# 3. Para desarrollo local, usar Ngrok para exponer localhost
# https://ngrok.com/

# Ejemplo:
ngrok http 8080
# Luego usar: https://abc123.ngrok.io/api/payment/...
```

---

## ☁️ Problemas de Cloudinary

### Error: `Cloudinary API key invalid`

**Solución:**

```bash
# 1. Obtener credenciales correctas
# https://cloudinary.com/console

# 2. Copiar en .env
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret

# 3. Reiniciar app
```

### Error: `Upload failed: 429 Too Many Requests`

**Causa:** Límite de uploads por minuto alcanzado.

**Solución:**

```bash
# Implementar retry logic en CloudinaryService
int maxRetries = 3;
for (int i = 0; i < maxRetries; i++) {
    try {
        uploadImage(...);
        break;
    } catch (Exception e) {
        if (i == maxRetries - 1) throw e;
        Thread.sleep(1000 * (i + 1));  // Backoff exponencial
    }
}
```

---

## ⚡ Problemas de Rendimiento

### La app está lenta

**Diagnóstico:**

```bash
# 1. Ver uso de recursos
docker stats

# 2. Ver logs para queries lentas
tail -f logs/app.log | grep "WARN\|ERROR"

# 3. Activar SQL logging
spring.jpa.show-sql=true
spring.jpa.properties.hibernate.format_sql=true

# 4. Usar Spring Boot Actuator
curl http://localhost:8080/actuator/metrics
```

**Soluciones:**

```bash
# 1. Agregar índices en base de datos
CREATE INDEX idx_product_category ON products(category);
CREATE INDEX idx_order_user ON orders(user_id);

# 2. Aumentar memoria JVM
java -Xmx2g -Xms1g -jar app.jar

# 3. Usar caché para consultas frecuentes
@Cacheable("products")
public List<Product> getAllProducts() { ... }

# 4. Optimizar queries N+1
@EntityGraph(attributePaths = "category")
List<Product> findAll();
```

### Ollama responde lentamente

**Causa:** Modelo grande o hardware insuficiente.

**Solución:**

```bash
# 1. Usar modelo más pequeño
ollama pull tinyllama

# 2. Limitar tokens de respuesta
spring.ai.ollama.chat.options.num-predict=100  # Menos tokens = más rápido

# 3. Reducir temperatura
spring.ai.ollama.chat.options.temperature=0.3  # Menos creatividad = más rápido
```

---

## ❓ FAQ

### P: ¿Necesito instalar Ollama si uso OpenAI?

**R:** No. Cambia en `application.properties`:

```properties
# En lugar de Ollama
spring.ai.openai.api-key=${SPRING_AI_OPENAI_API_KEY}
spring.ai.openai.chat.model=gpt-4-turbo
```

### P: ¿Cómo uso la app en producción?

**R:** Lee [DEPLOYMENT.md](DEPLOYMENT.md) (próxima mejora). Por ahora:

```bash
# 1. Compilar con perfil prod
mvn clean install -Pprod

# 2. Crear imagen Docker
docker build -t costadeoro:prod .

# 3. Desplegar en Kubernetes o cualquier hosting
```

### P: ¿Cómo contribuyo?

**R:** Lee [CONTRIBUTING.md](CONTRIBUTING.md) o el README.md, sección Contribuciones.

### P: ¿Dónde reporesto bugs?

**R:** En GitHub Issues. Para seguridad, ve a [SECURITY.md](SECURITY.md).

### P: ¿Cómo accedo a los logs?

**R:**

```bash
# Desarrollo
tail -f logs/app.log

# Docker
docker-compose logs -f app

# Kubernetes
kubectl logs -f deployment/costadeoro
```

### P: ¿Cómo reseteo mi contraseña?

**R:** Usa el endpoint de recuperación (próximo):

```bash
POST /api/auth/forgot-password
Body: { "email": "tumail@example.com" }
```

Por ahora, contacta a support@costadeoro.com

---

## 📞 Contacto y Escalación

Si tu problema no está aquí:

| Categoría | Contacto | Tiempo Respuesta |
|-----------|----------|:----------------:|
| **Bug técnico** | GitHub Issues | 24-48h |
| **Seguridad** | security@costadeoro.com | 24h |
| **Pago/Billing** | billing@costadeoro.com | 24h |
| **General** | support@costadeoro.com | 72h |

### Información útil para reportar

Cuando abras un issue, incluye:

```
### Descripción
[Describe qué pasó]

### Pasos para reproducir
1. Hice esto...
2. Luego eso...
3. Esperaba X, pero pasó Y

### Logs/Error
[Copia logs relevantes]

### Entorno
- OS: [Windows/macOS/Linux]
- Java: [java -version]
- Maven: [mvn -version]
- Docker: [docker --version]
```

---

**Última actualización:** Julio 2026  
**Versión Help:** 2.0
