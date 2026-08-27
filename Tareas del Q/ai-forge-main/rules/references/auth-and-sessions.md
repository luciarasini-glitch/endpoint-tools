# Auth & Sessions

Reglas de seguridad para autenticación, autorización, manejo de sesiones, RBAC, e IDOR.

**Cheatsheets oficiales que aplican (consultá si necesitás profundidad):**
- [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [JSON Web Token](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
- [OAuth 2.0 Protocol](https://cheatsheetseries.owasp.org/cheatsheets/OAuth_2.0_Protocol_Cheatsheet.html)
- [Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [Access Control](https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html)
- [Insecure Direct Object Reference Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)

**OWASP IDs:** A01:2025, A07:2025, API1:2023, API2:2023, API5:2023

---

## 1. Identificá qué tipo de auth necesitás

Hay 3 escenarios distintos. Elegí MAL y todo el resto está mal.

| Escenario | Quién es el "cliente" | Auth recomendada |
|---|---|---|
| App / dashboard / backoffice para empleados | Persona humana (colaborador interno) | **OIDC con SSO corporativo** (en Cashea: JumpCloud) |
| API ↔ API / microservicio ↔ microservicio | Otra app sin humano | **OAuth2 Client Credentials** o **mTLS** o **service tokens firmados** |
| App o API pública para clientes finales | Persona humana fuera de la empresa | OIDC con un IdP público o auth propia con MFA — caso por caso |

**No mezcles los 3 escenarios.** No autentiques una API service-to-service con un user JWT. No autentiques un dashboard interno con un client_credentials grant.

---

## 2. Auth para humanos: OIDC (Authorization Code + PKCE)

### Por qué OIDC y no otra cosa

OIDC (OpenID Connect) sobre OAuth2 es el estándar para login con humanos. Resuelve identidad (quién sos) y autorización (qué podés hacer) con un solo flujo, soporta SSO, MFA, y no requiere que tu app maneje passwords.

### Flujo correcto: Authorization Code + PKCE

```
1. App redirige a IdP con: client_id, redirect_uri, scope, code_challenge (PKCE)
2. Usuario se autentica en el IdP (+MFA si aplica)
3. IdP redirige a la app con: authorization code
4. Backend de la app intercambia code por: id_token + access_token + refresh_token
5. Backend valida id_token (signature, iss, aud, exp, nonce)
6. Backend crea session (cookie HttpOnly)
```

### Reglas

- **PKCE siempre.** Aunque tengas `client_secret`. Protege contra interceptación del code.
- **El intercambio code → token va por el backend, NO por el frontend.** El frontend nunca toca el `client_secret` ni el `refresh_token`.
- **Validá el `id_token`:**
  - `iss` (issuer) coincide con tu IdP esperado
  - `aud` (audience) coincide con tu `client_id`
  - `exp` no expiró
  - `nbf` ya pasó (si está presente)
  - `nonce` coincide con el que mandaste (anti-replay)
  - Algoritmo: **RS256** (NO `none`, NO HS256 con clave pública)
- **Validá la firma con JWKS.** Bajá las claves públicas del endpoint `/.well-known/jwks.json` del IdP, cacheá con TTL razonable (1h), rotación automática.
- **Token lifetime corto.** Access token ≤ 1 hora. Si necesitás más, usá refresh token con rotación.

### En Cashea

Para apps internas, el IdP es **JumpCloud**. Endpoints: ver la página de Notion "Integración JumpCloud SSO" para los URLs exactos, token lifetimes y proceso de creación de app OIDC con el equipo de IAM.

**No hardcodees endpoints de JumpCloud.** Vienen del `/.well-known/openid-configuration` o de Secret Manager.

---

## 3. Sessions: cookies HttpOnly, NO tokens en localStorage

**Esta es la regla que más se viola hoy en Cashea.** Tenemos servicios web que mantienen el JWT en `localStorage` o `sessionStorage` y lo mandan como `Authorization: Bearer`. Eso es patrón de API, no de web.

### Web (browser): cookies HttpOnly

- Token de sesión va en **cookie**, no en `localStorage` ni `sessionStorage`
- Cookie configurada con:
  - `HttpOnly` — JavaScript no puede leerla (mitiga XSS robando token)
  - `Secure` — solo se envía sobre HTTPS
  - `SameSite=Lax` (o `Strict` si es backoffice) — mitiga CSRF
  - `Path=/` y `Domain` explícito
  - Expiración acorde al lifetime del session
- El backend valida la session en cada request — no confía en lo que diga el frontend

### API pura (sin browser): Bearer token

- Para clientes que NO son browsers (otros servicios, jobs, scripts), el `Authorization: Bearer <token>` está bien
- El token sigue siendo un JWT firmado y validado igual

### Por qué importa esta diferencia

Si guardás un JWT en `localStorage`, **cualquier XSS en tu app le da el token al atacante**. Una cookie `HttpOnly` no es leíble desde JavaScript, así que un XSS no puede robarla (puede usarla para hacer requests, pero no exfiltrarla).

### CSRF

Si usás cookies, necesitás protección CSRF:
- `SameSite=Lax` o `Strict` cubre la mayoría de los casos
- Para acciones críticas (transferencias, cambios de password): **CSRF token** además
- Header custom (`X-Requested-With`) como defensa adicional, no como única

---

## 4. JWT: validar bien o no validar

### NUNCA aceptes un JWT sin validar TODO esto

```
✓ Signature válida (con la clave pública del JWKS del IdP esperado)
✓ Algoritmo: RS256, ES256, o EdDSA — NUNCA "none", NUNCA HS256 con public key
✓ iss == tu IdP esperado
✓ aud == tu client_id / API identifier
✓ exp > now()
✓ nbf <= now() (si está presente)
✓ Token NO está en blacklist (si manejás revocación)
```

### Errores comunes (no los hagas)

```typescript
// ❌ MAL — solo decodifica, no valida nada
const payload = jwt.decode(token);

// ❌ MAL — valida firma pero no claims
jwt.verify(token, publicKey);

// ❌ MAL — acepta cualquier algoritmo (incluido "none")
jwt.verify(token, publicKey, { algorithms: ['none', 'HS256', 'RS256'] });

// ✅ BIEN — valida todo
const payload = jwt.verify(token, publicKey, {
  algorithms: ['RS256'],
  issuer: process.env.OIDC_ISSUER,
  audience: process.env.OIDC_AUDIENCE,
});
```

### NUNCA confíes en el JWT solo porque está firmado

Un JWT firmado válido del IdP correcto **solo te dice quién es la persona**. NO te dice que esa persona puede hacer la acción que está pidiendo. Eso es autorización (sección siguiente).

---

## 5. Authorization (RBAC) y prevención de IDOR

### El error más común: confundir auth con authz

- **Auth (autenticación):** ¿quién sos? → JWT válido te lo dice
- **Authz (autorización):** ¿podés hacer ESTO sobre ESTE recurso? → tu app tiene que verificarlo

Que el JWT sea válido NO significa que el usuario tenga permiso para todo. Cada endpoint, cada acción, cada recurso requiere su propia verificación.

### IDOR / BOLA — el error más común en APIs

**Insecure Direct Object Reference** = un usuario accede a recursos de otro usuario porque el código no verifica el ownership.

```typescript
// ❌ MAL — confía en que el ID del path es del usuario autenticado
@Get('orders/:id')
async getOrder(@Param('id') id: string) {
  return this.orderService.findById(id);  // Cualquiera puede pedir cualquier order
}

// ✅ BIEN — verifica que el order pertenece al usuario (o que es admin)
@Get('orders/:id')
async getOrder(@Param('id', ParseUUIDPipe) id: string, @CurrentUser() user: User) {
  const order = await this.orderService.findById(id);
  if (!order) throw new NotFoundException();
  if (order.userId !== user.sub && !user.roles.includes('admin')) {
    throw new ForbiddenException();
  }
  return order;
}
```

### Reglas para prevenir IDOR

1. **Usá UUIDs, no IDs secuenciales.** Si tu URL es `/orders/12345`, un atacante prueba `/orders/12346`. Con UUIDs no puede enumerar.
2. **Verificá ownership en cada endpoint.** No asumas. No confíes en el frontend.
3. **No expongas IDs internos** en respuestas si no son necesarios. A veces el cliente solo necesita un slug o un identifier scoped a su tenant.
4. **Logueá los 403** — son la señal de que alguien está intentando IDOR (ver `references/logging-and-monitoring.md`).

### RBAC: roles y permisos

#### Patrón

```
Usuario → tiene roles (en JWT claims o en DB)
Rol     → tiene permisos (acciones sobre recursos)
Acción  → requiere uno o más permisos
```

#### Ejemplo

```typescript
// Permisos granulares
const permissions = {
  'orders:read': ['admin', 'support', 'viewer'],
  'orders:write': ['admin', 'support'],
  'orders:delete': ['admin'],
  'users:write': ['admin'],
};

@UseGuards(AuthGuard, PermissionsGuard)
@RequirePermission('orders:delete')
@Delete('orders/:id')
async deleteOrder(...) { /* ... */ }
```

#### Reglas

- **No uses solo "está autenticado"** como check de autorización. Cada acción tiene su permiso.
- **No metas la lógica de roles en el frontend.** El frontend puede esconder botones, pero el backend tiene que rechazar la request igual. UI ≠ security.
- **Roles vienen del IdP (JumpCloud groups) o de tu DB**, mapeados a permisos en código o config.
- **Mínimo privilegio.** El rol por default es el de menos permisos.

---

## 6. Auth entre servicios (API ↔ API)

Cuando un microservicio llama a otro, NO uses el JWT del usuario final (a menos que estés haciendo flow-through autorizado). Usá una de estas:

### Opción A: OAuth2 Client Credentials

El servicio A pide un access token al IdP usando `client_id` + `client_secret` del servicio. Lo manda al servicio B como `Authorization: Bearer`.

```
Service A → IdP: POST /token { grant_type: 'client_credentials', client_id, client_secret, scope }
IdP      → Service A: { access_token: "..." }
Service A → Service B: GET /resource { Authorization: Bearer ... }
Service B: valida el token (signature, iss, aud, exp, scope)
```

**Cuándo usar:** APIs internas donde ya tenés un IdP corriendo (ej: JumpCloud con OAuth2 apps).

### Opción B: mTLS (mutual TLS)

Cada servicio tiene un certificado. Se autentican mutuamente en el TLS handshake.

**Cuándo usar:** comunicación dentro de una mesh (Istio, Linkerd) o entre servicios con identidades managed (GCP Workload Identity).

### Opción C: Service tokens firmados

El servicio A firma un token con una clave compartida (vía Secret Manager). El servicio B verifica.

**Cuándo usar:** casos simples donde no querés depender del IdP. **Menos preferido** porque hay que rotar claves manualmente.

### Reglas

- **NUNCA pongas el `client_secret` del servicio en el código.** Va en Secret Manager.
- **Cada servicio tiene su propio `client_id`.** No compartir entre servicios.
- **Scopes mínimos.** Si Servicio A solo necesita leer, su token tiene scope `read`, no `*`.
- **Rotación.** `client_secret` se rota cada 90 días. mTLS certs se renuevan automáticamente.
- **Logueá las llamadas service-to-service** con `requestId` propagado, para trace end-to-end.

### En Cashea

Para apps internas, el approach recomendado por default es **OAuth2 Client Credentials con JumpCloud**. Si el caso justifica mTLS (volumen alto, latencia crítica), validar con AppSec.

---

## 7. Logout y revocación de session

- **Logout local:** borrá la cookie de session, limpiá memory state del cliente.
- **Logout global (SSO):** redirigí al `end_session_endpoint` del IdP. Esto cierra la sesión en JumpCloud.
- **Revocación de token:** si manejás refresh tokens, mantené una lista de revocados. Access tokens son short-lived así que normalmente no se revocan (expiran rápido).
- **Logout en todos los devices:** si soportás esto, invalidar TODOS los refresh tokens del usuario en la DB.

---

## 8. Checklist rápido para implementar auth en una nueva app

```
[ ] Decidí el escenario: humanos / service-to-service / público
[ ] Si humanos: OIDC con JumpCloud (Authorization Code + PKCE)
[ ] Si service-to-service: OAuth2 Client Credentials con JumpCloud
[ ] Token validation completa: signature + iss + aud + exp + algorithm whitelist
[ ] JWKS dinámico desde el IdP, cacheado
[ ] Sessions web: cookie HttpOnly + Secure + SameSite, NO localStorage
[ ] CSRF protection si usás cookies
[ ] Authz: cada endpoint verifica permisos sobre el recurso
[ ] IDs en URLs son UUIDs, no secuenciales
[ ] Anti-IDOR: verificación de ownership en cada acción
[ ] Logout local + global (end_session_endpoint del IdP)
[ ] Logging de auth events (login, logout, 401, 403, token expired)
[ ] Rate limiting en endpoints de auth (login, refresh)
```
