# Logging & Monitoring

Reglas para logging seguro, structured logging con 5W, y alertas mínimas.

**Cheatsheets oficiales que aplican:**
- [Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [Application Logging Vocabulary](https://cheatsheetseries.owasp.org/cheatsheets/Application_Logging_Vocabulary_Cheat_Sheet.html)
- [Error Handling](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html)

**OWASP IDs:** A09:2025, A10:2025, DSGAI14

---

## Por qué importa

Sin logs:
- No detectás ataques (intentos de IDOR, brute force, anomalías)
- No podés investigar incidentes (qué pasó, quién, cuándo)
- No respondés a auditorías
- No depurás bugs en producción

Con logs **mal hechos**:
- Leakeás PII, tokens, passwords
- Llenás el disco / la cuota de Cloud Logging
- No podés filtrar / buscar
- Generás más ruido que señal

---

## El framework 5W

Cada log estructurado debe responder:

| W | Qué | Campo |
|---|---|---|
| **Who** | Quién hizo la acción | `userId`, `clientId` (service-to-service) |
| **What** | Qué acción / endpoint | `action`, `method`, `path` |
| **When** | Cuándo | `timestamp` (ISO 8601, UTC) |
| **Where** | Sobre qué recurso, desde dónde | `resourceId`, `ip`, `userAgent` |
| **Why outcome** | Resultado y por qué | `statusCode`, `outcome` (success/failure), `reason` |

### Plus: trace context

| Campo | Para qué |
|---|---|
| `requestId` | Trazar una request end-to-end (frontend → backend → DB) |
| `traceId` | Compatibilidad con OpenTelemetry / Cloud Trace |
| `spanId` | Spans dentro del trace |

### Plus: contexto del servicio

| Campo | Para qué |
|---|---|
| `service` | Nombre del servicio (ej: `bo-orders`) |
| `version` | Versión deployada (git SHA o tag) |
| `env` | `dev` / `staging` / `prod` |

---

## Estructura recomendada del log

```json
{
  "timestamp": "2026-04-22T10:30:00.123Z",
  "level": "info",
  "service": "bo-orders",
  "version": "abc1234",
  "env": "prod",
  "requestId": "req_abc123",
  "traceId": "trace_xyz789",
  "userId": "user_5f8b...",
  "action": "GET /api/v1/orders/:id",
  "method": "GET",
  "path": "/api/v1/orders/abc-123",
  "statusCode": 200,
  "duration": 142,
  "ip": "10.0.1.5",
  "userAgent": "Mozilla/5.0...",
  "outcome": "success"
}
```

---

## Qué NUNCA loguear

```
❌ Passwords (incluso hasheados)
❌ Access tokens, refresh tokens, JWTs completos
❌ API keys, client_secrets
❌ Authorization headers
❌ Cookie values (especialmente session)
❌ Números de tarjeta de crédito, CVV
❌ Datos bancarios, números de cuenta
❌ Document numbers (DNI, pasaporte, SSN)
❌ Emails completos (mascará: jo***@example.com)
❌ Direcciones físicas completas
❌ Request bodies completos (pueden contener PII)
❌ Response bodies completos
❌ SQL queries con valores (parametrizalas en logs también)
❌ Stack traces que contienen valores sensibles
```

### Si necesitás loguear algo "casi sensible"

| Dato | Cómo loguearlo |
|---|---|
| Email | `jo***@cashea.app` |
| Phone | `***-***-1234` |
| Card | `****1234` |
| User ID | El UUID está bien (no es sensible per se) |
| Token | `***` o `tok_***` (los primeros 4 chars si necesitás trazar) |
| Auth header | `Bearer ***` |

---

## Niveles de log y cuándo usarlos

| Nivel | Cuándo |
|---|---|
| `debug` | Desarrollo local. NUNCA en prod. |
| `info` | Eventos de negocio normales (login, order created, etc.) |
| `warn` | Algo está mal pero el sistema sigue (deprecation, retry, throttle) |
| `error` | Falló algo y afectó al usuario (5xx, exception capturada) |
| `fatal` | El servicio se va a caer (crash, panic) |

**Reglas:**
- En prod, level mínimo es `info`
- Errores 4xx (validation, not found, forbidden) son `info` o `warn`, no `error` (no son errores del sistema)
- Errores 5xx son `error`

---

## Eventos de seguridad que SIEMPRE se loguean

Independiente del nivel general:

| Evento | Por qué |
|---|---|
| Login exitoso | Auditoría |
| Login fallido | Detectar brute force |
| Logout | Auditoría |
| Cambio de password | Auditoría |
| Cambio de permisos / roles | Auditoría |
| Token expirado / inválido (401) | Detectar token theft, replay |
| **403 Forbidden** | **Detectar IDOR / BOLA attempts** |
| Acceso a datos sensibles | Auditoría |
| Acción admin | Auditoría |
| Rate limit hit | Detectar abuso |
| Validación de input fallida en patrones sospechosos | Detectar injection attempts |

---

## Implementación

### NestJS — Pino logger

```typescript
// main.ts
import { LoggerModule } from 'nestjs-pino';

@Module({
  imports: [
    LoggerModule.forRoot({
      pinoHttp: {
        level: process.env.LOG_LEVEL || 'info',
        formatters: {
          level: (label) => ({ level: label }),
        },
        timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
        redact: {
          paths: [
            'req.headers.authorization',
            'req.headers.cookie',
            'req.body.password',
            'req.body.token',
            'req.body.creditCard',
            '*.password',
            '*.token',
            '*.apiKey',
          ],
          censor: '***',
        },
        serializers: {
          req: (req) => ({
            id: req.id,
            method: req.method,
            url: req.url,
            // No incluir body por default
          }),
        },
      },
    }),
  ],
})
export class AppModule {}
```

### Python — structlog

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Custom processor para redactar campos sensibles
        redact_sensitive_fields,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()

def redact_sensitive_fields(logger, method_name, event_dict):
    SENSITIVE_KEYS = {'password', 'token', 'authorization', 'api_key', 'card_number'}
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in SENSITIVE_KEYS):
            event_dict[key] = '***'
    return event_dict

# Uso
logger.info(
    "order_created",
    user_id=user.id,
    order_id=order.id,
    amount=order.amount,  # OK loguear el monto
    request_id=request.headers.get("x-request-id"),
)
```

---

## Request ID end-to-end

Cada request debe tener un ID único que se propaga del frontend al backend al servicio downstream:

```
Frontend genera requestId      → Header X-Request-ID: abc123
Backend lo recibe, lo loguea   → todos los logs de esa request tienen requestId=abc123
Backend llama a otro servicio  → propaga el header X-Request-ID
Cliente HTTP                   → todos sus logs incluyen el mismo requestId
```

```typescript
// NestJS interceptor
@Injectable()
export class RequestIdInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler) {
    const req = context.switchToHttp().getRequest();
    req.id = req.headers['x-request-id'] || randomUUID();
    return next.handle();
  }
}
```

---

## Error handling sin leak

Cuando se loguea un error, el log tiene todo el detalle. La response al cliente, no.

```typescript
// Filter global en NestJS
@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request>();

    const status = exception instanceof HttpException
      ? exception.getStatus()
      : 500;

    // Loguear todo (server-side)
    this.logger.error({
      requestId: request.id,
      path: request.url,
      method: request.method,
      statusCode: status,
      error: exception instanceof Error ? {
        name: exception.name,
        message: exception.message,
        stack: exception.stack,
      } : exception,
    }, 'Request failed');

    // Responder al cliente (sin internals)
    const clientMessage = status < 500
      ? (exception as HttpException).message  // 4xx: mensaje específico OK
      : 'Internal server error';               // 5xx: mensaje genérico

    response.status(status).json({
      statusCode: status,
      message: clientMessage,
      requestId: request.id,
    });
  }
}
```

---

## Cloud Logging — sinks y retención

### Configuración recomendada

```
Default retention:    90 días
Application logs:     90 días
Audit logs (admin):   400 días (compliance)
Security events:     400 días
Debug logs:           7 días (si los activás temporalmente)
```

### Sinks

```bash
# Sink a BigQuery para análisis a largo plazo
gcloud logging sinks create security-events-sink \
  bigquery.googleapis.com/projects/myproj/datasets/security_logs \
  --log-filter='severity>=WARNING AND jsonPayload.event_type="security"'
```

---

## Alertas mínimas (Cloud Monitoring)

| Condición | Severidad | Notificar a |
|---|---|---|
| 5xx error rate > 5% en 5 min | Alert | On-call |
| Auth failures > 50 en 10 min | Alert | AppSec, on-call |
| **403 rate > 20 / usuario en 5 min** | Alert | **AppSec (posible IDOR/BOLA)** |
| Container restart > 3 en 10 min | Alert | On-call |
| Memory/CPU > 80% sostenido (15 min) | Warning | On-call |
| Anomalía en egress (data exfiltration) | Alert | AppSec |
| Acceso a secrets fuera de horario laboral | Warning | AppSec |
| Login admin desde IP no whitelisted | Alert | AppSec |
| Latencia p95 > 2s sostenida | Warning | On-call |

---

## Checklist de logging al implementar un servicio

```
[ ] Structured logger configurado (Pino, structlog, etc.)
[ ] Logs en JSON, no plain text
[ ] Redacción de campos sensibles configurada (password, token, auth, etc.)
[ ] Request ID generado / propagado en cada request
[ ] Logs incluyen los 5W (Who, What, When, Where, Why outcome)
[ ] Logs incluyen contexto de servicio (service, version, env)
[ ] Eventos de seguridad logueados (login, 401, 403, admin actions)
[ ] Error handler global que loguea full detail server-side y responde sanitized
[ ] No hay console.log() / print() en código (todos via logger)
[ ] Niveles de log apropiados (4xx → info/warn, 5xx → error)
[ ] Cloud Logging configurado con retention apropiada
[ ] Alertas mínimas configuradas en Cloud Monitoring
```
