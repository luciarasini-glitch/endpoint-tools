# Scaffolding — Specification

Este documento es la **spec técnica** que necesita el equipo de DevOps para
habilitar el scaffolding automático. El código YAML ya está en
`.github/workflows/scaffold.yml` y `.github/workflows/publish-rules.yml`,
pero requiere configuración previa para funcionar.

---

## ¿Qué es esto?

Cuando alguien abre un Issue acá y AppSec/CloudSec lo aprueba (le agrega el label
`approved`), una GitHub Action crea automáticamente un repo nuevo desde el template
correcto, le inyecta los rules de seguridad de Cashea y le configura permisos.

Reemplaza un proceso manual de 2-3 días por uno automático de 30 segundos.

---

## ¿Qué hay que configurar antes de prenderlo?

### 1. GitHub App: "Cashea AI Forge"

Crear una GitHub App en la org `cashea` con estos permisos:

**Repository permissions:**
- Contents: **Read & Write**
- Administration: **Read & Write** (para crear repos)
- Metadata: **Read-only**
- Pull requests: **Read & Write**
- Issues: **Read & Write**
- Workflows: **Read & Write**

**Organization permissions:**
- Members: **Read & Write** (para asignar team permissions)
- Administration: **Read-only**

**Events a suscribir:** ninguno por ahora (la App solo es para auth, no event-driven).

**Where can this GitHub App be installed?** Only on this account (cashea).

Una vez creada:

1. Generar private key (descarga un `.pem`)
2. Instalar la App en la org `cashea`, dándole acceso a TODOS los repos (o al menos `ai-forge` + los 3 templates + permiso para crear nuevos)
3. Tomar nota del **App ID** (lo muestra la página de settings de la App)

### 2. Secrets en el repo ai-forge

Settings → Secrets and variables → Actions → New repository secret

| Nombre | Valor |
|---|---|
| `FORGE_APP_ID` | El App ID numérico de la GitHub App |
| `FORGE_APP_PRIVATE_KEY` | El contenido completo del `.pem` (incluyendo `-----BEGIN/END-----`) |

### 3. Teams en la org

Estos teams tienen que existir en `cashea-bnpl` para que la Action pueda asignar permisos:

- `cashea-bnpl/appsec` — admin de todos los repos nuevos
- `cashea-bnpl/devops` — co-owner de workflows
- `cashea-bnpl/platform`, `cashea-bnpl/engineering`, `cashea-bnpl/finance`, `cashea-bnpl/security`, `cashea-bnpl/data`, `cashea-bnpl/product` — equipos que pueden ser dueños de servicios

Si algún team no existe, crearlo o ajustar las opciones en `new-service.yml`,
`new-backoffice.yml`, `new-frontend-package.yml` (dropdown de "Equipo
responsable").

### 4. Templates con repository=template habilitado

En GitHub, los repos `bo-template`, `ms-template` y `web-platform` deben tener
marcado **Settings → Template repository** para poder usarlos en
`gh repo create --template`.

### 5. Labels en el repo ai-forge

Crear estas labels (Settings → Labels):

| Label | Color | Para qué |
|---|---|---|
| `new-service` | `#0E8A16` | Issue de nuevo microservicio |
| `new-backoffice` | `#1D76DB` | Issue de nuevo backoffice |
| `new-frontend-package` | `#5319E7` | Issue de nuevo paquete frontend |
| `pending-approval` | `#FBCA04` | Esperando aprobación de AppSec |
| `approved` | `#28A745` | Aprobado — triggerea el scaffolding |
| `rejected` | `#D73A4A` | Rechazado por AppSec |
| `automated` | `#7057FF` | PR generado automáticamente |
| `security` | `#B60205` | Cambio relacionado con seguridad |

---

## Flujo end-to-end (qué pasa cuando todo está configurado)

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Usuario abre Issue desde un template                            │
│     ↓                                                                │
│  2. Issue queda con label `pending-approval`                        │
│     ↓                                                                │
│  3. AppSec + CloudSec reciben notificación, revisan                 │
│     ↓                                                                │
│  4. Si OK: agregan label `approved` (manual o vía /approve comment) │
│     ↓                                                                │
│  5. Workflow scaffold.yml triggerea en label `approved`             │
│     ↓                                                                │
│  6. Crea repo desde template correcto                               │
│     ↓                                                                │
│  7. Inyecta .claude/rules/ via inject-rules.sh                      │
│     ↓                                                                │
│  8. Asigna permisos al team dueño + AppSec admin                    │
│     ↓                                                                │
│  9. Comenta en Issue con link al repo, cierra Issue                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Flujo de update de rules

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. AppSec modifica rules/SKILL.md o algún reference                │
│     ↓                                                                │
│  2. Abre PR, CI valida (validate-rules.yml)                         │
│     ↓                                                                │
│  3. AppSec aprueba (CODEOWNERS lo exige)                            │
│     ↓                                                                │
│  4. Merge a main                                                    │
│     ↓                                                                │
│  5. Workflow publish-rules.yml triggerea                            │
│     ↓                                                                │
│  6. Para cada template (bo, ms, web-platform):                      │
│     - Clona                                                          │
│     - Copia rules/ → .claude/rules/                                 │
│     - Abre PR en el template                                        │
│     ↓                                                                │
│  7. Team dueño del template revisa y mergea                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Failure modes y cómo se manejan

| Falla | Qué pasa | Cómo se resuelve |
|---|---|---|
| Nombre de repo inválido | Workflow falla, comenta en Issue | Usuario edita Issue, AppSec re-aplica label |
| Repo ya existe | Workflow falla, comenta en Issue | Usuario elige otro nombre |
| Template no encontrado | Workflow falla, comenta en Issue | DevOps verifica que el template existe y es accesible |
| Team no existe | Workflow falla al asignar permisos | DevOps crea el team o ajusta el Issue |
| Permisos insuficientes | Workflow falla con error 403 | Verificar permisos de la GitHub App |
| inject-rules.sh falla | Workflow falla, comenta en Issue | AppSec investiga (probablemente rules/ corruptos) |

## Testing

Antes de prender el workflow en main, testear en un fork:

1. Forkear `ai-forge` a tu cuenta personal o a `cashea-sandbox`
2. Configurar los secrets en el fork (con una GitHub App de prueba)
3. Abrir un Issue de prueba, aplicar `approved`
4. Verificar que se crea el repo de prueba con todos los archivos correctos
5. Verificar que el Issue se cierra con el comentario adecuado

## Próximos pasos / roadmap

- [ ] DevOps configura GitHub App + secrets (semana 1)
- [ ] AppSec testea el flujo end-to-end con un Issue dummy (semana 1)
- [ ] Documentar el flujo de aprobación en docs/governance.md (semana 2)
- [ ] Integrar con Slack: notificar a #appsec cuando hay un Issue pendiente (semana 3)
- [ ] Métricas: tiempo medio Issue → aprobación → repo creado (semana 4)

## Preguntas frecuentes

**¿Por qué GitHub App y no PAT?**
- PAT está atado a una persona; si esa persona se va, todo se rompe
- App scope es más granular y se audita por App, no por usuario
- App tokens son short-lived (1 hora) — más seguro

**¿Por qué no usar `repository_dispatch` o `workflow_dispatch` directos?**
- Queremos que el trigger sea visible (un Issue), no oculto en alguna API call
- El Issue queda como documentación de qué se creó y por qué

**¿Por qué no commit directo de rules a los templates en vez de PR?**
- Auditoría: un PR queda en el historial del template, los commits directos no
- CI: los templates pueden tener tests propios que queremos correr antes de mergear
- Control: el team dueño del template puede rechazar el cambio si rompe algo

---

Contacto: AppSec @ Cashea — Slack #appsec — security@cashea.app
