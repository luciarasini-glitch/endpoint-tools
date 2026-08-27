# Input Validation

Reglas para validar todo input que entra a la aplicación.

**Cheatsheets oficiales que aplican:**
- [Input Validation](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Mass Assignment](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html)
- [Deserialization](https://cheatsheetseries.owasp.org/cheatsheets/Deserialization_Cheat_Sheet.html)
- [File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Query Parameterization](https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html)

**OWASP IDs:** A05:2025, API3:2023

---

## Principio: nunca confíes en nada que venga de afuera

Input no es solo lo que llega de un formulario. **Todo lo siguiente es input no confiable:**

- Request body, query params, path params, headers
- Respuestas de APIs externas (third-parties, internal services)
- Datos leídos de DB que originalmente vinieron de un usuario
- Mensajes de queue (Pub/Sub, SQS, RabbitMQ)
- Variables de entorno (cuando vienen de fuentes no controladas)
- Archivos subidos por usuarios
- URLs de redirect
- Webhooks

Si lo escribió un humano o un sistema externo, validalo.

---

## Las 4 dimensiones a validar

Para cada input:

| Dimensión | Qué validar |
|---|---|
| **Tipo** | string, number, boolean, UUID, fecha, email |
| **Formato** | regex, schema (JSON schema, Zod, Pydantic) |
| **Rango** | longitud min/max, valor min/max, items min/max en arrays |
| **Allowlist** | enum de valores permitidos cuando aplica |

**Allowlist > Denylist.** Listar lo que está permitido es más seguro que tratar de listar todo lo que está prohibido.

---

## Reglas universales

### IDs siempre UUID, nunca string libre

```typescript
// ❌ MAL
@Param('id') id: string  // acepta cualquier cosa

// ✅ BIEN
@Param('id', ParseUUIDPipe) id: string  // valida formato UUID
```

```python
# ❌ MAL
def get_order(order_id: str): ...

# ✅ BIEN
from uuid import UUID
def get_order(order_id: UUID): ...
```

**Por qué:** sequential IDs (`/orders/123`) hacen IDOR trivial — el atacante prueba `/orders/124`. UUIDs son no-enumerables.

### Paginación con límite máximo

```typescript
// ✅ BIEN
class ListQueryDto {
  @IsOptional() @IsInt() @Min(1) @Max(100)
  limit: number = 20;

  @IsOptional() @IsInt() @Min(0)
  offset: number = 0;
}
```

**Por qué:** sin límite, alguien pide `?limit=10000000` y tu DB explota (DoS) o devuelve datos en exceso.

### Strings con longitud máxima

```typescript
// ❌ MAL
@IsString() name: string;

// ✅ BIEN
@IsString() @MaxLength(200) name: string;
```

**Por qué:** strings sin tope son vector de DoS y de queries lentas.

### Enums explícitos para campos de dominio

```typescript
// ❌ MAL — acepta cualquier string
@IsString() status: string;

// ✅ BIEN — solo valores válidos
@IsEnum(['pending', 'approved', 'rejected'])
status: string;
```

### Arrays con límite de items

```typescript
// ✅ BIEN
@IsArray() @ArrayMaxSize(50) @ValidateNested({ each: true })
items: ItemDto[];
```

---

## Mass Assignment — el bug silencioso

**Mass Assignment** ocurre cuando aceptás un objeto entero del cliente y lo asignás directo a tu modelo. El cliente puede setear campos que no debería (ej: `isAdmin: true`).

```typescript
// ❌ MAL — el cliente puede mandar cualquier campo
@Post('users')
createUser(@Body() body: any) {
  return this.userService.create(body);  // body podría tener {isAdmin: true}
}

// ✅ BIEN — DTO con whitelist
class CreateUserDto {
  @IsEmail() email: string;
  @IsString() @MaxLength(100) name: string;
  // No isAdmin, no roles, no createdAt — solo lo que el usuario puede setear
}

@Post('users')
createUser(@Body() body: CreateUserDto) {
  return this.userService.create(body);
}
```

**Configuración crítica del ValidationPipe:**

```typescript
app.useGlobalPipes(new ValidationPipe({
  whitelist: true,              // remueve campos no declarados en el DTO
  forbidNonWhitelisted: true,   // rechaza la request si tiene campos extra
  transform: true,              // convierte tipos automáticamente
  forbidUnknownValues: true,    // rechaza objetos desconocidos
}));
```

En Pydantic:

```python
class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(max_length=100)

    model_config = ConfigDict(extra='forbid')  # rechaza campos extra
```

---

## Output validation: lo que devolvés también importa

Un caso común: el modelo de DB tiene `passwordHash`, `internalNotes`, `createdBy`. Si devolvés `user` directo, leakeás esos campos.

```typescript
// ❌ MAL
@Get(':id')
async getUser(@Param('id') id: string) {
  return this.userService.findById(id);  // devuelve el modelo completo
}

// ✅ BIEN — DTO de respuesta explícito
class UserResponseDto {
  id: string;
  email: string;
  name: string;
  // No passwordHash, no internalNotes
}

@Get(':id')
@Serialize(UserResponseDto)
async getUser(@Param('id', ParseUUIDPipe) id: string): Promise<UserResponseDto> {
  return this.userService.findById(id);
}
```

---

## File uploads

Reglas mínimas para cualquier endpoint que acepta archivos:

```
[ ] Tamaño máximo (ej: 10MB para imágenes, 50MB para docs)
[ ] Allowlist de MIME types — NO denylist
[ ] Allowlist de extensiones
[ ] Validar el contenido real (magic bytes), no solo la extensión
[ ] Renombrar el archivo antes de guardar (UUID, no usar el nombre del usuario)
[ ] Guardar en GCS, NUNCA en el filesystem del container
[ ] Servir archivos via signed URLs con expiración corta
[ ] Escanear con antivirus si va a ser descargado por otros usuarios
```

**No hagas:**
```typescript
// ❌ MAL — el usuario controla el path
const path = `/uploads/${file.originalname}`;
fs.writeFileSync(path, file.buffer);

// Esto permite path traversal con originalname = "../../../etc/passwd"
```

---

## URLs y redirects

**Open Redirect** es cuando la app redirige a una URL controlada por el atacante:

```typescript
// ❌ MAL
@Get('login')
login(@Query('returnUrl') returnUrl: string, @Res() res) {
  res.redirect(returnUrl);  // returnUrl = "https://evil.com/phish"
}

// ✅ BIEN — allowlist de redirects válidos
const ALLOWED_REDIRECTS = ['/dashboard', '/profile', '/orders'];

@Get('login')
login(@Query('returnUrl') returnUrl: string, @Res() res) {
  const safe = ALLOWED_REDIRECTS.includes(returnUrl) ? returnUrl : '/dashboard';
  res.redirect(safe);
}
```

---

## SSRF (Server-Side Request Forgery)

Cuando tu backend hace requests a URLs controladas por el usuario, podés terminar pegándole a la red interna o al metadata server de GCP (`169.254.169.254`).

```typescript
// ❌ MAL
@Get('fetch-url')
async fetch(@Query('url') url: string) {
  return await axios.get(url);
  // url = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
}

// ✅ BIEN — allowlist de dominios + bloqueo de IPs internas
const ALLOWED_HOSTS = ['api.partner.com', 'cdn.example.com'];

async function safeFetch(url: string) {
  const parsed = new URL(url);

  // Solo HTTPS
  if (parsed.protocol !== 'https:') throw new Error('Only HTTPS allowed');

  // Solo hosts en allowlist
  if (!ALLOWED_HOSTS.includes(parsed.hostname)) throw new Error('Host not allowed');

  // Bloquear IPs privadas (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
  // ... resolver DNS y verificar

  return await axios.get(url, { timeout: 5000, maxRedirects: 0 });
}
```

---

## Deserialization

Nunca deserialices datos no confiables con formatos que permiten ejecución de código:

- **Python:** NUNCA `pickle.loads()` con datos del usuario
- **Node:** NUNCA `eval()`, `Function()`, `vm.runInNewContext()` con strings del usuario
- **Java:** evitar `ObjectInputStream.readObject()` sin filtros

Usá JSON parseado con un schema (Zod, Pydantic, JSON Schema). Nunca formatos arbitrarios.

---

## Checklist de validación al crear un endpoint

```
[ ] Hay un DTO con tipos explícitos para el body
[ ] El DTO tiene whitelist + forbidNonWhitelisted (NestJS) o extra='forbid' (Pydantic)
[ ] Cada campo tiene validators de tipo + formato + rango
[ ] IDs son UUIDs validados, no strings libres
[ ] Strings tienen MaxLength
[ ] Paginación tiene Min(1)+Max(100) en limit
[ ] Enums explícitos en campos de dominio
[ ] Si recibe archivos: tamaño + MIME + extensión validados, magic bytes verificados
[ ] Si redirige: allowlist de URLs
[ ] Si hace fetch externo: allowlist de hosts + bloqueo de IPs internas
[ ] Hay un DTO de response que oculta campos sensibles
```
