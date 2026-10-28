# 🔐 Security Policy

Última actualización: Julio 2026

---

## 📋 Tabla de Contenidos

1. [Versiones Soportadas](#-versiones-soportadas)
2. [Reporte de Vulnerabilidades](#-reporte-de-vulnerabilidades)
3. [Proceso de Divulgación Responsable](#-proceso-de-divulgación-responsable)
4. [Escala CVSS](#-escala-cvss)
5. [Herramientas de Seguridad](#-herramientas-de-seguridad)
6. [Actualizaciones de Seguridad](#-actualizaciones-de-seguridad)
7. [Mejores Prácticas](#-mejores-prácticas-de-seguridad)
8. [Verificación de Dependencias](#-verificación-de-dependencias)
9. [Incidentes de Seguridad](#-incidentes-de-seguridad)
10. [Preguntas Frecuentes](#-preguntas-frecuentes)

---

## 📦 Versiones Soportadas

Las siguientes versiones del proyecto están siendo **activamente soportadas** con actualizaciones de seguridad:

| Versión Java | Soporte | Fin de Soporte | Notas |
|:-------------:|:-------:|:--------------:|-------|
| **21.x (LTS)** | ✅ Activo | Septiembre 2031 | Recomendado para producción |
| **17.x (LTS)** | ✅ Activo | Septiembre 2026 | Soporte a corto plazo |
| **< 17.x** | ❌ Fin de vida | - | Actualiza inmediatamente |

> [!IMPORTANT]
> Java 21 es LTS (Long Term Support). Se recomienda **como mínimo** Java 17 para desarrollo. Para nuevos proyectos, usa **Java 21**.

### Spring Boot y Spring AI

| Componente | Versión | Estado | EOL |
|:-----------|:-------:|:------:|:---:|
| **Spring Boot** | 4.1.0 | ✅ Soportado | Dic 2027 |
| **Spring AI** | 2.0.0 | ✅ Soportado | Dic 2026 |
| **Spring Security** | Última | ✅ Activa | Sigue a Boot |

> [!WARNING]
> Si usas versiones menores de Spring Boot 4.1 o Spring AI < 2.0, **actualiza inmediatamente**. Versiones antiguas tienen vulnerabilidades conocidas.

---

## 🛡️ Reporte de Vulnerabilidades

Si encuentras una vulnerabilidad de seguridad en este proyecto, te pedimos que **no la publiques públicamente** en Issues de GitHub. En su lugar, reporta responsablemente.

### Canales de Reporte

| Método | Detalles | Tiempo de Respuesta |
|--------|----------|:------------------:|
| **Email** | `security@costadeoro.com` | 24-48 horas |
| **Security Advisory** | Usa el formulario de GitHub | 24-48 horas |
| **PGP Encryption** | Disponible bajo solicitud | 24-48 horas |

### Información a Incluir

```
Asunto: [SECURITY] Reporte de Vulnerabilidad - [Brevísima descripción]

Cuerpo:
1. Descripción detallada de la vulnerabilidad
2. Pasos para reproducirla
3. Impacto potencial (datos, servicios, usuarios afectados)
4. Versiones afectadas
5. Sugerencia de fix (si tienes una)
6. Tu información de contacto (email, nombre opcional)
7. Si prefieres ser acreditado en release notes
```

> [!IMPORTANT]
> **Nunca crees un Issue público** con detalles de vulnerabilidades. Usa email o el formulario privado de GitHub.

> [!TIP]
> Incluye **proof-of-concept** siempre que sea posible. Ayuda a validar rápidamente.

---

## 🔄 Proceso de Divulgación Responsable

Seguimos el estándar de **Responsible Disclosure (CVE)**:

```
1. Reporte recibido
   ↓
2. Validación (24-48 hrs)
   ├─ Aceptado → Paso 3
   └─ Rechazado → Explicación al reportero
   ↓
3. Desarrollo de fix en rama privada (1-7 días)
   ↓
4. Testing y verificación
   ↓
5. Publicación de parche (patch release)
   ↓
6. Divulgación pública + CVE (si aplica)
   ↓
7. Acreditación en release notes (si lo deseas)
```

### Cronograma esperado

- **Vulnerabilidades Críticas (CVSS 9-10):** Fix en 48 horas
- **Vulnerabilidades Altas (CVSS 7-8.9):** Fix en 1 semana
- **Vulnerabilidades Medias (CVSS 4-6.9):** Fix en 2 semanas
- **Vulnerabilidades Bajas (CVSS 0-3.9):** Fix en próxima release

> [!NOTE]
> Los plazos pueden extenderse si el fix requiere cambios arquitectónicos mayores. Te mantendremos informado.

---

## 📊 Escala CVSS

Usamos **CVSS v3.1** para clasificar severidad. Aquí están las bandas:

| Severidad | Rango CVSS | Color | Acción |
|-----------|:----------:|:-----:|--------|
| **Crítica** | 9.0-10.0 | 🔴 Rojo | Patch inmediato + comunicado |
| **Alta** | 7.0-8.9 | 🟠 Naranja | Patch en < 1 semana |
| **Media** | 4.0-6.9 | 🟡 Amarillo | Patch en próxima release |
| **Baja** | 0.1-3.9 | 🟢 Verde | Patch en siguiente versión |

**Ejemplo:** Una vulnerabilidad de inyección SQL en un endpoint administrativo sería **Crítica (CVSS 9.5)** porque:
- Alcance: Red
- Complejidad: Baja
- Privilegios requeridos: Ninguno o bajos
- Impacto: Confidencialidad + Integridad + Disponibilidad

---

## 🔧 Herramientas de Seguridad

### 1. Dependabot (GitHub Native)

Escanea automáticamente vulnerabilidades en dependencias:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "maven"
    directory: "/"
    schedule:
      interval: "daily"
    open-pull-requests-limit: 10
```

**Verificar resultados:**
- Ve a **Settings > Code security and analysis > Dependabot alerts**
- Revisa PRs creadas automáticamente por Dependabot

### 2. OWASP Dependency-Check

Ejecuta escaneo local:

```bash
# Via Maven
mvn org.owasp:dependency-check-maven:check

# Via Docker
docker run --rm -v $(pwd):/src \
  owasp/dependency-check:latest \
  --scan /src --format HTML --project "Costa de Oro"
```

Esto genera un reporte HTML con vulnerabilidades conocidas.

### 3. Snyk (Opcional - SaaS)

Para escaneo continuo en CI/CD:

```yaml
# En GitHub Actions
- name: Run Snyk scan
  uses: snyk/actions/maven@master
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
```

### 4. Spring Security Advisories

Spring publica advisories en: https://spring.io/security/cve/

Úscalos regularmente.

> [!TIP]
> Ejecuta `mvn dependency:tree | grep -i security` para ver qué versiones de Spring Security tienes.

---

## 🔄 Actualizaciones de Seguridad

### Política de Actualización

- **Parches de seguridad críticos:** Se publican como hotfixes en cualquier momento
- **Menores con seguridad:** Se incluyen en releases mensuales
- **Dependencias:** Se actualizan semanalmente via Dependabot

### Proceso de Aplicar Actualizaciones

```bash
# 1. Clonar/Pullear último código
git pull origin main

# 2. Verificar vulnerabilidades localmente
mvn clean install
mvn org.owasp:dependency-check-maven:check

# 3. Revisar cambios en dependencias
git log --oneline -10 | grep -i "security\|bump"

# 4. Ejecutar tests
mvn test

# 5. Desplegar (si todo está bien)
docker-compose up --build
```

### Notification Subscribe

Para recibir alertas de seguridad:

1. **Watch** este repositorio (Settings > Watch)
2. Selecciona: "All Activity" o al menos "Releases"
3. O suscríbete a releases: https://github.com/tuusuario/CostaDeOroImports/releases.atom

> [!IMPORTANT]
> Configura notificaciones de GitHub en tu correo personal. No dependas solo de in-app notifications.

---

## 🛡️ Mejores Prácticas de Seguridad

### Backend (Java/Spring Boot)

#### 1. Autenticación y Autorización

```java
// ✅ BIEN: Usar @PreAuthorize con expresiones SPEL
@PreAuthorize("hasRole('ADMIN')")
@DeleteMapping("/api/products/{id}")
public ResponseEntity<?> deleteProduct(@PathVariable Long id) {
    // Solo admins
}

// ✅ BIEN: Validar permisos a nivel de objeto
@GetMapping("/api/orders/{id}")
public ResponseEntity<?> getOrder(@PathVariable Long id) {
    Order order = orderService.findById(id);
    if (!order.getUser().getId().equals(getCurrentUserId())) {
        throw new AccessDeniedException("No tienes permisos");
    }
    return ResponseEntity.ok(order);
}

// ❌ MAL: Confiar solo en URL patterns
@GetMapping("/admin/panel")  // Insuficiente
```

#### 2. Validación de Entrada

```java
// ✅ BIEN: Validar con Bean Validation + Custom
@PostMapping("/api/products")
public ResponseEntity<?> createProduct(
    @Valid @RequestBody ProductRequest request) {
    // @Valid valida anotaciones @NotNull, @Size, etc.
    // Validación ocurre automáticamente
}

// ❌ MAL: Confiar en tipos
@PostMapping("/api/products")
public ResponseEntity<?> createProduct(ProductRequest request) {
    // Sin validación = inyecciones posibles
}
```

#### 3. Inyección SQL

```java
// ✅ BIEN: Usar JPA Queries + Parámetros
repository.findByNameAndCategory(name, category);
// JPA usa prepared statements internamente

// ❌ MAL: Concatenar strings
Query q = em.createQuery("SELECT p FROM Product p WHERE name = '" + name + "'");
// Vulnerable a SQL injection
```

#### 4. XSS (Cross-Site Scripting)

```html
<!-- ✅ BIEN: Thymeleaf auto-escapa por defecto -->
<p th:text="${product.name}"></p>

<!-- ❌ MAL: No escaper HTML -->
<p>[[${product.name}]]</p>

<!-- ❌ MAL: Usar unescape explícitamente -->
<p th:utext="${product.description}"></p>
```

#### 5. CSRF (Cross-Site Request Forgery)

```html
<!-- ✅ BIEN: Spring Security genera token CSRF -->
<form th:action="@{/api/cart/add}" method="post">
    <input type="hidden" th:name="${_csrf.parameterName}" 
           th:value="${_csrf.token}" />
    <input type="submit" value="Agregar" />
</form>

<!-- O en AJAX: -->
<script>
    fetch('/api/cart/add', {
        method: 'POST',
        headers: {
            'X-CSRF-TOKEN': document.querySelector('meta[name="_csrf"]').content
        }
    });
</script>
```

#### 6. Cifrado de Contraseñas

```java
// ✅ BIEN: Usar BCrypt con salt
@Bean
public PasswordEncoder passwordEncoder() {
    return new BCryptPasswordEncoder(12); // strength 12
}

// En UserService
user.setPassword(passwordEncoder.encode(rawPassword));

// ❌ MAL: Almacenar en plain text o MD5
user.setPassword(rawPassword); // CRÍTICO
user.setPassword(md5(rawPassword)); // Inseguro
```

#### 7. JWT Seguro

```properties
# ✅ BIEN: Clave fuerte, algoritmo HS256+ con sal
jwt.secret=tu-clave-super-secreta-de-256-bits-minimo-generada-aleatoriamente
jwt.expiration=86400000  # 24 horas
jwt.algorithm=HS512

# ❌ MAL: Expiración larga
jwt.expiration=31536000000  # 1 año
```

```java
// ✅ BIEN: Validar firma siempre
@Component
public class JwtUtil {
    public boolean isTokenValid(String token) {
        try {
            Jwts.parserBuilder()
                .setSigningKey(key)
                .build()
                .parseClaimsJws(token);
            return true;
        } catch (JwtException e) {
            return false;
        }
    }
}
```

#### 8. Logs Seguros

```java
// ✅ BIEN: No loguear datos sensibles
logger.info("Usuario {} inició sesión", username);

// ❌ MAL: Loguear passwords, tokens, etc.
logger.info("Login credentials: {}", password);  // NO
logger.info("JWT: {}", token);  // NO
```

### Frontend (Thymeleaf + JavaScript)

#### 1. Content Security Policy (CSP)

```java
@Configuration
public class SecurityConfig {
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.headers(headers -> headers
            .contentSecurityPolicy(csp -> csp
                .policyDirectives("default-src 'self'; " +
                    "script-src 'self' 'unsafe-inline'; " +
                    "style-src 'self' 'unsafe-inline'; " +
                    "img-src 'self' data: https:; " +
                    "font-src 'self'"
                )
            )
        );
        return http.build();
    }
}
```

#### 2. Rate Limiting

```java
@Component
public class RateLimitInterceptor implements HandlerInterceptor {
    private final RateLimiter rateLimiter = RateLimiter.create(10.0); // 10 req/sec

    @Override
    public boolean preHandle(HttpServletRequest request, 
                           HttpServletResponse response, 
                           Object handler) throws Exception {
        if (!rateLimiter.tryAcquire()) {
            response.sendError(HttpStatus.TOO_MANY_REQUESTS.value());
            return false;
        }
        return true;
    }
}
```

#### 3. HTTPS Enforcement

```properties
# application.properties
server.ssl.enabled=true
server.ssl.key-store=classpath:keystore.p12
server.ssl.key-store-password=${SSL_PASSWORD}

# Forzar HTTPS en producción
server.error.whitelabel.enabled=false
```

### Infraestructura (Docker/Kubernetes)

#### 1. Dockerfile Seguro

```dockerfile
# ✅ BIEN: No ejecutar como root
FROM eclipse-temurin:21-jdk-alpine
RUN addgroup -S java && adduser -S java -G java
USER java

# ✅ BIEN: Usar imagen base mínima
FROM eclipse-temurin:21-jdk-alpine  # Pequeña y segura

# ❌ MAL: Usar ubuntu/debian full
FROM ubuntu:22.04  # Mucho más grande y vulnerable
```

#### 2. Secretos en Docker Compose

```yaml
# ✅ BIEN: Usar .env y variables
version: '3.8'
services:
  app:
    environment:
      DB_PASSWORD: ${DB_PASSWORD}
      JWT_SECRET: ${JWT_SECRET}

# ❌ MAL: Hardcodear secretos
services:
  app:
    environment:
      DB_PASSWORD: "admin123"  # Visible en git
```

> [!CAUTION]
> **Nunca** commitees `.env` a Git. Agrega a `.gitignore` inmediatamente.

---

## 🔍 Verificación de Dependencias

### Ejecutar Análisis Localmente

```bash
# 1. Analizar dependencias vulnerables
mvn dependency:tree > deps.txt
grep -i "security\|crypto\|auth" deps.txt

# 2. Buscar vulnerabilidades conocidas
mvn org.owasp:dependency-check-maven:check

# 3. Ver reporte HTML
open target/dependency-check-report.html

# 4. Actualizar dependencias seguras
mvn versions:display-updates
mvn versions:use-latest-releases
```

### Interpretar Reportes

```
[INFO] NVD Advisories Found
[WARN] CVE-2024-12345 (HIGH) in org.springframework:spring-core:5.x.x
       Description: Remote Code Execution vulnerability
       Fix: Update to version 6.x.x
```

Acciones:

1. Si CVSS ≥ 7: **Actualiza inmediatamente**
2. Si CVSS 4-6: **Planifica actualización para próxima release**
3. Si CVSS < 4: **Agenda en backlog**

---

## 🚨 Incidentes de Seguridad

Si descubrimos una vulnerabilidad en nuestro código (no reportada externamente):

1. Creamos una rama privada con el fix
2. Publicamos un parche (patch version bump)
3. Emitimos un comunicado de seguridad
4. Actualizamos esta SECURITY.md

### Histórico de Incidentes

_Sin incidentes reportados hasta la fecha. Mantén esta página actualizada._

> [!NOTE]
> Si alguna vez tenemos un incidente, lo documentaremos aquí con:
> - Fecha de descubrimiento
> - CVSS score
> - Componentes afectados
> - Versión del fix
> - Workarounds temporales (si aplican)

---

## ❓ Preguntas Frecuentes

### ¿Cómo reporto vulnerabilidades sin quedar identificado?

Puedes usar una cuenta de correo anónima. Mencionalo al inicio del reporte. Respetamos tu privacidad.

### ¿Cuál es el SLA (Service Level Agreement) de respuesta?

- **Crítica:** 24 horas confirmación + 48 horas fix
- **Alta:** 48 horas confirmación + 1 semana fix
- **Media/Baja:** Best effort

### ¿Qué pasa si no arreglan una vulnerabilidad reportada?

1. Te notificamos el estado
2. Si hay razón válida (ejg. arquitectura), te explicamos alternativas
3. Puedes escalar a [security-escalation@costadeoro.com]

### ¿Necesito realizar pruebas de penetración?

**Sí**, especialmente antes de producción:

```bash
# Recomendaciones:
- OWASP Top 10 test
- Penetration testing
- Code review de seguridad
```

Contacta a un especialista en seguridad.

### ¿Cada cuándo auditamos seguridad?

- **Análisis automatizado:** Diariamente (Dependabot + GitHub Advanced Security)
- **Revisión manual:** Semanalmente
- **Auditoría profesional:** Anualmente (recomendado)

### ¿Cómo me mantengo actualizado sobre CVEs?

1. **Subscribe a alertas:** GitHub > Settings > Code security
2. **Síguenos en redes:** Twitter/LinkedIn anuncios importantes
3. **Feed:** https://github.com/tuusuario/CostaDeOroImports/releases.atom

### ¿Es este proyecto candidato a Bug Bounty?

No en este momento. Si cambio en el futuro, lo anunciaremos aquí.

---

## 📞 Contactos de Seguridad

| Rol | Email | Response Time |
|-----|-------|:---------------:|
| **Security Lead** | `victor@costadeoro.com` | 24h |
| **Escalación** | `security-escalation@costadeoro.com` | 48h |
| **Consulta General** | `support@costadeoro.com` | 72h |

---

## 📚 Referencias Externas

- [OWASP Top 10 2024](https://owasp.org/www-project-top-ten/)
- [Spring Security Documentation](https://spring.io/projects/spring-security)
- [CVSS Score Guide](https://www.first.org/cvss/)
- [CWE Most Dangerous](https://cwe.mitre.org/top25/2024/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

---

**Última actualización:** Julio 2026  
**Versión Policy:** 2.0  
**Próxima revisión:** Enero 2027
