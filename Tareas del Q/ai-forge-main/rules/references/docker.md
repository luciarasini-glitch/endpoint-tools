# Docker / Containers

Reglas para Dockerfiles seguros, imágenes mínimas, y runtime hardening.

**Cheatsheets oficiales que aplican:**
- [Docker Security](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [Kubernetes Security](https://cheatsheetseries.owasp.org/cheatsheets/Kubernetes_Security_Cheat_Sheet.html)

**Otros referentes:**
- Docker CIS Benchmark
- Distroless: https://github.com/GoogleContainerTools/distroless

**OWASP IDs:** A02:2025, A03:2025, ASI09

---

## Por qué importa el tamaño

Imagen más chica significa:

| Beneficio | Impacto |
|---|---|
| Deploys más rápidos | Pull y start del container en segundos en lugar de minutos |
| Menos superficie de ataque | Menos paquetes = menos CVEs |
| Menor costo | Menos storage en Artifact Registry, menos egress |
| Menos breakage en updates | Menos paquetes que actualizar = menos chance de romper algo |

**Target práctico:**

| Stack | Imagen típica mal hecha | Imagen bien hecha |
|---|---|---|
| Node.js | `node:20` (1GB+) | `gcr.io/distroless/nodejs20-debian12` (~150MB) |
| Python | `python:3.12` (900MB+) | `gcr.io/distroless/python3-debian12` (~50MB) |

---

## Las 4 reglas que más impactan

### 1. Multi-stage build

Separar el stage de build (con compiladores, herramientas, código fuente) del stage de runtime (solo el binario y sus libs runtime):

```dockerfile
# Stage 1: deps
FROM node:20-alpine@sha256:<digest> AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

# Stage 2: build
FROM node:20-alpine@sha256:<digest> AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# Stage 3: runtime (sin npm, sin código fuente, sin nada que no sea necesario)
FROM gcr.io/distroless/nodejs20-debian12@sha256:<digest>
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
EXPOSE 8080
USER nonroot
CMD ["dist/main.js"]
```

### 2. Distroless para runtime

[Distroless](https://github.com/GoogleContainerTools/distroless) son imágenes que tienen **solo el runtime** (Node, Python, JVM) **sin shell, sin apt, sin curl, sin nada**. No podés `docker exec -it bash` porque no hay bash.

| Imagen | Tiene shell | Tiene package manager | Para qué |
|---|---|---|---|
| `gcr.io/distroless/nodejs20-debian12` | No | No | Producción Node |
| `gcr.io/distroless/python3-debian12` | No | No | Producción Python |
| `gcr.io/distroless/static-debian12` | No | No | Producción Go binarios |
| `gcr.io/distroless/base-debian12` | No | No | Producción binarios con libc |
| `gcr.io/distroless/*-debug` | Sí (busybox) | No | **Solo debugging temporal** |

Variantes: `nonroot`, `:latest`, `:debug`, `:debug-nonroot`. Preferí `:nonroot` por default.

### 3. Non-root user

```dockerfile
# Distroless tiene "nonroot" user ya creado (uid 65532)
USER nonroot

# Si NO usás distroless:
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
```

**Por qué:** si el container corre como root y un atacante lo compromete, ya tiene root dentro del container. Si corre como `nonroot`, tiene mucho menos margen.

### 4. Pinned base images con SHA256

```dockerfile
# ❌ MAL
FROM node:20-alpine

# ❌ Mejor pero todavía mal
FROM node:20.11.0-alpine

# ✅ BIEN
FROM node:20-alpine@sha256:1d27e63...
```

**Por qué:** los tags son mutables. Si Docker Hub re-publica `node:20-alpine` con malware, tu build lo usa en el próximo build. Con SHA256, si el digest no coincide, falla.

---

## Reglas adicionales

### .dockerignore obligatorio

Sin `.dockerignore`, el build context incluye `.git`, `node_modules`, `.env`, secrets:

```
# .dockerignore
.env
.env.*
.git
.gitignore
.github
node_modules
__pycache__
*.pyc
.claude/
.vscode/
.idea/
*.md
README.md
Dockerfile*
docker-compose*
tests/
test/
__tests__/
coverage/
.nyc_output
.npm
.cache
*.log
```

### HEALTHCHECK

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["node", "healthcheck.js"]
```

Cloud Run tiene su propio health check, pero el HEALTHCHECK del Dockerfile sirve para:
- Docker Compose local
- Kubernetes
- Detección de container unhealthy

### EXPOSE el puerto correcto

```dockerfile
EXPOSE 8080
```

Solo informativo, no abre puertos. Pero ayuda a otros developers a saber qué puerto usar.

### NUNCA secrets en el Dockerfile

```dockerfile
# ❌ MAL — los secrets quedan en la layer history
ARG API_KEY
ENV API_KEY=$API_KEY

# ❌ MAL — el .env queda en la imagen
COPY .env .

# ❌ MAL — la layer queda con el secret aunque lo borres
RUN curl -H "Authorization: Bearer $TOKEN" ... && rm /tmp/token

# ✅ BIEN — secrets solo en runtime, vía Cloud Run
# (no en el Dockerfile)
```

Para secrets necesarios en build (raros): usar BuildKit secrets:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install
```

```bash
docker build --secret id=npmrc,src=$HOME/.npmrc .
```

### COPY con --chown

```dockerfile
# Si copiás archivos antes de USER nonroot, los archivos son de root
COPY --chown=nonroot:nonroot package.json ./
```

---

## Runtime hardening (Cloud Run / Docker run)

Cloud Run aplica algunos defaults seguros, pero podemos endurecer más:

### Cloud Run

```bash
gcloud run deploy my-service \
  --image=us-east1-docker.pkg.dev/proj/repo/svc:abc123 \
  --no-allow-unauthenticated \
  --ingress=internal-and-cloud-load-balancing \
  --service-account=svc-sa@proj.iam.gserviceaccount.com \
  --set-secrets=DB_PASS=db-pass:latest \
  --cpu=1 \
  --memory=512Mi \
  --max-instances=10 \
  --timeout=60 \
  --concurrency=80
```

**Settings críticos:**

| Flag | Valor | Por qué |
|---|---|---|
| `--no-allow-unauthenticated` | Sí | Cloud Run exige IAM auth (defense in depth) |
| `--ingress` | `internal-and-cloud-load-balancing` | NUNCA `all` para apps internas |
| `--service-account` | SA dedicada | NUNCA default compute SA |
| `--set-secrets` | Desde Secret Manager | NUNCA env vars planas para secrets |
| `--max-instances` | 10-50 según servicio | Prevenir Denial of Wallet |
| `--cpu` / `--memory` | Lo mínimo que funcione | Limitar recursos = limitar daño |

### Docker run (local / docker-compose)

Si corrés containers fuera de Cloud Run:

```bash
docker run \
  --user nonroot:nonroot \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --memory=512m \
  --cpus=1.0 \
  --pids-limit=100 \
  --network=app-net \
  myapp:v1
```

| Flag | Para qué |
|---|---|
| `--read-only` | Filesystem inmutable. Atacantes no pueden droppear webshells. |
| `--tmpfs /tmp` | Permite escritura en /tmp pero noexec (no se ejecutan binarios) |
| `--cap-drop=ALL` | Quita todas las Linux capabilities. Agregar solo las necesarias. |
| `--security-opt=no-new-privileges:true` | El proceso no puede escalar privilegios |
| `--pids-limit` | Previene fork bombs |

---

## Lo que NUNCA se hace

```
❌ Correr como root en runtime
❌ Usar :latest como base image
❌ FROM node sin pinear
❌ ENV con secrets
❌ ARG con secrets
❌ COPY .env
❌ Instalar paquetes en el runtime stage
❌ Usar --privileged
❌ Mount /var/run/docker.sock dentro del container
❌ Mount / read-write del filesystem del host
❌ HOST network namespace (--network=host)
❌ HOST PID namespace (--pid=host)
❌ Imágenes desconocidas / no oficiales (verificar source)
❌ apt update sin --no-install-recommends
❌ Olvidar --no-cache-dir en pip
```

---

## Vulnerability scanning

### En Cashea

- **GCP SCC Premium** (ya configurado a nivel org) escanea automáticamente las imágenes en Artifact Registry
- Los findings aparecen en el Security Command Center

### Reglas

- Ningún deploy con CRITICAL o HIGH no resueltos sin aprobación de AppSec
- Re-escaneo programado (las imágenes que estaban OK ayer pueden no estarlo hoy si sale un CVE)
- Parche o rebuilds frecuentes — imagen de hace 3 meses está obsoleta

---

## Templates de Dockerfile por stack

### Node.js / NestJS

```dockerfile
# syntax=docker/dockerfile:1.6
FROM node:20-alpine@sha256:<digest> AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

FROM node:20-alpine@sha256:<digest> AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM gcr.io/distroless/nodejs20-debian12:nonroot
WORKDIR /app
COPY --from=deps --chown=nonroot:nonroot /app/node_modules ./node_modules
COPY --from=build --chown=nonroot:nonroot /app/dist ./dist
COPY --chown=nonroot:nonroot package.json ./
EXPOSE 8080
ENV NODE_ENV=production
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD ["node", "dist/healthcheck.js"]
USER nonroot
CMD ["dist/main.js"]
```

### Python / FastAPI

```dockerfile
# syntax=docker/dockerfile:1.6
FROM python:3.12-slim@sha256:<digest> AS build
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY . .

FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app
COPY --from=build --chown=nonroot:nonroot /root/.local /home/nonroot/.local
COPY --from=build --chown=nonroot:nonroot /app /app
ENV PATH=/home/nonroot/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
USER nonroot
CMD ["main.py"]
```

### Next.js (con standalone output)

```dockerfile
# syntax=docker/dockerfile:1.6
FROM node:20-alpine@sha256:<digest> AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine@sha256:<digest> AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM gcr.io/distroless/nodejs20-debian12:nonroot
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=8080
COPY --from=build --chown=nonroot:nonroot /app/.next/standalone ./
COPY --from=build --chown=nonroot:nonroot /app/.next/static ./.next/static
COPY --from=build --chown=nonroot:nonroot /app/public ./public
EXPOSE 8080
USER nonroot
CMD ["server.js"]
```

---

## Checklist al crear / revisar un Dockerfile

```
[ ] Multi-stage build (deps / build / runtime separados)
[ ] Runtime usa imagen distroless (o equivalente minimal)
[ ] Base images pinneadas con SHA256
[ ] USER nonroot en el runtime stage
[ ] EXPOSE solo el puerto necesario
[ ] HEALTHCHECK definido
[ ] No ENV / ARG con secrets
[ ] No COPY .env
[ ] .dockerignore excluye .env, .git, node_modules, .claude, tests, docs
[ ] COPY usa --chown=nonroot:nonroot
[ ] No `apt update` sin --no-install-recommends
[ ] No `pip install` sin --no-cache-dir
[ ] No `npm install` en runtime stage (debe ser solo runtime)
[ ] Imagen final < 500MB (target práctico)
[ ] SCC scan pasa sin CRITICAL / HIGH
```
