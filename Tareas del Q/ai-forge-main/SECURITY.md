# Security Policy

## Reportar una vulnerabilidad

Si descubrís una vulnerabilidad en `ai-forge`, en alguno de los templates (`bo-template`, `ms-template`, `web-platform`) o en cualquier repo creado desde acá:

**NO abras un Issue público.** Las vulnerabilidades reportadas públicamente pueden ser explotadas antes de que tengamos chance de arreglarlas.

### Canales seguros

| Canal | Cuándo usarlo |
|---|---|
| 📧 **Email: security@cashea.app** | Default para todo |
| 💬 **Slack: #appsec** | Si ya tenés acceso al workspace |
| 🔒 **GitHub Security Advisory** | Para vulnerabilidades en el código del repo |

### Qué incluir en el reporte

1. **Descripción** clara del problema
2. **Pasos para reproducir** (si aplica)
3. **Impacto** estimado (severity, scope, datos en riesgo)
4. **PoC** si lo tenés (opcional)
5. **Quién más sabe** (idealmente nadie todavía)

### Qué esperar

| Etapa | Tiempo objetivo |
|---|---|
| Confirmación de recepción | < 24h hábiles |
| Evaluación inicial + severity | < 3 días hábiles |
| Plan de remediación | < 7 días hábiles |
| Fix deployed | depende de severity (críticos < 48h) |
| Disclosure pública | después del fix, coordinado con quien reportó |

### Disclosure responsable

Pedimos que esperes a que se aplique el fix antes de hacer disclosure pública. A cambio:

- Te creditamos en la disclosure (a menos que prefieras anonimato)
- Te avisamos cuando el fix está deployed
- No tomamos acciones legales contra reportes de buena fe

## Scope

### Incluido

- Vulnerabilidades en `ai-forge` (workflows, scripts, configs)
- Vulnerabilidades en los rules de seguridad (`rules/` o `.claude/rules/`)
- Vulnerabilidades en los templates (`bo-template`, `ms-template`, `web-platform`)
- Vulnerabilidades en repos creados desde `ai-forge`

### Fuera de scope

- Bugs no relacionados con seguridad → usar Issues normales
- Vulnerabilidades en dependencias de terceros (reportar al vendor, abrir Dependabot alert)
- Issues que ya están reportados en Dependabot/CodeQL

## Threat model

`ai-forge` es un repo **interno** de Cashea con visibilidad limitada al equipo. Aún así, asumimos los siguientes threat actors:

- **Insider con permisos básicos:** puede leer este repo pero no debería poder modificar rules ni workflows críticos
- **Insider con permisos write:** puede mergear cambios, pero CODEOWNERS lo fuerza a tener approval de AppSec en archivos sensibles
- **Compromised GitHub App token:** el workflow usa la App con permisos mínimos y tokens short-lived (1h)
- **Supply chain attack via dependencies:** Dependabot + Secret Scanning + lockfiles pinned

Mitigaciones aplicadas:

- ✅ Branch protection en `main` (no push directo)
- ✅ CODEOWNERS enforced
- ✅ Required reviews para PRs
- ✅ GHAS habilitado (CodeQL + Dependabot + Secret Scanning)
- ✅ Workflows con permisos mínimos (`permissions:` explícito)
- ✅ GitHub App en vez de PATs
- ✅ Audit logs habilitados

## Frameworks de referencia

- OWASP Top 10 2025
- OWASP API Security Top 10 2023
- OWASP LLM Top 10 2025
- CIS GCP Foundations Benchmark
- Docker CIS Benchmark
- ASVS 5.0

Contacto: **security@cashea.app**
