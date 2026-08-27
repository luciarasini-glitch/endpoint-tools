# Architecture

> Cómo está pensado el sistema de Secure Vibecoding en Cashea, y cómo encajan las piezas.

## Vista general

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   USUARIO (dev, head, C-level, no-técnico)                          │
│                                                                     │
│   ↓ pide código a una IA                                            │
│                                                                     │
│   ┌──────────────────────────────────────────────────┐              │
│   │  Claude.ai (web) o Claude Code (CLI)             │              │
│   │  + skill secure-coding cargado automáticamente   │              │
│   └────────────────────┬─────────────────────────────┘              │
│                        │                                            │
│                        ↓ código que aplica las reglas               │
│                                                                     │
│   ┌──────────────────────────────────────────────────┐              │
│   │  Repo nuevo (creado desde un template via         │              │
│   │  ai-forge) con .claude/rules/ + GHAS + CODEOWNERS │              │
│   └────────────────────┬─────────────────────────────┘              │
│                        │                                            │
│                        ↓ PR + CI                                    │
│                                                                     │
│   ┌──────────────────────────────────────────────────┐              │
│   │  GHAS: CodeQL + Dependabot + Secret Scanning      │              │
│   │  + AppSec review en archivos críticos (CODEOWNERS)│              │
│   └────────────────────┬─────────────────────────────┘              │
│                        │                                            │
│                        ↓ merge                                      │
│                                                                     │
│   ┌──────────────────────────────────────────────────┐              │
│   │  Cloud Build → Artifact Registry → Cloud Run      │              │
│   │  + SCC Premium + Cloud Armor + JumpCloud SSO      │              │
│   └──────────────────────────────────────────────────┘              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Las 4 capas

### Capa 1: Skills de IA

**Qué:** Reglas que se cargan automáticamente cuando alguien pide código a Claude.

**Dónde vive:**
- Claude.ai (web): skill subido a nivel org en `Settings → Skills → Organization`
- Claude Code (CLI): `.claude/rules/` en cada repo + opcionalmente `~/.claude/rules/`
- Source of truth: `rules/` en `ai-forge`

**Cómo se mantiene:** AppSec edita `rules/` → CI valida → merge → workflow `publish-rules.yml` propaga a los 3 templates y a otros repos opt-in.

### Capa 2: Repo templates

**Qué:** Estructura, configs, defaults seguros pre-armados.

**Cuáles:**
- `bo-template` — Backoffices (Next.js + JumpCloud SSO)
- `ms-template` — Microservicios (NestJS + Cloud SQL)
- `web-platform` — Monorepo de paquetes frontend

**Cómo se usa:** alguien abre Issue en `ai-forge` → la Action crea repo nuevo desde el template + inyecta rules + asigna permisos.

### Capa 3: Pipeline CI

**Qué:** GHAS Enterprise corre en cada PR de todos los repos.

**Componentes:**
- **CodeQL** — análisis estático de seguridad (SQL injection, XSS, etc.)
- **Dependabot** — alertas de vulnerabilidades en dependencias
- **Secret Scanning** — bloquea commits con tokens / API keys

**Bloqueo:** si alguno encuentra algo serio, el merge se bloquea hasta que se arregle.

### Capa 4: Pipeline CD + Infra

**Qué:** Build, push, deploy seguro por default.

**Componentes:**
- **Cloud Build** — CD
- **Artifact Registry** — registro de imágenes Docker
- **SCC Premium** — scan de containers + análisis de configuración GCP
- **Cloud Run** — runtime con ingress interno por default
- **Cloud Armor** — WAF si la app es internet-facing
- **JumpCloud OIDC** — auth de empleados
- **VPC Service Controls** — perímetro para datos sensibles
- **CMEK** — claves de cifrado propias para datos Restringidos

## Componentes del repo ai-forge

### `rules/` — Source of truth de los rules

12 reglas universales (en SKILL.md) + 9 referencias por dominio. Es el contenido que carga Claude para generar código.

### `.claude/rules/` — Copia para uso local de Claude Code

Tiene que estar **sincronizado** con `rules/`. El CI valida que estén iguales. Claude Code lo lee al iniciar sesión en el repo.

### `.github/ISSUE_TEMPLATE/` — Formularios de creación

3 templates para que la gente pida proyectos nuevos. YAML moderno con dropdowns, validaciones y checkboxes.

### `.github/workflows/` — Automation

- `scaffold.yml` — Crea repos cuando un Issue se aprueba
- `validate-rules.yml` — Lint + valida los rules en cada PR
- `publish-rules.yml` — Sincroniza rules a los 3 templates via PR

### `.github/CODEOWNERS` — Enforcement de aprobaciones

Define qué archivos requieren approval de AppSec / DevOps. GitHub enforcea esto.

### `scaffolding/` — Lógica del scaffolding

- `inject-rules.sh` — Script que copia los rules a un repo nuevo
- `rules-readme.md` — README que va dentro de `.claude/rules/` en el repo destino
- `README.md` — Spec técnica para DevOps de cómo configurar la GitHub App

### `docs/` — Documentación operativa

- `for-non-technical.md` — Para usuarios no-técnicos
- `for-developers.md` — Para devs
- `claude-code-setup.md` — Cómo configurar Claude Code
- `architecture.md` — Este documento
- `governance.md` — Quién aprueba qué, cómo escalar

## Decisiones de diseño

### ¿Por qué un repo orquestador en vez de templates standalone?

**Pro de templates standalone:** la gente clona directamente.
**Contra:** no hay control central de approvals, no hay tracking de qué se creó, los rules se copian una vez y no se actualizan.

**Pro del orquestador:** approval centralizado, scaffolding consistente, updates de rules automáticos.
**Contra:** un punto extra entre el usuario y el repo final.

**Decisión:** orquestador. La fricción mínima del approval vale por la consistencia.

### ¿Por qué inyectar rules en cada repo en vez de symlinkear?

**Pro de symlink/submodule:** una sola copia, siempre actualizada.
**Contra:** complica el setup del dev, no funciona bien con Claude Code si no entiende el symlink, los cambios pueden romper repos viejos sin aviso.

**Pro de inyectar:** cada repo es self-contained, los cambios llegan via PR (auditable, rechazable).
**Contra:** versiones distintas en distintos repos si alguno no acepta el PR.

**Decisión:** inyectar via PR. La auditabilidad y la posibilidad de rechazo valen más que la simplicidad teórica.

### ¿Por qué GitHub App en vez de PAT?

- **PAT:** atado a una persona. Si se va, se rompe todo. Permisos amplios.
- **App:** scope acotado, tokens short-lived (1h), auditable por App, sobrevive cambios de personal.

**Decisión:** GitHub App.

### ¿Por qué Issue templates YAML en vez de markdown clásico?

- **Markdown:** caja de texto pre-llenada, el usuario puede borrar todo y poner cualquier cosa.
- **YAML:** formulario con campos validados, dropdowns, checkboxes obligatorios.

**Decisión:** YAML. La calidad de los datos que recibimos es 10x mejor.

### ¿Por qué inyectar rules como copia y no como ref de git remoto?

Claude Code lee archivos físicos en `.claude/rules/`. No tiene mecanismo para resolver refs remotas. Tenemos que copiar.

## Lo que NO está acá (y por qué)

### Tooling de DLP / proxy para LLMs

Hay productos comerciales (Lakera, Prompt Security, Protect AI) que filtran data antes de mandarla a un LLM. **Hoy no los usamos.** Razón: caros, complejos, requieren cambios en el flujo del usuario. Hoy nos defendemos con:

- Skill `secure-coding` regla #12 — Claude detecta y avisa
- Política de Uso de IA — instrucciones a los usuarios
- Educación + cultura de seguridad

Si en el futuro vemos que esto no alcanza, evaluamos sumar tooling.

### Managed settings de Claude Code

Anthropic está trabajando en "managed settings" para deploy de config a nivel org. Cuando esté disponible, evaluamos. Hoy lo manejamos con inyección al repo.

### MDM para distribuir rules

Posibilidad técnica pero descartada — Cashea no usa MDM en máquinas de devs, no vale la pena montar uno solo para esto.

## Métricas y observabilidad

Lo que queremos medir (cuando el flujo esté corriendo):

- **Time-to-repo:** desde Issue hasta repo creado
- **Approval rate:** % de Issues aprobados / rechazados / cambiados
- **Rule violation rate:** findings de GHAS en repos creados desde `ai-forge` vs repos legacy
- **Adoption:** # de repos activos creados desde `ai-forge` / mes
- **Rule update lag:** tiempo entre merge a `ai-forge/rules` y deploy en cada template

## Roadmap

Ver Notion → AI Security → Roadmap.

Highlights:
- ✅ Subir skill a Claude.ai org
- 🟡 Crear el repo `ai-forge` (este)
- ⏳ Configurar GitHub App + secrets (DevOps)
- ⏳ Testing del flujo end-to-end con un Issue dummy
- ⏳ Hardening de los 3 templates con findings de auditoría
- ⏳ Training a equipos de ingeniería
- ⏳ Decisión final sobre Claude Code (Opción A vs B vs ambas)
