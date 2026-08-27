# Contributing to ai-forge

¡Gracias por querer contribuir! Este repo es de AppSec pero las mejoras son bienvenidas.

## Tipos de contribuciones

### 1. Mejoras a los rules de seguridad

Los archivos en `rules/` son la **fuente de verdad** de las reglas que aplica Claude a todo el código de Cashea. Si encontrás una regla que mejorar, un caso de uso que falta o un cheatsheet que sumar:

1. Abrí un Issue describiendo el cambio
2. Discutimos el approach con AppSec
3. Abrís el PR

**Importante:** los cambios en `rules/` requieren approval de AppSec (enforced por CODEOWNERS).

### 2. Issue templates

Los formularios que la gente usa para pedir repos nuevos viven en `.github/ISSUE_TEMPLATE/`. Si encontrás campos confusos o falta algún campo, mandá un PR.

### 3. Documentación

Los archivos en `docs/` están abiertos. Si algo no se entiende o falta algo, abrí un PR.

### 4. Scaffolding action

El workflow `scaffold.yml` y los scripts en `scaffolding/` son sensibles — cambios acá requieren approval de AppSec **y** DevOps.

---

## Workflow

1. **Forkeá el repo** (o, si tenés permisos, branch desde main)
2. **Hacé el cambio** en una branch con nombre descriptivo (`feat/`, `fix/`, `docs/`, `chore/`)
3. **Corré los tests localmente**:
   - Si tocaste rules: el workflow `validate-rules.yml` te va a chequear
   - Si tocaste workflows: testealos en tu fork antes de PR
4. **Abrí el PR** usando el template
5. **Esperá review** de los owners correspondientes
6. **Mergeá** cuando tengas approval

## Estándares de código

- **Markdown:** prosa clara y directa. Argentino casual está bien para docs internos.
- **YAML:** 2 espacios de indent. Strings con `"` cuando contienen interpolación.
- **Bash:** `set -euo pipefail` siempre. Variables entre comillas.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, etc.

## Lo que NO se hace en este repo

- ❌ Commitear secrets (la GitHub App + GHAS te van a frenar)
- ❌ Push directo a main (branch protection lo bloquea)
- ❌ Bypass de CODEOWNERS sin justificación documentada
- ❌ Pegar datos reales de clientes en Issues o PRs

## Reportar vulnerabilidades

**No abras un Issue público.** Mandá un mail a security@cashea.app o avisá en Slack #appsec.

Ver [SECURITY.md](./SECURITY.md) para el proceso completo.

## Preguntas

- Slack: #appsec
- Email: security@cashea.app
- Notion: AI Security workspace

Gracias por sumar 💛
