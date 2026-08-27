---
name: secure-coding
description: >
  MANDATORY security rules for ALL code generation, review, or modification at Cashea, AND for any
  prompt containing sensitive data. This skill MUST be loaded whenever anyone generates, writes,
  edits, or reviews ANY code — backend (Node, NestJS, Python, FastAPI), frontend (React, Next.js,
  TypeScript), Docker, Terraform/IaC, SQL/BigQuery, API endpoints, auth flows, CI/CD, shell scripts.
  Trigger on requests like "create a service", "build an API", "make a dashboard", "write a function",
  "fix a bug", "add a feature", "connect to a database", "integrate with BigQuery", "deploy to Cloud
  Run", or ANY code output. ALSO trigger at the start of any conversation where the user message may
  contain Cashea sensitive data (PII-D, FIN-IND, SEC-PRD). Applies to ALL languages and frameworks.
  NO exceptions. If code is generated or sensitive data shared, this skill MUST be consulted FIRST.
---

# Cashea Secure Coding

Mandatory security rules for every piece of code generated within Cashea, based on:

- **Políticas oficiales de Cashea** (fuente de verdad)
- OWASP Top 10 2025 (web)
- OWASP API Security Top 10 2023
- OWASP LLM Top 10 2025 (AI risks)
- OWASP GenAI Data Security
- OWASP Mobile Top 10 2024
- OWASP Cheatsheet Series
- Docker CIS Benchmark
- CIS GCP Foundations Benchmark

**These rules are not suggestions. They are mandatory.**

If a request would require breaking these rules, refuse and explain why.
If the user insists, escalate to AppSec — do not comply.

---

## How to use this skill

1. **Always read this file first.** It contains universal rules that apply to every piece of code.
2. **Then read the relevant reference(s)** based on what's being built:

| Building... | Read |
|---|---|
| Any backend service (auth, sessions, JWT) | `references/auth-and-sessions.md` |
| Any code that touches user input (API, form, query) | `references/input-validation.md` |
| Any code that handles data (DB, BigQuery, GCS, PII, secrets) | `references/data-security.md` (incluye matriz de uso de LLMs y códigos Cashea) |
| Any code that produces logs | `references/logging-and-monitoring.md` |
| Node.js / NestJS backend | `references/node-nestjs.md` |
| Python backend | `references/python.md` |
| React / Next.js frontend | `references/frontend.md` |
| Dockerfile / containers | `references/docker.md` |
| Terraform / IaC | `references/iac-terraform.md` |

3. **Multiple references usually apply.** A NestJS API needs `auth-and-sessions` + `input-validation` + `logging` + `node-nestjs` + `docker` + `data-security`. Read them all.

---

## Universal rules (apply to ALL code, ALL stacks)

### 1. Secrets — NEVER hardcode (OWASP A04:2025, Cashea SEC-PRD)

- NEVER put API keys, passwords, tokens, connection strings, or credentials in code
- NEVER commit `.env` files — only `.env.example` with placeholder values
- Secrets come from environment variables (dev) or **GCP Secret Manager** (prod)
- SEC-PRD category in Cashea taxonomy: must reside **EXCLUSIVELY** in Vault/Secret Manager (Política de Protección de Datos sección 5.5)
- If you see a secret in code during review, flag it as **CRITICAL** immediately

### 2. Input validation — ALWAYS validate (OWASP A05:2025, API3:2023)

- Every external input MUST be validated: type, length, format, range
- IDs MUST be UUIDs or specific formats — NEVER accept free strings
- Pagination MUST have maximum limits (typically 100 max)
- NEVER trust data from clients, APIs, databases, files, or queue messages
- See `references/input-validation.md`

### 3. Authentication — ALWAYS enforce (OWASP A01:2025, A07:2025, API1:2023, API2:2023)

- Every endpoint requires authentication by default
- Public routes are explicitly whitelisted — everything else is protected
- ALWAYS validate JWTs: signature, `iss`, `aud`, `exp`, algorithm
- NEVER trust a JWT just because it's signed — verify it's YOUR JWT (issuer match)
- See `references/auth-and-sessions.md`

### 4. Authorization — ALWAYS check the resource (OWASP A01:2025, API1:2023, API5:2023)

- "Authenticated" ≠ "authorized". Every action checks: does THIS user have access to THIS resource?
- This is how you prevent **IDOR / BOLA**: never assume `userId === resourceOwnerId`, verify it
- Admin actions require explicit role check, not just "is logged in"
- Use **UUIDs**, not sequential IDs — sequential IDs make IDOR trivial to exploit
- See `references/auth-and-sessions.md`

### 5. Errors — NEVER leak internals (OWASP A10:2025)

- Error responses to clients: `{ statusCode, message, requestId }` — NOTHING else
- Stack traces, file paths, SQL errors, internal IPs go to **server logs only**
- 4xx errors can show specific messages; 5xx errors show generic messages

### 6. Queries — ALWAYS parameterize (OWASP A05:2025)

- NEVER concatenate or interpolate user input into SQL, NoSQL, or BigQuery queries
- ALWAYS use the ORM, parameterized queries, or query parameters (`@param` for BigQuery)
- This rule has zero exceptions

### 7. Logging — NEVER log sensitive data (OWASP A09:2025)

- NEVER log: passwords, tokens, API keys, credit card numbers, PII, full request/response bodies, Authorization headers
- ALWAYS log the 5W: **Who** (userId), **What** (action), **When** (timestamp), **Where** (resource/IP), **Why outcome** (success/failure + reason)
- Use structured logging (JSON), never `console.log()` / `print()`
- Cashea OPS-LOG category: confidencial — masking obligatorio para PII-I, NUNCA loguear PII-D / FIN-IND / SEC-PRD
- See `references/logging-and-monitoring.md`

### 8. Dependencies — ALWAYS verify (OWASP A03:2025, LLM09:2025)

- AI models hallucinate package names. **Verify every package exists** on npmjs.com / PyPI / crates.io before installing
- ALWAYS use lockfiles (`package-lock.json`, `poetry.lock`, `requirements.txt` with pins)
- In CI: `npm ci` (not `npm install`), `pip install --no-deps -r requirements.txt`
- Updates go through Dependabot PRs — review the changelog before merging

### 9. Data — minimize and protect (OWASP DSGAI07, A02:2025, Cashea Política de Protección de Datos)

- Store only what you need, only for as long as you need it (Política sección 7.1 — minimización)
- Categorías Cashea (memorizar): PII-D, FIN-IND, SEC-PRD = Restringido | PII-I, IP-CORE, REG-RPT, EMP-DATA, OPS-LOG = Confidencial | FIN-AGG, TECH-NP = Interno | PUB = Público
- Restringido at rest: **CMEK obligatorio** (Customer-Managed Encryption Keys)
- All data in transit: **TLS 1.2+** (prefer 1.3), NUNCA `rejectUnauthorized: false`
- Read-only access where possible (dashboards READ from BigQuery, never WRITE)
- See `references/data-security.md` for the full Cashea taxonomy and mechanisms

### 10. Headers and CORS (OWASP A02:2025, API8:2023)

- CORS: explicit allowed origins, NEVER `*` in production
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS
- Rate limiting on sensitive endpoints (login, registration, password reset, expensive queries)

### 11. AI-specific rules (OWASP LLM02:2025, DSGAI03)

- NEVER paste secrets, PII, customer data, or financial data into AI prompts (ChatGPT, Claude, Gemini, anywhere)
- NEVER trust AI-generated package names without verifying they exist
- NEVER deploy AI-generated code without passing CI (CodeQL + Dependabot + Secret Scanning)
- AI code is a **starting point**. It MUST be reviewed and pass the pipeline.

### 12. Detección proactiva de datos sensibles en prompts (Cashea Política de Protección de Datos)

If the user includes in their message data that appears to match a Cashea **Restringido** category, you MUST stop and warn before processing:

- **PII-D** (CDI, RIF, full names, dates of birth, KYC selfies)
- **FIN-IND** (PAN/credit card numbers, account balances, real transactions, scoring)
- **SEC-PRD** (API keys, JWTs, tokens, passwords, certificates, KMS keys)

**What to do when detected:**

1. STOP — do not process the request as-is
2. Tell the user clearly: "El mensaje contiene lo que parece [categoría]. Según la Política de Protección de Datos de Cashea, esto no debería compartirse en prompts de IA."
3. If it's SEC-PRD: tell them to **rotate the secret immediately** and report to AppSec.
4. Offer to continue with masked/synthetic example data: "¿Querés que continúe con datos de ejemplo (`user@example.com`, `<REDACTED-TOKEN>`, etc.)?"
5. Document in your reasoning what category was detected (helps the user learn).

This is not paranoia — it is enforcing the Cashea data handling policy at the prompt layer. The goal is to **minimize the impact of accidental copy/paste of sensitive info**, which is the #1 way data leaks via LLMs.

**This rule applies BEFORE the request is processed**, not after.

---

## When in doubt

- **Security vs UX trade-off:** present both options to the user and let them choose, but document the security trade-off explicitly.
- **A pattern not in this skill:** look up the relevant OWASP Cheatsheet at https://cheatsheetseries.owasp.org/ and apply the principles. If still unsure, recommend escalating to AppSec.
- **Refusal:** if a request would require violating these rules and there's no safe alternative, refuse and explain. Examples: "store passwords in plaintext", "skip input validation for performance", "log full request bodies for debugging in prod".

---

## Cashea-specific context

- **Cloud:** Google Cloud Platform (Cloud Run, BigQuery, Cloud SQL, Secret Manager, Artifact Registry, Cloud Armor)
- **CI/CD:** GitHub Actions for CI (with GHAS: CodeQL + Dependabot + Secret Scanning), Cloud Build for CD
- **Auth for internal users (employees):** JumpCloud SSO via OIDC
- **Auth between services:** OAuth2 Client Credentials or service-to-service tokens
- **Default deployment:** Cloud Run with `--ingress=internal-and-cloud-load-balancing`, no public ingress unless explicitly justified
- **Secrets:** GCP Secret Manager only. Never env vars in Cloud Run for sensitive secrets.

### Políticas oficiales de Cashea (fuente de verdad)

Este skill **destila** las siguientes políticas para aplicación en código. Si hay conflicto, la política gana.

- **Política de Clasificación de la Información** — define las 11 categorías (PII-D, PII-I, FIN-IND, FIN-AGG, IP-CORE, SEC-PRD, REG-RPT, EMP-DATA, OPS-LOG, TECH-NP, PUB) y los 4 niveles (Público, Interno, Confidencial, Restringido).
- **Política de Protección de Datos** — define los 7 mecanismos (cifrado, enmascarado, anonimización, seudonimización, truncamiento, vault, RBAC) y la matriz de aplicación por categoría × etapa del ciclo de vida.
- **Estándar de Configuración Segura — Google Cloud Storage** — define naming, PAB, UBLA, CMEK, lifecycle, Resource Tags obligatorios.
- **Estándar de Configuración Segura — BigQuery** — define IAM, VPC-SC, Audit Logs, clasificación de datasets/tablas vía tags.

Ver `references/data-security.md` para el detalle accionable.
