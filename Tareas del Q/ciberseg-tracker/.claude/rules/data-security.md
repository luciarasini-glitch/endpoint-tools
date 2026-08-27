# Data Security

Reglas para manejo seguro de datos en código generado, alineadas con las políticas oficiales de Cashea.

**Fuente de verdad (política):**
- [Política de Clasificación de la Información](https://docs.google.com/document/d/1RVCRTTo7Bqi32qvp3t_ezRTAJoDlruVXEfMCtNGeWZo) — define las 11 categorías y los 4 niveles
- [Política de Protección de Datos](https://docs.google.com/document/d/18fHgwODXgb06-c4IGWsTJS44gUMvhUPNaip4hyurfjw) — define los mecanismos de protección y la matriz de aplicación
- [Estándar GCS](https://docs.google.com/document/d/1TcOOvWxJpRwiDWVv-kYfagE0DbBp94iX1rFYyEn-s8A) — configuración segura de buckets
- [Estándar BigQuery](https://docs.google.com/document/d/10qOOoU7wF8GzmqrhKAWB4_oDfFSU1c1bX79tamFdjUs) — configuración segura de datasets/tablas

**Cheatsheets de OWASP que aplican:**
- [Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [Sensitive Data Exposure](https://cheatsheetseries.owasp.org/cheatsheets/Sensitive_Data_Exposure_Cheat_Sheet.html)
- [Database Security](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html)
- [Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

**OWASP IDs:** A02:2025, A04:2025, DSGAI03, DSGAI07, DSGAI14

> Este skill **destila** las políticas de Cashea para aplicación en código. La fuente de verdad son las políticas — si hay conflicto, gana la política.

---

## 1. Clasificación de Cashea (memorizá estos códigos)

Toda variable, columna de DB, campo de DTO, log, archivo subido, mensaje de queue, debe poder mapearse a una de estas categorías. **Si no podés clasificarlo, asumí Restringido y consultá con AppSec.**

### Las 11 categorías

| Código | Nombre | Ejemplos | Nivel |
|---|---|---|---|
| **PII-D** | Identificadores personales directos | CDI, RIF, nombre completo, fecha de nacimiento, selfie KYC | 🔴 Restringido |
| **FIN-IND** | Datos financieros individuales | PAN (tarjeta), saldos, transacciones, scoring crediticio, cuentas bancarias | 🔴 Restringido |
| **SEC-PRD** | Credenciales y secretos productivos | API keys, tokens, secrets de BD, certificados, llaves KMS | 🔴 Restringido |
| **PII-I** | Identificadores personales indirectos | Email, teléfono, dirección, IP de usuario | 🟠 Confidencial |
| **IP-CORE** | Modelos y lógica propietaria | Algoritmos de scoring, reglas antifraude, modelos predictivos | 🟠 Confidencial |
| **REG-RPT** | Datos regulatorios reportables | Reportes a reguladores, registros auditables | 🟠 Confidencial |
| **EMP-DATA** | Datos de empleados | Nómina, evaluaciones, contratos | 🟠 Confidencial |
| **OPS-LOG** | Logs y observabilidad | Logs de app, audit trail, métricas, traces | 🟠 Confidencial |
| **FIN-AGG** | Datos financieros agregados | KPIs, reportes consolidados, métricas agregadas | 🟡 Interno |
| **TECH-NP** | Datos técnicos sin PII | Configs, metadatos técnicos | 🟡 Interno |
| **PUB** | Información pública | Web pública, marketing, comunicados | 🟢 Público |

### Los 4 niveles de criticidad

- 🟢 **Público (PUB)** — Aprobado para difusión externa. Sin restricciones.
- 🟡 **Interno (FIN-AGG, TECH-NP)** — No para divulgación pública. Impacto operativo menor.
- 🟠 **Confidencial (PII-I, IP-CORE, REG-RPT, EMP-DATA, OPS-LOG)** — Impacto legal/reputacional/financiero moderado.
- 🔴 **Restringido (PII-D, FIN-IND, SEC-PRD)** — Máxima sensibilidad, protegido por ley/regulación.

---

## 2. Mecanismos de protección (qué se aplica a qué)

La Política de Protección de Datos sección 6 define la matriz oficial. Resumen accionable para código:

### 🔴 PII-D · Identificadores personales directos

| Etapa | Mecanismo |
|---|---|
| Almacenamiento | Cifrado obligatorio. CMEK en GCP. |
| Acceso | RBAC + MFA |
| Transmisión interna | Canal cifrado (TLS) |
| Transmisión externa | Canal cifrado (TLS 1.2+) |
| Visualización | **Seudonimización** — mostrar token/seudónimo, no el valor real |
| Eliminación | Borrado seguro |

### 🔴 FIN-IND · Datos financieros individuales

| Etapa | Mecanismo |
|---|---|
| Almacenamiento | Cifrado obligatorio. CMEK en GCP. |
| Acceso | RBAC + MFA |
| Transmisión | Canal cifrado |
| Visualización | **Truncamiento** o **enmascaramiento** según el caso |
| Eliminación | Borrado seguro |

**Reglas específicas para PAN (números de tarjeta):**

- Si Cashea es **procesador de pagos**: prohibido almacenar CVV, PIN, Track I/II después de la autorización.
- Si Cashea es **emisor**: permitido en entornos PCI DSS certificados.
- Cuando solo se necesitan BIN + últimos 4: **truncar** según PCI DSS (máx 6 primeros + 4 últimos visibles).

### 🔴 SEC-PRD · Credenciales y secretos productivos

| Etapa | Mecanismo |
|---|---|
| Almacenamiento | **EXCLUSIVAMENTE en Vault o Módulo de Seguridad** (Secret Manager). Prohibido en bases de datos convencionales o en código. |
| Acceso | Solo Custodios formalmente designados |
| Transmisión | Canal cifrado |
| Visualización | **NO PERMITIDO** en ninguna interfaz, log, o reporte |
| Eliminación | Borrado seguro |

**Reglas específicas:**
- Las referencias a secretos (IDs/tokens) sí pueden ir en DB; el secreto real va en Vault.
- Acceso revocado inmediatamente ante baja, cambio de función o sospecha de compromiso.

### 🟠 Confidencial (PII-I, IP-CORE, REG-RPT, EMP-DATA, OPS-LOG)

| Etapa | Mecanismo |
|---|---|
| Almacenamiento | Sin restricciones para el dato particular, pero la base/storage debe estar cifrada |
| Acceso | RBAC + MFA |
| Transmisión interna | Sin restricciones (pero recomendado canal cifrado) |
| Transmisión externa | Canal cifrado |
| Visualización | **Enmascaramiento para PII-I** ante roles sin permiso explícito. El resto sin restricciones. |

### 🟡 Interno (FIN-AGG, TECH-NP) y 🟢 Público (PUB)

Sin restricciones específicas, salvo:
- **Acceso Interno**: RBAC + MFA (por defecto)
- **Transmisión externa Interno**: canal cifrado

---

## 3. Las 7 técnicas de protección — cuándo usar cuál

| Técnica | Cuándo usarla | Reversible | Ejemplo |
|---|---|---|---|
| **Cifrado** | Almacenamiento + transmisión de PII-D, FIN-IND, SEC-PRD | Sí (con clave) | AES-256-GCM en columna de DB |
| **Enmascaramiento** | Mostrar PII-I en UI sin permiso de ver crudo | No (display only) | `jo***@cashea.app` |
| **Anonimización** | Reportes, analytics, datos para entrenar modelos | **No** (irreversible) | Hash + remover columnas identificadoras |
| **Seudonimización** | PII-D que necesita reidentificarse después | Sí (con info adicional) | UUID en DB, mapping en otro lado |
| **Truncamiento** | Mostrar PAN, document numbers | **No** (irreversible) | `****1234` |
| **Vault** | SEC-PRD obligatorio, sin excepción | N/A | Secret Manager |
| **Borrado seguro** | Eliminación al final del ciclo de vida | N/A | Sobreescritura, deletion + audit log |

---

## 4. Aplicación práctica en código

### 4.1 Identificá la categoría antes de escribir el código

```typescript
// ❌ MAL — campo sin clasificar
class User {
  email: string;
  ci: string;
  cardNumber: string;
}

// ✅ BIEN — categoría documentada
class User {
  /** PII-I — enmascarar en UI sin permiso explícito */
  email: string;

  /** PII-D — cifrado obligatorio at rest, seudonimización en visualización */
  ci: string;

  /** FIN-IND — truncar a últimos 4 dígitos en visualización (PCI DSS) */
  cardLastFour: string;
  // El PAN completo NUNCA persiste fuera de Vault/HSM
}
```

### 4.2 Cifrado en reposo

**GCP cifra todo at rest por default** (Google-managed keys). Para datos Restringidos usar **CMEK** (Customer-Managed Encryption Keys):

| Servicio GCP | Configuración CMEK |
|---|---|
| Cloud Storage | `kmsKeyName` en bucket o por objeto |
| Cloud SQL | `disk_encryption_configuration.kms_key_name` |
| BigQuery | `default_encryption_configuration.kms_key_name` en dataset |
| Pub/Sub | KMS key en topic |
| Secret Manager | Customer-managed encryption configurada |

```hcl
# Terraform — bucket con CMEK para datos Restringidos
resource "google_storage_bucket" "restricted_data" {
  name     = "cashea-billing-prd-restringido-sae1-pii"
  location = "southamerica-east1"

  encryption {
    default_kms_key_name = google_kms_crypto_key.bucket_key.id
  }

  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  labels = {
    cost-center      = "cc-4521"
    managed-by       = "terraform"
    backup-policy    = "daily"
    created-by       = "appsec"
  }
  # Resource Tags se aplican vía google_tags_tag_binding
}
```

### 4.3 Cifrado en tránsito

**TLS 1.2+ obligatorio** en toda comunicación. NUNCA `verify=False` o `rejectUnauthorized: false`.

```typescript
// ❌ MAL — permite MitM
const conn = createConnection({
  ssl: { rejectUnauthorized: false }
});

// ✅ BIEN
const conn = createConnection({
  ssl: { rejectUnauthorized: true, ca: fs.readFileSync('ca-cert.pem') }
});
```

```python
# ❌ MAL
requests.get(url, verify=False)

# ✅ BIEN
requests.get(url, verify=True)
```

### 4.4 SEC-PRD — Secret Manager (sin excepciones)

```python
# ❌ MAL — SEC-PRD en código
API_KEY = "sk-abc123..."

# ❌ MAL — SEC-PRD en variable de entorno plain
API_KEY = os.getenv("API_KEY")

# ❌ MAL — SEC-PRD en DB convencional
db.query("INSERT INTO secrets (key) VALUES (?)", api_key)

# ✅ BIEN — Secret Manager
from google.cloud import secretmanager

@lru_cache(maxsize=32)
def get_secret(name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(
        request={"name": f"projects/{PROJECT}/secrets/{name}/versions/latest"}
    )
    return response.payload.data.decode("UTF-8")
```

**Reglas:**
- Cada SEC-PRD tiene su propio nombre y versión
- Rotación cada 90 días (alineado con Política sección 5.1)
- IAM mínimo: solo la SA del servicio que lo necesita tiene `roles/secretmanager.secretAccessor`
- Cargar al startup, no en cada request
- Auditoría: cada acceso queda en Cloud Audit Logs

### 4.5 Enmascaramiento de PII-I

```typescript
// PII-I sin permiso explícito de ver crudo
function maskEmail(email: string): string {
  const [user, domain] = email.split('@');
  return `${user.slice(0, 2)}***@${domain}`;
}

function maskPhone(phone: string): string {
  return `***-***-${phone.slice(-4)}`;
}

// FIN-IND — truncamiento PCI DSS
function maskCard(pan: string): string {
  return `${pan.slice(0, 6)}******${pan.slice(-4)}`;
}

// PII-D — seudonimización
async function pseudoCi(ci: string): Promise<string> {
  // Devolver un token, no el valor real
  return await tokenizationService.tokenize(ci);
}
```

Aplicar en:
- Logs estructurados (ver `references/logging-and-monitoring.md`)
- Mensajes de error
- Dashboards
- Exports/reports
- Notifications a Slack/email

### 4.6 BigQuery — Estándar de Cashea

Toda tabla en BigQuery **debe tener** asignados los Resource Tags:
- `data-owner` (platform / engineering / finance / security / data / product)
- `data-classification` (publico / interno / confidencial / restringido)
- `environment` (dev / stg / prd / sandbox)

Más Labels operativos: `cost-center`, `managed-by`, `backup-policy`, `created-by`.

```python
# Queries SIEMPRE parameterizadas
from google.cloud import bigquery

client = bigquery.Client()

# ❌ MAL — SQL injection + posible exfiltración
query = f"SELECT * FROM `proj.ds.users` WHERE email = '{email}'"

# ✅ BIEN — parameterized + LIMIT
query = """
    SELECT * FROM `proj.ds.users`
    WHERE email = @email
    LIMIT @max_rows
"""
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("email", "STRING", email),
        bigquery.ScalarQueryParameter("max_rows", "INT64", 100),
    ]
)
client.query(query, job_config=job_config).result()
```

**IAM en BigQuery:**

| Rol | Cuándo usarlo |
|---|---|
| `roles/bigquery.dataViewer` | Lectura. Analistas, dashboards. |
| `roles/bigquery.dataEditor` | ETL, ingest pipelines. |
| `roles/bigquery.jobUser` | Ejecutar queries. |
| `roles/bigquery.metadataViewer` | Tools de catálogo, gobernanza. |
| `roles/bigquery.dataOwner` | Solo administradores de datos, previa aprobación. |
| `roles/bigquery.admin` | **Restringido** — solo equipo de data, temporal. |

**NUNCA**: `roles/owner`, `roles/editor`, `roles/viewer` en cuentas de servicio.

**Read-only views** para dashboards:

```sql
CREATE VIEW `proj.dashboard_views.orders_summary` AS
SELECT
  order_date, region, COUNT(*) AS total, SUM(amount) AS revenue
FROM `proj.raw.orders`
GROUP BY order_date, region;
```

La SA del dashboard solo accede a `dashboard_views`, no a `raw`.

### 4.7 Cloud Storage — Estándar de Cashea

Naming obligatorio: `{org}-{proyecto}-{entorno}-{clasificación}-{región}-{descripción}`

Ejemplo: `cashea-billing-prd-restringido-sae1-invoices`

**Configuración mínima:**

```hcl
resource "google_storage_bucket" "data" {
  name          = "cashea-billing-prd-confidencial-sae1-uploads"
  location      = "southamerica-east1"
  storage_class = "STANDARD"

  # Anti acceso público (Política sección 4.2)
  public_access_prevention    = "enforced"
  # Centraliza control en IAM (Política sección 5)
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  # Soft delete (Estándar sección 7.4 — mínimo 7 días)
  soft_delete_policy {
    retention_duration_seconds = 604800  # 7 días
  }

  # Lifecycle (Estándar sección 7.3)
  lifecycle_rule {
    condition { age = 30 }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition { age = 365, with_state = "ARCHIVED" }
    action { type = "Delete" }
  }

  # CMEK para Restringido
  encryption {
    default_kms_key_name = google_kms_crypto_key.bucket_key.id
  }

  labels = {
    cost-center      = "cc-4521"
    managed-by       = "terraform"
    backup-policy    = "daily"
    created-by       = "appsec"
  }
}
```

**Signed URLs** para compartir objetos:
- Expiración máxima: **1 hora**
- NUNCA hacer objetos públicos directamente

### 4.8 Cloud SQL

```hcl
resource "google_sql_database_instance" "db" {
  name             = "cashea-billing-prd-primary"
  database_version = "POSTGRES_15"
  region           = "southamerica-east1"

  settings {
    ip_configuration {
      ipv4_enabled    = false  # NO IP pública
      private_network = google_compute_network.vpc.id
      require_ssl     = true   # Política sección 5.1 — canal cifrado obligatorio
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 30
      }
    }
  }

  # CMEK para Restringido
  encryption_key_name = google_kms_crypto_key.db_key.id
  deletion_protection = true
}
```

NUNCA `require_ssl = false`, NUNCA `ipv4_enabled = true` para datos Restringidos/Confidencial.

---

## 5. Persistencia mínima (Política sección 7.1)

> Sólo se recolectan datos estrictamente necesarios. Bajo ninguna circunstancia datos sin finalidad declarada.

| Tipo de dato | Storage | Retención |
|---|---|---|
| Sesiones de usuario | Memoria / Redis (NO en DB convencional) | Hasta logout o 24h |
| Logs (OPS-LOG) | Cloud Logging + sink a BigQuery | 90 días app, 400 días audit/security |
| PII-D, PII-I | Cloud SQL + CMEK | Mínima legal/operativa |
| Archivos uploaded | GCS + lifecycle rules | 30 días o el mínimo |
| SEC-PRD | Secret Manager | Hasta rotación |

### NO persistir en filesystem del container

Cloud Run filesystem es **efímero**. Si guardás archivos ahí: se pierden, no se comparten, llenan disco.

### Right to be forgotten

Si manejás PII, tenés que poder borrarla cuando el usuario lo pide:

```
[ ] Identificar todas las DB / GCS / BigQuery donde está la PII
[ ] Endpoint admin (con auth fuerte) para iniciar el delete
[ ] Borrar de DB primaria
[ ] Borrar de DBs secundarias / read replicas
[ ] Borrar de backups (o documentar que el dato expira con la retention del backup)
[ ] Borrar de logs (o redactar)
[ ] Borrar de BigQuery (UPDATE para anonimizar, o DELETE)
[ ] Borrar de archivos en GCS
[ ] Loguear la acción de delete (con la fecha, no con el dato)
```

---

## 6. Datos en prompts de IA (LLM data handling)

Esta sección responde a la pregunta: **¿qué puedo pegar en un chat de Claude/GPT/Gemini al pedir código?**

### Matriz de qué se puede compartir con LLMs

| Categoría | Claude.ai workspace Cashea (con DPA) | Claude/GPT personal | Otros LLMs (no aprobados) |
|---|---|---|---|
| **PUB** | ✅ | ✅ | ✅ |
| **TECH-NP, FIN-AGG** | ✅ | ⚠️ caso por caso | ❌ |
| **PII-I, OPS-LOG** | ⚠️ con masking | ❌ | ❌ |
| **REG-RPT, EMP-DATA, IP-CORE** | ⚠️ con AppSec aprobando | ❌ | ❌ |
| **PII-D, FIN-IND** | ❌ NUNCA | ❌ NUNCA | ❌ NUNCA |
| **SEC-PRD** | ❌ NUNCA (incluso por error → rotar) | ❌ NUNCA | ❌ NUNCA |

### Lo que NUNCA se pega en una IA

- Stack traces con tokens, JWTs, Authorization headers
- Logs de producción sin redactar
- Exports de DB con clientes reales
- Configs con secrets (`.env`, kubeconfig, terraform.tfvars)
- Screenshots de paneles con datos de clientes
- Queries SQL con valores reales en el WHERE
- Documentos legales/financieros con datos identificables
- Cualquier cosa que tenga PII-D, FIN-IND, o SEC-PRD

### Patrones para usar IAs sin filtrar datos

**1. Datos sintéticos en lugar de reales:**

```typescript
// ❌ MAL — pegaste tu DB
const users = [
  { email: "juan.perez@cashea.app", ci: "12345678" },
  ...
];

// ✅ BIEN — datos de ejemplo
const users = [
  { email: "user@example.com", ci: "00000000" },
  ...
];
```

**2. Schemas sin valores:**

```sql
-- ✅ Pegá la estructura, no los datos
CREATE TABLE orders (
  id UUID PRIMARY KEY,
  user_id UUID,
  amount NUMERIC(10,2),
  created_at TIMESTAMPTZ
);
```

**3. Ejemplos genéricos para errores:**

```
❌ "Error: invalid token eyJhbGciOiJIUzI1NiJ9..."
✅ "Error: invalid token <REDACTED-JWT>"
```

### Si te equivocaste y pegaste algo sensible

1. **SEC-PRD (token, API key, password):** rotar inmediatamente. El IdP/proveedor donde vive ese secret. Reportar a AppSec.
2. **PII-D / FIN-IND:** reportar a AppSec. Borrar la conversación si el provider lo permite.
3. **Otras categorías:** reportar a AppSec, evaluar criticidad.

**Nadie es castigado por reportar.** La cultura de seguridad funciona si los errores se reportan rápido.

---

## 7. Backup y archivado

- Cifrados at rest (default GCP, CMEK si los originales lo requieren)
- Retention policy alineada con la del dato original
- Acceso restringido y auditado
- Test de restore periódico (no asumir que el backup funciona)
- Bucket Lock para datos sujetos a retención legal/regulatoria

---

## 8. Checklist al diseñar un servicio

```
[ ] Identifiqué TODAS las categorías de datos que el servicio toca (PII-D, FIN-IND, etc.)
[ ] Si hay Restringido: aprobación de AppSec obtenida
[ ] Cada campo en DTO/modelo tiene comentario con su categoría Cashea
[ ] Cifrado at rest configurado (default GCP, CMEK si Restringido)
[ ] TLS 1.2+ obligatorio en todas las conexiones
[ ] Secrets en Secret Manager (NUNCA en código, env vars planas, ni DB)
[ ] IAM mínimo para la SA (roles granulares, NO roles primitivos)
[ ] BigQuery: parameterized queries, views read-only, Resource Tags
[ ] Cloud SQL: SSL/TLS obligatorio, sin IP pública, IAM auth
[ ] Cloud Storage: PAB enforced, UBLA, naming convention, CMEK si aplica
[ ] APIs externas: HTTPS verify=true, allowlist, timeouts
[ ] PII-I masked en logs y outputs
[ ] PII-D pseudonymized en visualización
[ ] FIN-IND truncado en visualización
[ ] SEC-PRD nunca visualizable
[ ] Plan de data deletion (right to be forgotten)
[ ] Retention policy documentada
[ ] No persistencia en filesystem del container
[ ] Resource Tags asignados (data-owner, data-classification, environment)
[ ] No estoy compartiendo PII-D / FIN-IND / SEC-PRD en prompts de IA
```
