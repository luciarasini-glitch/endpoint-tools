# Guía para developers

> Para devs que ya conocen Git, Docker, GCP y quieren saber cómo usar `ai-forge` de la manera más eficiente.

## TL;DR

```bash
# 1. Abrí un Issue desde un template
gh issue create --repo cashea-bnpl/ai-forge --template new-service.yml

# 2. Esperá approval

# 3. Cloná tu repo nuevo
gh repo clone cashea-bnpl/your-new-service
cd your-new-service

# 4. Trabajá normal — los rules de seguridad ya están en .claude/rules/
```

---

## Arquitectura

```
┌────────────────────┐
│   ai-forge (this)  │  ← Source of truth de rules + scaffolding
└─────────┬──────────┘
          │
          ├──→ scaffold.yml (Action)
          │    └──→ Crea repos nuevos desde templates
          │
          ├──→ publish-rules.yml (Action)
          │    └──→ Sincroniza rules a los 3 templates via PR
          │
          └──→ rules/ (SOT)
               └──→ Se copia a .claude/rules/ de cada repo creado

   ┌────────────────────┬─────────────────────┬──────────────────┐
   ▼                    ▼                     ▼                  ▼
bo-template         ms-template          web-platform       repos de servicios
(template)          (template)           (monorepo)         (creados desde ai-forge)
```

## Cómo se usa

### Crear un proyecto

Ya lo cubre el README principal. TL;DR: Issue → approval → repo automático.

### Modificar los rules

Si encontrás una regla que mejorar o un gap:

```bash
# 1. Fork + clone
gh repo fork cashea-bnpl/ai-forge --clone
cd ai-forge

# 2. Branch
git checkout -b feat/add-rate-limiting-rule

# 3. Editar
vim rules/references/input-validation.md
# (importante: editar SOLO en rules/, no en .claude/rules/ — el CI los sincroniza)

# 4. Sincronizar rules/ → .claude/rules/
cp rules/SKILL.md .claude/rules/SKILL.md
cp -r rules/references/* .claude/rules/

# 5. Verificar localmente
# (el workflow validate-rules.yml hace estos chequeos)
python3 -c "
import yaml, re
with open('rules/SKILL.md') as f: c = f.read()
m = re.match(r'^---\n(.+?)\n---', c, re.DOTALL)
fm = yaml.safe_load(m.group(1))
desc = ' '.join(fm['description'].split())
print(f'description: {len(desc)} chars (max 1024)')
"

# 6. Commit + PR
git add . && git commit -m "feat(rules): add rate limiting guidance to input-validation"
git push origin feat/add-rate-limiting-rule
gh pr create
```

CODEOWNERS te va a forzar a tener approval de AppSec antes de mergear.

### Testear el scaffolding workflow

El workflow `scaffold.yml` no se puede testear directamente desde un PR (porque requiere secrets de la GitHub App + permisos de admin para crear repos). Para testear:

1. Forkeá `ai-forge` a tu cuenta personal
2. Crea una GitHub App de prueba en tu cuenta (con permisos mínimos para crear repos)
3. Agregá los secrets en tu fork (`FORGE_APP_ID`, `FORGE_APP_PRIVATE_KEY`)
4. Crea labels en tu fork (ver `scaffolding/README.md`)
5. Abrí un Issue de prueba en tu fork
6. Aplicá el label `approved`
7. Verificá el log del workflow + el repo de prueba creado

## Stack tecnológico de los templates

### bo-template (Backoffice)

- **Framework:** Next.js 14 (App Router)
- **Auth:** [next-auth](https://next-auth.js.org/) con JumpCloud OIDC
- **UI:** Tailwind + componentes de `@cashea-bnpl/ui`
- **API client:** auto-generado desde el OpenAPI del microservicio
- **Deploy:** Cloud Run con ingress interno + Cloud Armor + JumpCloud SSO

### ms-template (Microservicio)

- **Framework:** NestJS 10
- **DB:** TypeORM + Cloud SQL (Postgres)
- **Auth API↔API:** OAuth2 Client Credentials
- **Validation:** class-validator + class-transformer con `whitelist: true`
- **Logging:** Pino estructurado, sink a Cloud Logging
- **Deploy:** Cloud Run + Cloud SQL Proxy

### web-platform (Monorepo)

- **Manager:** Turborepo
- **Package manager:** pnpm
- **Linting:** ESLint + Prettier (config compartida)
- **Testing:** Vitest + Testing Library + Storybook
- **Build:** tsup para packages, Next.js para apps

## Convenciones

### Naming

- **Repos de servicios:** `<dominio>-<funcion>` (ej. `billing-invoices`, `risk-scoring`)
- **Repos de backoffices:** `<dominio>-<funcion>-bo` (ej. `risk-review-bo`)
- **Packages frontend:** `@cashea-bnpl/<categoria>-<nombre>` (ej. `@cashea-bnpl/ui-tables`)

### Branches

- `main`: producción, protegida
- `develop`: integración (en repos que lo usen)
- `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`: feature branches

### Commits

[Conventional Commits](https://www.conventionalcommits.org/). Ejemplos:

```
feat(auth): add JumpCloud OIDC flow to bo-template
fix(rules): correct CSP header example in frontend.md
chore(deps): bump @nestjs/core to v10.3.0
docs(readme): clarify approval process for new services
```

### CODEOWNERS pattern

Todo repo creado desde `ai-forge` tiene CODEOWNERS configurado así:

```
* @cashea-bnpl/<team-dueño>
/.claude/rules/ @cashea-bnpl/appsec
/.github/workflows/ @cashea-bnpl/appsec @cashea-bnpl/devops
/Dockerfile @cashea-bnpl/appsec
/infra/ @cashea-bnpl/appsec @cashea-bnpl/cloudsec
/iam/ @cashea-bnpl/appsec @cashea-bnpl/cloudsec
```

## CI/CD

### En cada PR (todos los repos):

- ✅ CodeQL scan (CodeQL semantic analysis)
- ✅ Dependabot check (vulnerabilidades en deps)
- ✅ Secret scanning (no commits con tokens/keys)
- ✅ Lint + format check
- ✅ Tests unitarios + integración
- ✅ Build (Docker image)

### En merge a main:

- ✅ Re-run de todo lo anterior
- ✅ Build + push a Artifact Registry (con SCC scan)
- ✅ Deploy a staging
- ✅ Smoke tests
- ⏸️ Manual approval para producción (en repos con datos restringidos)
- ✅ Deploy a producción

## Cómo trabajar con Claude

### Claude.ai (web)

El skill `secure-coding` está activo a nivel org. No necesitás hacer nada — pedile cosas y va a aplicar las reglas.

### Claude Code (CLI)

Los rules vienen en `.claude/rules/` del repo. Se cargan automáticamente al iniciar sesión.

**Para verificar que se están cargando:**

```bash
cd /your/repo
claude
# Al iniciar, deberías ver algo como: "Loaded 10 files from .claude/rules/"
```

Si no se cargan, revisar que `.claude/rules/SKILL.md` exista y tenga frontmatter YAML válido.

### Pedirle código a Claude

**OK:**
- "creá un endpoint de NestJS que liste pedidos con paginación"
- "agregale rate limiting a este endpoint, usá @nestjs/throttler"
- "este código tiene un IDOR? ¿cómo lo arreglo?"

**Mejor:**
- Linkear el archivo concreto: "este endpoint `src/orders/orders.controller.ts` necesita rate limiting"
- Mencionar el contexto: "es un microservicio que va a recibir webhooks de un payment provider — agregale verificación de signature"

**Lo que NO se hace:**
- ❌ Pegar tokens reales o credenciales aunque sea "para mostrar el formato"
- ❌ Pegar logs de producción sin redactar
- ❌ Pegar exports de DB con clientes reales

## Troubleshooting

### "El workflow scaffold falló"

Mirá el log de la Action. Causas comunes:
- Nombre de repo inválido → el usuario edita el Issue, AppSec re-aplica `approved`
- Repo ya existe → elegir otro nombre
- GitHub App sin permisos → DevOps lo arregla

### "Claude Code no carga los rules"

```bash
# Verificar que existen
ls -la .claude/rules/

# Verificar el SKILL.md
head -20 .claude/rules/SKILL.md

# Verificar que no haya problemas de encoding o BOM
file .claude/rules/SKILL.md
```

### "Quiero que mi repo no tenga AppSec como CODEOWNER"

No. Es enforced por política. Si necesitás una excepción, abrí un Issue justificándolo.

## Contacto

- 💬 Slack: #appsec (o #engineering si es general)
- 📧 Email: security@cashea.app
- 📖 Notion: AI Security workspace
