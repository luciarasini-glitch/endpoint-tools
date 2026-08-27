# Node.js / NestJS

Particularidades de seguridad para servicios Node.js, especialmente con NestJS.

**Cheatsheets oficiales que aplican:**
- [Nodejs Security](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html)
- [REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [Microservices Security](https://cheatsheetseries.owasp.org/cheatsheets/Microservices_Security_Cheat_Sheet.html)

**OWASP IDs:** A05:2025, A03:2025, API3:2023, API4:2023, API8:2023

---

## Setup inicial — main.ts mínimo seguro

Todo proyecto NestJS debe arrancar con esto:

```typescript
import { NestFactory } from '@nestjs/core';
import { ValidationPipe, VersioningType } from '@nestjs/common';
import helmet from 'helmet';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, {
    logger: false,  // usar Pino o equivalente vía LoggerModule
  });

  // 1. Security headers
  app.use(helmet({
    contentSecurityPolicy: process.env.NODE_ENV === 'production' ? {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'"],
        styleSrc: ["'self'", "'unsafe-inline'"],  // si necesitás
        imgSrc: ["'self'", "data:", "https:"],
        connectSrc: ["'self'"],
        fontSrc: ["'self'"],
        objectSrc: ["'none'"],
        frameAncestors: ["'none'"],
      },
    } : false,
    crossOriginEmbedderPolicy: false,
  }));

  // 2. CORS — explícito, NUNCA wildcard en prod
  app.enableCors({
    origin: process.env.ALLOWED_ORIGINS?.split(',') || [],
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
  });

  // 3. Validation global
  app.useGlobalPipes(new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
    transform: true,
    forbidUnknownValues: true,
  }));

  // 4. Versioning
  app.enableVersioning({ type: VersioningType.URI });

  // 5. Body size limit
  app.use((req, res, next) => {
    // express body-parser ya viene, pero limitarlo
    next();
  });

  // 6. Swagger SOLO en non-prod
  if (process.env.NODE_ENV !== 'production') {
    // setup Swagger
  }

  await app.listen(process.env.PORT || 8080);
}
bootstrap();
```

---

## Validation con class-validator

### DTOs estrictos

```typescript
import { IsUUID, IsInt, IsString, IsEmail, IsOptional, Min, Max, MaxLength, IsEnum, ValidateNested, ArrayMaxSize } from 'class-validator';
import { Type } from 'class-transformer';

export class CreateOrderDto {
  @IsUUID()
  customerId: string;

  @IsString()
  @MaxLength(200)
  description: string;

  @IsEnum(['standard', 'express', 'priority'])
  shippingType: 'standard' | 'express' | 'priority';

  @IsArray()
  @ArrayMaxSize(50)
  @ValidateNested({ each: true })
  @Type(() => OrderItemDto)
  items: OrderItemDto[];
}

export class OrderItemDto {
  @IsUUID()
  productId: string;

  @IsInt()
  @Min(1)
  @Max(100)
  quantity: number;
}

export class ListOrdersQueryDto {
  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(100)
  @Type(() => Number)
  limit: number = 20;

  @IsOptional()
  @IsInt()
  @Min(0)
  @Type(() => Number)
  offset: number = 0;
}
```

### Custom validators

Para reglas de dominio (ej: validar formato de invoice number):

```typescript
import { registerDecorator, ValidationOptions } from 'class-validator';

export function IsInvoiceNumber(options?: ValidationOptions) {
  return function (object: object, propertyName: string) {
    registerDecorator({
      name: 'isInvoiceNumber',
      target: object.constructor,
      propertyName,
      options,
      validator: {
        validate(value: any) {
          return typeof value === 'string' && /^INV-\d{8}$/.test(value);
        },
      },
    });
  };
}
```

---

## Guards: auth y authz

### AuthGuard global

```typescript
// Aplicar globalmente
@Module({
  providers: [
    { provide: APP_GUARD, useClass: AuthGuard },
  ],
})
export class AppModule {}

// Implementación
@Injectable()
export class AuthGuard implements CanActivate {
  constructor(
    private readonly reflector: Reflector,
    private readonly jwtService: JwtService,
  ) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    // Permitir rutas marcadas como públicas
    const isPublic = this.reflector.get<boolean>('isPublic', ctx.getHandler());
    if (isPublic) return true;

    const req = ctx.switchToHttp().getRequest();
    const token = this.extractBearer(req);
    if (!token) throw new UnauthorizedException();

    try {
      const payload = await this.jwtService.verifyAsync(token, {
        algorithms: ['RS256'],
        issuer: process.env.OIDC_ISSUER,
        audience: process.env.OIDC_AUDIENCE,
      });
      req.user = payload;
      return true;
    } catch {
      throw new UnauthorizedException();
    }
  }

  private extractBearer(req: Request): string | undefined {
    const auth = req.headers.authorization || '';
    return auth.startsWith('Bearer ') ? auth.slice(7) : undefined;
  }
}

// Decorator para rutas públicas
export const Public = () => SetMetadata('isPublic', true);
```

### Usage

```typescript
@Controller('orders')
export class OrdersController {
  // Auth obligatorio (default por el guard global)
  @Get()
  list() { /* ... */ }

  // Público explícito
  @Public()
  @Get('health')
  health() { /* ... */ }
}
```

### RolesGuard / PermissionsGuard

```typescript
export const REQUIRED_PERMS = 'requiredPerms';
export const RequirePermissions = (...perms: string[]) => SetMetadata(REQUIRED_PERMS, perms);

@Injectable()
export class PermissionsGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(ctx: ExecutionContext): boolean {
    const required = this.reflector.get<string[]>(REQUIRED_PERMS, ctx.getHandler());
    if (!required) return true;  // sin requerimiento = pasa

    const req = ctx.switchToHttp().getRequest();
    const userPerms = req.user?.permissions || [];

    return required.every((p) => userPerms.includes(p));
  }
}

// Uso
@RequirePermissions('orders:write')
@Post()
create() { /* ... */ }
```

---

## Anti-IDOR / BOLA en services

```typescript
@Injectable()
export class OrdersService {
  async findOne(id: string, user: JwtPayload): Promise<Order> {
    const order = await this.repo.findOne({ where: { id } });
    if (!order) throw new NotFoundException();

    // Anti-IDOR — verificar ownership o admin
    if (order.userId !== user.sub && !user.roles?.includes('admin')) {
      throw new ForbiddenException();  // se loguea con userId + resourceId
    }

    return order;
  }
}
```

---

## Exception filter global

```typescript
@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  constructor(private readonly logger: PinoLogger) {}

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request>();

    const status = exception instanceof HttpException
      ? exception.getStatus()
      : 500;

    // Server-side: full detail
    this.logger.error({
      requestId: request.id,
      method: request.method,
      path: request.url,
      statusCode: status,
      error: exception instanceof Error ? {
        name: exception.name,
        message: exception.message,
        stack: exception.stack,
      } : exception,
    }, 'Request failed');

    // Client-side: sanitized
    const message = status < 500
      ? (exception as HttpException).message
      : 'Internal server error';

    response.status(status).json({
      statusCode: status,
      message,
      requestId: request.id,
    });
  }
}

// En main.ts:
app.useGlobalFilters(new GlobalExceptionFilter(logger));
```

---

## Rate limiting

```typescript
// app.module.ts
import { ThrottlerModule, ThrottlerGuard } from '@nestjs/throttler';

@Module({
  imports: [
    ThrottlerModule.forRoot([
      { name: 'short', ttl: 1000, limit: 10 },     // 10 req/seg
      { name: 'medium', ttl: 60000, limit: 100 },  // 100 req/min
    ]),
  ],
  providers: [
    { provide: APP_GUARD, useClass: ThrottlerGuard },
  ],
})
export class AppModule {}

// Override por endpoint
@Throttle({ default: { limit: 5, ttl: 60000 } })
@Post('login')
login() { /* ... */ }
```

---

## TypeORM seguro

### NUNCA queries crudas con interpolación

```typescript
// ❌ MAL
await dataSource.query(`SELECT * FROM users WHERE email = '${email}'`);

// ✅ BIEN — parameterized
await dataSource.query('SELECT * FROM users WHERE email = $1', [email]);

// ✅ MEJOR — usar el repository
await this.usersRepo.findOne({ where: { email } });
```

### SSL obligatorio para Cloud SQL

```typescript
TypeOrmModule.forRoot({
  type: 'postgres',
  host: process.env.DB_HOST,
  ssl: {
    rejectUnauthorized: true,  // NUNCA false
    ca: fs.readFileSync('/etc/ssl/certs/server-ca.pem'),
  },
  // ...
})
```

### Read replicas

```typescript
TypeOrmModule.forRoot({
  type: 'postgres',
  replication: {
    master: { host: 'primary-db', /* ... */ },
    slaves: [{ host: 'replica-db', /* ... */ }],
  },
})
```

---

## TypeScript estricto

```json
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "forceConsistentCasingInFileNames": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true
  }
}
```

`strict: true` solo no alcanza — agregá los demás flags. Cierra agujeros donde TypeScript es laxo por default.

---

## Dependencias

### package-lock.json siempre

```bash
# Local
npm install

# CI (NO npm install)
npm ci
```

### Verificá paquetes que la IA sugiere

Las IAs a veces inventan paquetes (LLM09:2025). Antes de instalar:

```bash
# ¿Existe?
npm view <package-name>

# ¿Está mantenido?
npm view <package-name> versions  # ver últimas versiones
```

### Auditoría

```bash
# Local
npm audit

# CI: bloquear con high+
npm audit --audit-level=high
```

Dependabot ya está corriendo a nivel org en GHAS. Reviewá los PRs que abre — no los mergees ciegos.

---

## NPM scripts seguros

```json
{
  "scripts": {
    "start": "node dist/main.js",
    "start:dev": "nest start --watch",
    "build": "nest build",
    "test": "jest",
    "test:cov": "jest --coverage",
    "lint": "eslint src --max-warnings 0"
  }
}
```

**Reglas:**
- No scripts que ejecuten cosas raras de paquetes (`postinstall`, `preinstall`, etc. de deps son vector de supply chain attack)
- Usar `--max-warnings 0` en lint para fallar build con warnings

---

## Swagger (solo en dev/staging)

```typescript
if (process.env.NODE_ENV !== 'production') {
  const config = new DocumentBuilder()
    .setTitle('My API')
    .setVersion('1.0')
    .addBearerAuth()
    .build();
  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('api/docs', app, document);
}
```

**NUNCA expongas Swagger en producción.** Es un mapa para atacantes.

Si lo necesitás en prod (raro), protegelo con auth.

---

## Checklist al crear / revisar un servicio NestJS

```
[ ] tsconfig con strict: true + flags adicionales
[ ] main.ts: helmet, CORS explícito, ValidationPipe global con whitelist+forbidNonWhitelisted
[ ] AuthGuard global registrado
[ ] @Public() decorator usado solo donde corresponde (health, public webhooks)
[ ] PermissionsGuard / RolesGuard donde aplica
[ ] Cada controller verifica ownership de recursos (anti-IDOR)
[ ] Todos los DTOs tienen class-validator decorators
[ ] Paginación con Min(1)+Max(100)
[ ] IDs en URLs son UUIDs validados con ParseUUIDPipe
[ ] Exception filter global instalado
[ ] Rate limiting configurado en endpoints sensibles
[ ] TypeORM: SSL verify-full, queries parameterizadas
[ ] Logger structured (Pino) con redacción de campos sensibles
[ ] Swagger solo en non-prod
[ ] package-lock.json commiteado
[ ] CI usa `npm ci`, no `npm install`
[ ] Dockerfile multi-stage con distroless (ver references/docker.md)
```
