# 🔨 ai-forge

> **El lugar donde se forjan las aplicaciones de Cashea.**
> Framework operativo para desarrollo seguro con IA.

[![Security by default](https://img.shields.io/badge/security-by%20default-FDFA3D?style=flat-square&labelColor=0A0A0A)](./rules/SKILL.md)
[![OWASP](https://img.shields.io/badge/OWASP-Top%2010%202025-005A9C?style=flat-square)](https://owasp.org/Top10/2025/)
[![CIS Benchmarks](https://img.shields.io/badge/CIS-GCP%20%2B%20Docker-1E8449?style=flat-square)](https://www.cisecurity.org/cis-benchmarks)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-rules%20enforced-7C3AED?style=flat-square)](./.claude/rules/)
[![GHAS](https://img.shields.io/badge/GHAS-CodeQL%20%7C%20Dependabot%20%7C%20Secret%20Scanning-2EA44F?style=flat-square)](https://github.com/features/security)
[![Maintained by AppSec](https://img.shields.io/badge/maintained%20by-AppSec-FDFA3D?style=flat-square&labelColor=0A0A0A)](mailto:security@cashea.app)

---

## ¿Qué es esto?

`ai-forge` es el **orquestador de creación de aplicaciones internas** en Cashea. No es un template usable directamente — es el repo que **crea repos** desde los 3 templates oficiales:

| Template | Para qué | Stack |
|---|---|---|
| [`bo-template`](https://github.com/cashea-bnpl/bo-template) | Backoffices con UI | Next.js + JumpCloud SSO + Cloud Run |
| [`ms-template`](https://github.com/cashea-bnpl/ms-template) | Microservicios y APIs | NestJS + TypeORM + Cloud Run |
| [`web-platform`](https://github.com/cashea-bnpl/web-platform) | Paquetes frontend compartidos | Monorepo |

**El flujo:** alguien abre un Issue acá → AppSec aprueba → una GitHub Action crea el repo desde el template correcto, le inyecta los rules de seguridad y configura permisos. 30 segundos en vez de 2-3 días.

## ¿Por qué existe?

Porque cualquier persona en Cashea (dev o no) puede usar Claude/GPT/Gemini para generar código, y necesitamos que ese código sea **seguro por default** sin que la persona tenga que saber qué es OWASP A01.

Confiamos en la gente. No confiamos en que la gente conozca seguridad. Para eso están las 4 capas de defensa:

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Skills de IA           Claude.ai org skill + .claude/rules/     │
│  2. Repo Templates         bo-template · ms-template · web-platform │
│  3. Pipeline CI            GHAS: CodeQL + Dependabot + Secret Scan  │
│  4. Pipeline CD + Infra    Cloud Build + Cloud Run + SCC + Armor    │
└─────────────────────────────────────────────────────────────────────┘
```

## Cómo crear un proyecto nuevo

1. **Abrí un Issue** acá → "New Issue" → elegí el template:
   - 🖥️ [Nuevo Backoffice](../../issues/new?template=new-backoffice.yml)
   - ⚙️ [Nuevo Microservicio](../../issues/new?template=new-service.yml)
   - 🎨 [Nuevo paquete frontend](../../issues/new?template=new-frontend-package.yml)
2. Llená el formulario (nombre, equipo, clasificación de datos, etc.)
3. AppSec + CloudSec revisan y aprueban (label `approved`)
4. La Action automáticamente crea el repo nuevo, copia los rules de seguridad, configura permisos y te avisa
5. Listo, podés empezar a desarrollar

> 📖 Guía completa: [docs/for-non-technical.md](./docs/for-non-technical.md) (para no-técnicos) · [docs/for-developers.md](./docs/for-developers.md) (para devs)

## Cómo se usan los rules de seguridad

### En Claude.ai (web/app)

El skill `secure-coding` está subido a nivel organización. **Se activa solo** en cada conversación de la org cuando alguien pide código. No hay que hacer nada.

### En Claude Code (CLI)

Cuando creás un repo nuevo desde `ai-forge`, los rules vienen en `.claude/rules/`. Claude Code los carga automáticamente al iniciar sesión en ese repo.

Si querés sumarlos a un repo viejo manualmente:

```bash
# Copiar los rules al repo
cp -r /path/to/ai-forge/.claude/rules ./.claude/rules
git add .claude/rules && git commit -m "chore: add security rules"
```

Más info: [docs/claude-code-setup.md](./docs/claude-code-setup.md).

## Estructura del repo

```
ai-forge/
├── .github/
│   ├── ISSUE_TEMPLATE/     # Formularios para pedir nuevos proyectos
│   ├── workflows/          # GitHub Actions (scaffolding, validación)
│   ├── CODEOWNERS          # AppSec aprueba cambios en rules y workflows
│   └── pull_request_template.md
├── .claude/
│   └── rules/              # Rules que Claude Code carga en este repo
├── rules/                  # FUENTE DE VERDAD de los rules
│   ├── SKILL.md            # 12 reglas universales
│   └── references/         # 9 references por dominio
├── scaffolding/            # Lógica de la Action que crea repos
├── docs/                   # Documentación operativa
├── CONTRIBUTING.md
├── SECURITY.md
└── README.md
```

## Quién mantiene qué

- **Rules de seguridad** (`rules/`, `.claude/rules/`): AppSec
- **Templates** (`bo-template`, `ms-template`, `web-platform`): Frontend Platform + Backend
- **Scaffolding action** (`.github/workflows/scaffold.yml`): AppSec + DevOps
- **Issue templates**: AppSec
- **Docs**: AppSec + colaboraciones bienvenidas

Ver [CODEOWNERS](./.github/CODEOWNERS) para el detalle.

## Contribuir

PRs bienvenidos. Lee [CONTRIBUTING.md](./CONTRIBUTING.md) antes de arrancar.

Cambios en `rules/` o `.github/workflows/` requieren aprobación de AppSec (enforced por CODEOWNERS).

## Reportar vulnerabilidades

Si encontrás una vulnerabilidad en este repo o en cualquier repo creado desde acá, **no abras un Issue público**. Mandá un mail a security@cashea.app o avisá en Slack #appsec.

Ver [SECURITY.md](./SECURITY.md) para el proceso completo.

## Frameworks que aplicamos

- OWASP Top 10 2025 (web)
- OWASP API Security Top 10 2023
- OWASP LLM Top 10 2025
- OWASP GenAI Data Security
- OWASP Mobile Top 10 2024
- Docker CIS Benchmark
- CIS GCP Foundations Benchmark
- ASVS 5.0

Y alineado con las **políticas oficiales DataSec de Cashea**:

- [Política de Clasificación de la Información](https://docs.google.com/document/d/1RVCRTTo7Bqi32qvp3t_ezRTAJoDlruVXEfMCtNGeWZo)
- [Política de Protección de Datos](https://docs.google.com/document/d/18fHgwODXgb06-c4IGWsTJS44gUMvhUPNaip4hyurfjw)
- [Estándar GCS](https://docs.google.com/document/d/1TcOOvWxJpRwiDWVv-kYfagE0DbBp94iX1rFYyEn-s8A)
- [Estándar BigQuery](https://docs.google.com/document/d/10qOOoU7wF8GzmqrhKAWB4_oDfFSU1c1bX79tamFdjUs)

---

<p align="center">
  Hecho con 💛 por <a href="mailto:security@cashea.app">AppSec @ Cashea</a>
</p>
