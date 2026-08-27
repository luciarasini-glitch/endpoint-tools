# Python

Particularidades de seguridad para servicios Python (FastAPI principalmente).

**Cheatsheets oficiales que aplican:**
- [REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [Microservices Security](https://cheatsheetseries.owasp.org/cheatsheets/Microservices_Security_Cheat_Sheet.html)
- [SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [OS Command Injection Defense](https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html)

**OWASP IDs:** A05:2025, A03:2025, A09:2025, API3:2023

---

## Stack recomendado para servicios nuevos

| Componente | Recomendado |
|---|---|
| Framework | FastAPI |
| Validación | Pydantic v2 |
| ORM | SQLAlchemy 2.x con async |
| Driver Postgres | asyncpg |
| Auth | python-jose o authlib (JWT con JWKS) |
| Logging | structlog |
| Rate limiting | slowapi |
| Security headers | secure-headers o middleware custom |
| Testing | pytest, pytest-asyncio, httpx |
| Linter | ruff |
| Type checker | mypy strict |
| Package manager | poetry o uv |

---

## Setup inicial — main.py mínimo seguro

```python
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.auth import AuthMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.exceptions import setup_exception_handlers
from app.routers import orders, health

ENV = os.getenv("ENV", "development")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")

app = FastAPI(
    title="My Service",
    docs_url="/docs" if ENV != "production" else None,        # NO docs en prod
    redoc_url="/redoc" if ENV != "production" else None,
    openapi_url="/openapi.json" if ENV != "production" else None,
)

# Middlewares (orden importa)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in ALLOWED_ORIGINS if o],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", "").split(","))

# Routers
app.include_router(health.router)  # sin auth (configurado en AuthMiddleware)
app.include_router(orders.router, prefix="/api/v1")

# Exception handlers globales
setup_exception_handlers(app)
```

---

## Validation con Pydantic v2

### Modelos estrictos

```python
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from uuid import UUID
from typing import Annotated
from enum import Enum

class ShippingType(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    PRIORITY = "priority"

class OrderItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # rechaza campos no definidos

    product_id: UUID
    quantity: Annotated[int, Field(ge=1, le=100)]

class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    description: Annotated[str, Field(max_length=200)]
    shipping_type: ShippingType
    items: Annotated[list[OrderItemRequest], Field(min_length=1, max_length=50)]

class ListOrdersQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0)] = 0
```

### Response models (ocultar campos sensibles)

```python
class UserResponse(BaseModel):
    """Modelo expuesto al cliente. NO incluye password_hash, internal_notes, etc."""
    id: UUID
    email: EmailStr
    name: str
    # NO password_hash
    # NO internal_notes
    # NO created_by

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: UUID) -> UserResponse:
    user = await user_service.get(user_id)
    return user  # FastAPI filtra automáticamente al modelo de response
```

---

## Auth: JWT validation con JWKS

```python
import httpx
from jose import jwt, JWTError
from functools import lru_cache

OIDC_ISSUER = os.getenv("OIDC_ISSUER")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE")
JWKS_URL = f"{OIDC_ISSUER.rstrip('/')}/.well-known/jwks.json"

@lru_cache(maxsize=1)
def get_jwks() -> dict:
    """Cache JWKS para no pegarle al IdP en cada request."""
    return httpx.get(JWKS_URL, timeout=5).json()

# Refrescar cache cada hora con TTL cache custom o cachetools
# (lru_cache simple = no expira; usar cachetools.TTLCache en producción)

def verify_token(token: str) -> dict:
    try:
        # Decodificar header para encontrar el kid
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")

        jwks = get_jwks()
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key:
            raise ValueError("Key not found in JWKS")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],          # SOLO RS256
            issuer=OIDC_ISSUER,
            audience=OIDC_AUDIENCE,
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### Auth middleware

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

PUBLIC_PATHS = {"/health", "/health/live", "/health/ready"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"message": "Unauthorized", "request_id": request.state.request_id},
            )

        try:
            payload = verify_token(auth[7:])
            request.state.user = payload
        except HTTPException as e:
            return JSONResponse(
                status_code=401,
                content={"message": "Unauthorized", "request_id": request.state.request_id},
            )

        return await call_next(request)
```

### Authz: dependencias de FastAPI

```python
from fastapi import Depends

def require_permission(permission: str):
    def checker(request: Request) -> None:
        user = request.state.user
        if permission not in user.get("permissions", []):
            raise HTTPException(status_code=403, detail="Forbidden")
    return checker

# Uso
@app.delete("/orders/{order_id}", dependencies=[Depends(require_permission("orders:delete"))])
async def delete_order(order_id: UUID, request: Request):
    user = request.state.user
    order = await order_service.get(order_id)

    # Anti-IDOR
    if order.user_id != user["sub"] and "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403, detail="Forbidden")

    await order_service.delete(order_id)
```

---

## SQL queries — SIEMPRE parameterizadas

### Con SQLAlchemy

```python
# ❌ MAL
result = await session.execute(text(f"SELECT * FROM users WHERE email = '{email}'"))

# ✅ BIEN — bound params
result = await session.execute(
    text("SELECT * FROM users WHERE email = :email"),
    {"email": email},
)

# ✅ MEJOR — ORM
result = await session.execute(select(User).where(User.email == email))
user = result.scalar_one_or_none()
```

### BigQuery

```python
from google.cloud import bigquery

# ❌ MAL
query = f"SELECT * FROM `proj.ds.users` WHERE id = '{user_id}'"

# ✅ BIEN
query = "SELECT * FROM `proj.ds.users` WHERE id = @user_id LIMIT @max_rows"
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("user_id", "STRING", str(user_id)),
        bigquery.ScalarQueryParameter("max_rows", "INT64", 100),
    ]
)
client.query(query, job_config=job_config).result()
```

---

## subprocess y comandos del sistema

### NUNCA shell=True con input del usuario

```python
import subprocess

# ❌ MAL — RCE inminente
subprocess.run(f"convert {filename} output.png", shell=True)
os.system(f"echo {user_input}")

# ❌ TAMBIÉN MAL — concatenación
subprocess.run(["sh", "-c", f"convert {filename} output.png"])

# ✅ BIEN — lista de args, sin shell
subprocess.run(
    ["convert", filename, "output.png"],
    shell=False,
    check=True,
    timeout=30,
    capture_output=True,
)
```

### Validar el input antes de pasarlo a subprocess

```python
import re
from pathlib import Path

def safe_convert(filename: str):
    # Allowlist: solo nombres de archivo, sin paths
    if not re.match(r"^[a-zA-Z0-9_\-]+\.(jpg|png|webp)$", filename):
        raise ValueError("Invalid filename")

    full_path = Path("/uploads") / filename
    # Verificar que no escape del directorio
    if not full_path.resolve().is_relative_to(Path("/uploads").resolve()):
        raise ValueError("Path traversal detected")

    subprocess.run(["convert", str(full_path), "output.png"], shell=False, check=True)
```

---

## Deserialización segura

```python
# ❌ NUNCA con datos no confiables
import pickle
data = pickle.loads(user_input)  # RCE inmediato

# ❌ NUNCA
import yaml
data = yaml.load(user_input)  # usar safe_load

# ✅ BIEN
import yaml
data = yaml.safe_load(user_input)

# ✅ JSON con schema
from pydantic import BaseModel

class Payload(BaseModel):
    field1: str
    field2: int

data = Payload.model_validate_json(user_input)
```

---

## Secret Manager integration

```python
from google.cloud import secretmanager
from functools import lru_cache

@lru_cache(maxsize=32)
def get_secret(secret_name: str, project: str = None) -> str:
    project = project or os.getenv("GCP_PROJECT")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

# En startup
@app.on_event("startup")
async def load_secrets():
    app.state.db_password = get_secret("db-password")
    app.state.api_key = get_secret("partner-api-key")
```

---

## Error handling sin leak

```python
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import structlog

logger = structlog.get_logger()

def setup_exception_handlers(app: FastAPI):

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # 4xx: mensaje específico
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message": exc.detail,
                "status_code": exc.status_code,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        # 5xx: log full, response sanitized
        logger.exception(
            "unhandled_exception",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error",
                "status_code": 500,
                "request_id": request.state.request_id,
            },
        )
```

---

## Rate limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    # ...
```

---

## Logging con structlog

```python
import structlog
import logging

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,                     # custom
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

SENSITIVE_KEYS = {"password", "token", "authorization", "api_key", "secret", "card"}

def redact_sensitive(_, __, event_dict):
    for k in list(event_dict.keys()):
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            event_dict[k] = "***"
    return event_dict

logger = structlog.get_logger()

# Uso
logger.info(
    "order_created",
    user_id=str(user_id),
    order_id=str(order.id),
    request_id=request.state.request_id,
)
```

---

## TLS / SSL en conexiones

```python
# Postgres / asyncpg
DATABASE_URL = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=require"

# Mejor con ssl context
import ssl
ssl_ctx = ssl.create_default_context(cafile="/etc/ssl/certs/server-ca.pem")
ssl_ctx.verify_mode = ssl.CERT_REQUIRED

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"ssl": ssl_ctx},
)

# httpx — SIEMPRE verify=True
async with httpx.AsyncClient(verify=True, timeout=10) as client:
    response = await client.get(url)
```

NUNCA `verify=False`, NUNCA `ssl=False`.

---

## requirements.txt / poetry — pinned

```
# requirements.txt - pinned a versión exacta
fastapi==0.115.0
pydantic==2.9.2
sqlalchemy==2.0.36
asyncpg==0.30.0
python-jose[cryptography]==3.3.0
structlog==24.4.0
google-cloud-secret-manager==2.21.0
google-cloud-bigquery==3.27.0
```

```toml
# pyproject.toml con poetry
[tool.poetry.dependencies]
python = "^3.12"
fastapi = "0.115.0"  # exacto, no ^
# ...
```

### En CI

```bash
# Producción
pip install --no-deps -r requirements.txt

# Audit
pip-audit
# o
safety check
```

---

## mypy strict

```toml
# pyproject.toml
[tool.mypy]
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_unimported = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
```

---

## Verificá paquetes que la IA sugiere

Las IAs inventan paquetes (LLM09:2025):

```bash
# ¿Existe?
pip show <package> 2>/dev/null || pip search <package>

# Ver en PyPI
# https://pypi.org/project/<package>/
```

Especialmente sospechá si:
- El nombre tiene typos sutiles de paquetes populares (`reqests` vs `requests`)
- No tiene downloads / es nuevo
- No tiene maintainer claro

---

## Checklist al crear / revisar un servicio Python

```
[ ] FastAPI con docs deshabilitado en prod
[ ] CORS explícito, sin wildcard
[ ] CORS allowed_origins desde env, no hardcoded
[ ] Pydantic v2 con extra="forbid" en todos los modelos
[ ] Auth middleware global con JWT validation completa (signature, iss, aud, exp, alg)
[ ] JWKS cacheado con TTL razonable
[ ] Authz por endpoint (require_permission + ownership check)
[ ] IDs son UUID type, no str
[ ] Response models filtran campos sensibles
[ ] SQLAlchemy con queries parameterizadas, NUNCA f-strings
[ ] BigQuery con query parameters
[ ] subprocess: shell=False, lista de args, validación de input
[ ] No pickle.loads / yaml.load con datos del usuario
[ ] Secret Manager para secrets, no env vars planos
[ ] Exception handlers que logean full y responden sanitized
[ ] Rate limiting en endpoints sensibles (login, register)
[ ] structlog con redacción de campos sensibles
[ ] DB con SSL verify obligatorio
[ ] httpx / requests con verify=True, timeouts
[ ] requirements.txt pinneado a versiones exactas
[ ] mypy strict habilitado
[ ] CI usa pip --no-deps
[ ] Dockerfile multi-stage con distroless (ver references/docker.md)
```
