# Governance

> Quién decide qué, quién aprueba qué, cómo se escala.

## Stakeholders

| Equipo | Rol en ai-forge |
|---|---|
| **AppSec** | Owner del repo. Aprueba cambios en rules, workflows críticos, CODEOWNERS, issue templates |
| **CloudSec** | Co-aprobador de Issues que tocan infra GCP o datos Restringidos |
| **DevOps** | Configura la GitHub App, secrets, mantiene los workflows |
| **Frontend Platform** | Mantiene `bo-template` y `web-platform` |
| **Backend** | Mantiene `ms-template` |
| **Equipo dueño del servicio** | Mantiene los repos creados desde ai-forge (asignado vía Issue) |

## Quién aprueba qué

### Crear un repo nuevo (Issue de creación)

| Tipo de proyecto | Aprobador principal | Aprobador adicional |
|---|---|---|
| Backoffice / Microservicio / Paquete frontend (datos Públicos o Internos) | AppSec | — |
| Cualquiera con datos Confidenciales | AppSec | — |
| Cualquiera con datos Restringidos (PII-D, FIN-IND, SEC-PRD) | AppSec | CloudSec |

**SLA objetivo:** 1-2 días hábiles.

### Cambios en rules (`rules/`, `.claude/rules/`)

Aprobador: **AppSec** (enforced por CODEOWNERS).

**SLA objetivo:** 3 días hábiles para changes routinarios. Same-day para fixes críticos.

### Cambios en workflows (`.github/workflows/`)

Aprobador: **AppSec + DevOps**.

### Cambios en issue templates

Aprobador: **AppSec**.

### Cambios en docs

Default: AppSec aprueba. Si es solo docs (no rules), un thumbs-up de cualquier AppSec member es suficiente.

## Escalation

### "Mi Issue está sin respuesta hace +2 días"

1. Mensaje en `#appsec` en Slack con link al Issue
2. Si sigue sin respuesta, ping a `@appsec-leads` en Slack
3. Si urgente, mandar mail directo a `security@cashea.app`

### "AppSec rechazó mi Issue y no estoy de acuerdo"

1. Pedí en el Issue una explicación más detallada de la razón
2. Si seguís sin estar de acuerdo, pediríamos un meeting de 15 min con AppSec lead + tu manager
3. La decisión final la tiene el Head de Security, pero buscamos consenso primero

### "El scaffolding falló y bloquea mi proyecto"

1. AppSec automaticamente recibe notificación del failure (comentario en el Issue)
2. Si en 24h no hay update, ping en `#appsec`

### "Encontré una vulnerabilidad en los rules o en un template"

Ver [SECURITY.md](../SECURITY.md). **No abras Issue público.** Mail a `security@cashea.app` o Slack DM.

## Lifecycle de los repos creados

### Activos

- Mantenidos por el equipo dueño
- AppSec recibe alertas si hay findings de GHAS sin resolver +14 días
- Quarterly review de IAM, secretos rotados, deps actualizadas

### Sunset

Si un repo queda sin uso por +6 meses:
1. AppSec contacta al team dueño para confirmar
2. Si confirman que no se usa: archive (read-only en GitHub) + deshabilitar Cloud Run + revocar IAM
3. Después de 6 meses adicionales archived: delete (con backup en cold storage por 1 año más por compliance)

## Métricas de governance

Reportadas mensualmente en `#appsec`:

- Issues abiertos / aprobados / rechazados
- Time-to-repo medio
- # de repos activos creados desde ai-forge
- # de findings de seguridad en repos ai-forge vs repos legacy
- Adopción del skill `secure-coding`
- PRs de rules abiertos / mergeados

## Cambios a este documento

PR + approval de AppSec lead. Si el cambio impacta a otros equipos (ej. requerir CloudSec en más casos), también aprobación de los heads correspondientes.

---

Última revisión: mayo 2026
Próxima revisión: agosto 2026 (quarterly)
