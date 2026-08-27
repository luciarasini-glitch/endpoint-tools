# Frontend (React / Next.js)

Particularidades de seguridad para apps frontend.

**Cheatsheets oficiales que aplican:**
- [Cross Site Scripting (XSS) Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [DOM-based XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html)
- [HTML5 Security](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html)
- [Content Security Policy](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
- [Cross-Site Request Forgery (CSRF) Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Clickjacking Defense](https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html)

**OWASP IDs:** A02:2025, A05:2025, A07:2025, LLM05:2025

---

## XSS — el riesgo #1 del frontend

React escapa por default cualquier valor que metés en JSX:

```tsx
// ✅ Seguro — React escapa automáticamente
<div>{userInput}</div>
```

Pero hay 3 formas de meter HTML crudo y romper la protección:

```tsx
// ❌ Peligroso — bypass del escape
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// ❌ Peligroso — href con javascript:
<a href={userControlledUrl}>click</a>  // userControlledUrl = "javascript:alert(1)"

// ❌ Peligroso — estilos dinámicos sin sanitizar
<div style={`background: url(${userImage})`} />
```

### Reglas

1. **NUNCA `dangerouslySetInnerHTML` con input del usuario.**
2. **Si necesitás HTML rico** (ej: contenido de un CMS), sanitizá con DOMPurify:
   ```tsx
   import DOMPurify from 'isomorphic-dompurify';

   <div dangerouslySetInnerHTML={{
     __html: DOMPurify.sanitize(htmlContent, {
       ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'a', 'p', 'br'],
       ALLOWED_ATTR: ['href'],
     })
   }} />
   ```
3. **URLs en `href`/`src`** — validá el protocolo:
   ```tsx
   function safeUrl(url: string): string {
     try {
       const u = new URL(url, window.location.origin);
       if (!['http:', 'https:', 'mailto:'].includes(u.protocol)) {
         return '#';
       }
       return u.toString();
     } catch {
       return '#';
     }
   }
   ```

---

## Manejo de tokens en el browser

**Esta es la regla más violada en apps de Cashea.** Hoy hay servicios que mantienen el JWT en `localStorage` o `sessionStorage`. No es seguro.

### NUNCA tokens en localStorage / sessionStorage

```typescript
// ❌ MAL — accesible desde JavaScript, robable con XSS
localStorage.setItem('token', accessToken);
sessionStorage.setItem('token', accessToken);
```

**Por qué:** un XSS en cualquier dependencia de tu frontend puede leer todo el storage y exfiltrar tokens. Ya pasó (Magecart, polyfill.io, etc.).

### Patrón correcto: HttpOnly cookies

El backend setea la session como cookie `HttpOnly`:

```typescript
// Backend (NestJS / similar) al hacer login
res.cookie('session', sessionToken, {
  httpOnly: true,
  secure: true,       // solo HTTPS
  sameSite: 'lax',    // o 'strict' para backoffices
  maxAge: 60 * 60 * 1000,  // 1 hora
  path: '/',
});

// Frontend — el browser manda la cookie automáticamente
fetch('/api/orders', { credentials: 'include' });
```

### Si tenés que mantener un access token en memoria (caso M2M poco común)

```typescript
// Variable en módulo (no global, no storage)
let accessToken: string | null = null;

export function setAccessToken(t: string) { accessToken = t; }
export function getAccessToken(): string | null { return accessToken; }
```

Se pierde al refresh — eso es **bueno**, fuerza re-auth.

### Refresh tokens

NUNCA en localStorage. Siempre HttpOnly cookie. La rotación la maneja el backend.

---

## Content Security Policy (CSP)

CSP es la mejor defensa contra XSS. Bloquea scripts no autorizados.

### En Next.js (next.config.js)

```javascript
const cspHeader = `
  default-src 'self';
  script-src 'self' 'nonce-{nonce}' 'strict-dynamic';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
  font-src 'self';
  connect-src 'self' https://api.cashea.app;
  object-src 'none';
  base-uri 'self';
  form-action 'self';
  frame-ancestors 'none';
  upgrade-insecure-requests;
`.replace(/\s{2,}/g, ' ').trim();

module.exports = {
  async headers() {
    return [{
      source: '/(.*)',
      headers: [
        { key: 'Content-Security-Policy', value: cspHeader },
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
      ],
    }];
  },
};
```

### Reglas

- `default-src 'self'` como base
- `script-src` con nonces (Next.js los genera) o `strict-dynamic`
- **NUNCA** `'unsafe-eval'` en producción
- `'unsafe-inline'` en `style-src` es aceptable (Tailwind/CSS-in-JS lo necesitan), pero NUNCA en `script-src`
- `frame-ancestors 'none'` para prevenir clickjacking
- `object-src 'none'` para bloquear plugins
- `connect-src` explícito con los dominios de tu API

---

## CORS y credentials

Cuando usás cookies HttpOnly, el frontend tiene que mandar `credentials: 'include'`:

```typescript
fetch('/api/orders', {
  credentials: 'include',  // manda cookies
  headers: { 'Content-Type': 'application/json' },
});

// Con axios
axios.create({
  withCredentials: true,
  baseURL: process.env.NEXT_PUBLIC_API_URL,
});
```

Y el backend tiene que tener CORS configurado con `credentials: true` y `origin` explícito (no `*`).

---

## CSRF

Si usás cookies, necesitás protección CSRF.

### Defensas

1. **`SameSite=Lax` o `Strict`** en la cookie de session — cubre la mayoría de casos
2. **CSRF token** para acciones críticas:
   ```typescript
   // Frontend obtiene un token al cargar
   const csrfToken = await fetch('/api/csrf-token', { credentials: 'include' });

   // Lo manda en cada request mutativo
   fetch('/api/orders', {
     method: 'POST',
     credentials: 'include',
     headers: { 'X-CSRF-Token': csrfToken },
   });
   ```
3. **Header custom** (`X-Requested-With: XMLHttpRequest`) — defensa adicional, no única

---

## Variables de entorno en Next.js

```typescript
// ❌ Estas VARIABLES SE EXPONEN AL BROWSER (visibles en el bundle)
process.env.NEXT_PUBLIC_API_URL  // OK, no es secret
process.env.NEXT_PUBLIC_API_KEY  // ❌ NUNCA poner secrets acá

// ✅ Solo server-side (NO accesibles en el browser)
process.env.DATABASE_URL
process.env.JWT_SECRET
process.env.OIDC_CLIENT_SECRET
```

**Regla:** todo lo que sea `NEXT_PUBLIC_*` queda en el bundle JavaScript que el browser descarga. **Cualquiera puede verlo.** No metas secrets ahí.

Para configuración de OIDC en runtime (no build-time), usar el patrón de `/api/auth/config` que devuelve la config desde el backend:

```typescript
// app/api/auth/config/route.ts
export async function GET() {
  return Response.json({
    oidc_issuer: process.env.OIDC_ISSUER,        // server-side env, OK
    oidc_client_id: process.env.OIDC_CLIENT_ID,  // public por design (es client_id de OIDC)
    redirect_uri: process.env.OIDC_REDIRECT_URI,
  });
}

// El frontend lo lee en runtime
const config = await fetch('/api/auth/config').then(r => r.json());
```

---

## Fetch wrapper con auth y error handling

```typescript
// lib/api.ts

const API_URL = process.env.NEXT_PUBLIC_API_URL!;

interface ApiOptions extends RequestInit {
  timeout?: number;
}

export async function apiCall<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { timeout = 30_000, ...fetchOpts } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...fetchOpts,
      credentials: 'include',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...fetchOpts.headers,
      },
    });

    if (res.status === 401) {
      // Sesión expirada, redirect a login
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      // 4xx: el server manda message
      // 5xx: mostrar mensaje genérico
      const body = await res.json().catch(() => ({}));
      const message = res.status >= 500
        ? 'Algo salió mal. Intentá de nuevo.'
        : body.message || 'Error en la operación';
      throw new ApiError(message, res.status, body.requestId);
    }

    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId?: string,
  ) {
    super(message);
  }
}
```

---

## Sanitización de URLs en componentes

```tsx
// ❌ MAL
<a href={item.externalUrl}>Open</a>

// ✅ BIEN
import { isAllowedExternalUrl } from '@/lib/url';

<a href={isAllowedExternalUrl(item.externalUrl) ? item.externalUrl : '#'}
   target="_blank"
   rel="noopener noreferrer">
  Open
</a>
```

Atributos a NUNCA olvidar en links externos:
- `rel="noopener"` — evita que la página abierta acceda a `window.opener`
- `rel="noreferrer"` — no manda Referer header

---

## Logging en frontend

### NUNCA loguees datos sensibles

```typescript
// ❌ MAL — el token va a console (visible en DevTools, en logs de error tracking, etc.)
console.log('Logged in with token:', accessToken);

// ❌ MAL
console.log('User:', user);  // user puede tener fields sensibles
```

### En producción, console.log debería estar deshabilitado

```javascript
// next.config.js
module.exports = {
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production'
      ? { exclude: ['error'] }
      : false,
  },
};
```

### Error tracking (Sentry, etc.)

Si usás un error tracker:
- Configurá `beforeSend` para redactar PII
- No mandes el body de las requests
- Filtrá emails / tokens / etc.

---

## Dependencies

### NPM audit + Dependabot

Igual que el backend — Dependabot ya está corriendo a nivel org. Reviewá los PRs antes de mergear.

### NUNCA instalar paquetes que la IA sugiere sin verificar

Esto es especialmente cierto en frontend porque el ecosistema npm es enorme y hay typosquatting:

```bash
# Verificá
npm view <package-name>

# Mirá downloads
# https://npmjs.com/package/<name>
```

Sospechá de:
- Paquetes con muy pocos downloads
- Typos sutiles (`react-domm`, `loadash`)
- Versiones recién publicadas

---

## Server Components / Server Actions (Next.js 14+)

### Server Components

```tsx
// ❌ NUNCA exponer secrets en server components
async function Page() {
  const data = await fetch('https://api.com', {
    headers: { 'Authorization': process.env.API_KEY }  // OK acá, server-side
  });
  return <div>{data.something}</div>;
}
```

```tsx
// ✅ El cliente recibe solo `data.something`, no el API key
```

### Server Actions

```tsx
'use server';

import { z } from 'zod';

const Schema = z.object({
  email: z.string().email().max(200),
  name: z.string().max(100),
});

export async function createUser(formData: FormData) {
  // SIEMPRE validar — los inputs vienen del cliente
  const parsed = Schema.safeParse({
    email: formData.get('email'),
    name: formData.get('name'),
  });

  if (!parsed.success) {
    throw new Error('Invalid input');
  }

  // Auth check
  const session = await getSession();
  if (!session) throw new Error('Unauthorized');

  // ...
}
```

**Las Server Actions son endpoints.** Aplican las mismas reglas: validación, auth, authz, error handling.

---

## React Native — particularidades

(Si en algún momento se construye una mobile app. Por ahora no aplica a las apps internas.)

- NUNCA AsyncStorage para tokens — usar Keychain (iOS) / Keystore (Android)
- Certificate pinning para conexiones críticas
- Detectar jailbreak/root para apps con datos sensibles
- Ofuscación de código y release builds firmados
- NO permitir Allow Backup en debug
- Ver OWASP MASVS / MASTG

---

## Checklist al crear / revisar una app frontend

```
[ ] React (sin dangerouslySetInnerHTML excepto con DOMPurify)
[ ] URLs validadas con safe protocol check
[ ] Tokens NUNCA en localStorage/sessionStorage — solo en HttpOnly cookies (set por backend)
[ ] CSP configurada con nonces, sin 'unsafe-eval', sin 'unsafe-inline' en script-src
[ ] Security headers: X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, HSTS
[ ] CORS con credentials: 'include' y allowed_origins explícitos en el backend
[ ] CSRF protection si usás cookies (SameSite + token donde aplique)
[ ] NEXT_PUBLIC_* solo para datos no sensibles
[ ] Fetch wrapper con timeout + error handling sanitizado
[ ] Links externos con rel="noopener noreferrer"
[ ] console.log eliminado en prod build (excepto error)
[ ] Error tracker (si hay) con beforeSend que redacta PII
[ ] Server Actions validan input con schema y verifican auth
[ ] package-lock.json commiteado, npm ci en CI
[ ] Auth con JumpCloud SSO usando el patrón del template (runtime config)
```
