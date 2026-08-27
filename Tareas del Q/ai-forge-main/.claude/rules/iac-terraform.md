# Infrastructure as Code (Terraform)

Reglas para Terraform y otros IaC en GCP.

**Cheatsheets oficiales que aplican:**
- [Infrastructure as Code Security](https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html)
- [Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

**Referentes:**
- CIS GCP Foundations Benchmark
- Google Cloud Architecture Framework

**OWASP IDs:** A04:2025, A05:2025, A08:2025, ASI09
---

## Estándares Cashea (obligatorios)

> **Fuente de verdad:** [Estándar GCS](https://docs.google.com/document/d/1TcOOvWxJpRwiDWVv-kYfagE0DbBp94iX1rFYyEn-s8A) + [Estándar BigQuery](https://docs.google.com/document/d/10qOOoU7wF8GzmqrhKAWB4_oDfFSU1c1bX79tamFdjUs)

### Resource Tags obligatorios (gobernanza y seguridad)

Todo recurso GCP que persiste datos (bucket GCS, dataset/tabla BigQuery, instancia Cloud SQL, secret) **debe tener** asignados estos 3 Resource Tags. Son parte del enforcement de IAM y Org Policies de Cashea — sin ellos, el recurso no debería crearse.

| Tag Key | Valores permitidos | Para qué se usa |
|---|---|---|
| `data-owner` | `platform` \| `engineering` \| `finance` \| `security` \| `data` \| `product` | Auditoría de responsabilidad |
| `data-classification` | `publico` \| `interno` \| `confidencial` \| `restringido` | Condición IAM: restringir acceso según clasificación |
| `environment` | `dev` \| `stg` \| `prd` \| `sandbox` | Org Policy: restricciones por entorno |

```hcl
# Aplicación de Resource Tags vía google_tags_tag_binding
resource "google_tags_tag_binding" "bucket_classification" {
  parent    = "//storage.googleapis.com/projects/_/buckets/${google_storage_bucket.data.name}"
  tag_value = "tagValues/${var.classification_restringido_tag_value_id}"
}

resource "google_tags_tag_binding" "bucket_owner" {
  parent    = "//storage.googleapis.com/projects/_/buckets/${google_storage_bucket.data.name}"
  tag_value = "tagValues/${var.owner_engineering_tag_value_id}"
}

resource "google_tags_tag_binding" "bucket_environment" {
  parent    = "//storage.googleapis.com/projects/_/buckets/${google_storage_bucket.data.name}"
  tag_value = "tagValues/${var.environment_prd_tag_value_id}"
}
```

### Labels operativos obligatorios

Aparte de los Resource Tags, todo recurso debe llevar Labels para tracking operativo y de costos:

| Label | Valores | Ejemplo |
|---|---|---|
| `cost-center` | Código del centro de costos | `cc-4521` |
| `managed-by` | `terraform` \| `manual` \| `pulumi` | `terraform` |
| `backup-policy` | `daily` \| `weekly` \| `monthly` \| `none` | `daily` |
| `created-by` | Solicitante | `appsec` |

### Naming Convention

Todo bucket GCS debe seguir:

```
{org}-{proyecto}-{entorno}-{clasificación}-{región}-{descripción}
```

Ejemplo: `cashea-billing-prd-restringido-sae1-invoices`

Componentes:
- `org`: siempre `cashea`
- `proyecto`: nombre del proyecto/sistema (ej: `billing`, `kyc`, `risk`)
- `entorno`: `dev` \| `stg` \| `prd` \| `sandbox`
- `clasificación`: `publico` \| `interno` \| `confidencial` \| `restringido`
- `región`: GCP abreviada (ej: `sae1` para southamerica-east1)
- `descripción`: breve, lowercase, separado con guiones

### Org Policies que deben estar enforced (no romperlas)

Cuando armás Terraform, asumí que estas Org Policies están activas a nivel organización:

| Org Policy Constraint | Valor | Implicancia para tu Terraform |
|---|---|---|
| `storage.publicAccessPrevention` | Enforced | Tu bucket no puede ser público |
| `storage.uniformBucketLevelAccess` | Enforced | No uses ACLs por objeto, solo IAM |
| `storage.secureHttpTransport` | Enforced | Tus apps deben hablar HTTPS al bucket |
| `gcp.resourceLocations` | Lista permitida | No podés crear recursos fuera de las regiones aprobadas |
| `iam.allowedPolicyMemberDomains` | Dominio corporativo | No podés dar acceso a cuentas externas |

Si tu Terraform falla porque viola alguna de estas → **NO desactives la Org Policy**, repensá el diseño.

---


## Por qué importa

IaC es código que crea infraestructura. Un Terraform mal escrito puede:
- Crear buckets públicos con datos sensibles
- Asignar `roles/owner` a una SA de servicio
- Exponer una DB a internet
- Dejar secrets en el state file
- Crear firewall rules `0.0.0.0/0`

Los errores en IaC se replican a escala — un módulo malo se usa en 50 servicios.

---

## Reglas universales

### 1. Secrets NUNCA en el .tf

```hcl
# ❌ MAL — el secret queda en el repo y en el state
resource "google_sql_user" "db" {
  password = "MyP@ssw0rd"
}

# ❌ MAL — el secret queda en .tfvars que se suele commitear
variable "db_password" {
  default = "MyP@ssw0rd"
}

# ✅ BIEN — desde Secret Manager
data "google_secret_manager_secret_version" "db_pass" {
  secret = "db-password"
}

resource "google_sql_user" "db" {
  password = data.google_secret_manager_secret_version.db_pass.secret_data
}
```

### 2. State file encriptado y remoto

El state de Terraform contiene **TODOS** los recursos creados, incluyendo passwords resueltos:

```hcl
# ❌ MAL — state local, en el filesystem del developer
terraform {
  # No backend = state local
}

# ✅ BIEN — state en GCS con encryption + state locking
terraform {
  backend "gcs" {
    bucket  = "cashea-tfstate-prod"
    prefix  = "infra/networking"
    encryption_key = "..." # CMEK opcional pero recomendado
  }
}
```

**El bucket de tfstate:**
- IAM mínimo (solo CI/CD y CloudSec acceden)
- Versioning habilitado
- Encryption at rest (default GCP, CMEK preferido)
- Lifecycle: NO borrar versiones antiguas (rollback)
- NO público

### 3. Módulos versionados

```hcl
# ❌ MAL — pulleando from main, puede romper sin aviso
module "service" {
  source = "github.com/cashea-bnpl/tf-modules//cloud-run"
}

# ✅ BIEN — pinneado a tag/SHA
module "service" {
  source = "github.com/cashea-bnpl/tf-modules//cloud-run?ref=v1.4.2"
}
```

---

## IAM — least privilege

### NUNCA dar roles broad

```hcl
# ❌ NUNCA en producción
resource "google_project_iam_member" "bad" {
  role   = "roles/owner"      # NO
  member = "serviceAccount:..."
}

resource "google_project_iam_member" "also_bad" {
  role   = "roles/editor"     # NO
  member = "serviceAccount:..."
}
```

Los roles primitivos (`owner`, `editor`, `viewer`) dan acceso transversal a TODO. CIS Benchmark los prohíbe en cuentas de servicio.

### Patrón correcto: roles específicos al recurso específico

```hcl
# ✅ BIEN — roles específicos, scope al recurso
resource "google_secret_manager_secret_iam_member" "svc_can_read" {
  secret_id = google_secret_manager_secret.db_pass.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.svc.email}"
}

resource "google_bigquery_dataset_iam_member" "svc_can_read_dataset" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.svc.email}"
}
```

### Service Accounts dedicadas

```hcl
# Una SA por servicio. Nunca compartir.
resource "google_service_account" "svc" {
  account_id   = "bo-orders-sa"
  display_name = "Service Account for bo-orders Cloud Run service"
}
```

### NO permitir Service Account Keys exportadas

```hcl
# ❌ NUNCA crear keys en Terraform en producción
# resource "google_service_account_key" ... NO

# ✅ Workload Identity Federation o impersonation
```

---

## Networking

### Firewall rules: deny by default

```hcl
# ❌ MAL
resource "google_compute_firewall" "all_allowed" {
  name    = "allow-all"
  network = google_compute_network.vpc.name

  allow {
    protocol = "all"
  }
  source_ranges = ["0.0.0.0/0"]   # NO
}

# ✅ BIEN — específico
resource "google_compute_firewall" "allow_health_checks" {
  name    = "allow-gcp-health-checks"
  network = google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
  source_ranges = [
    "130.211.0.0/22",   # GCP health checkers
    "35.191.0.0/16",
  ]
}
```

### VPC Service Controls

Para datos sensibles (PII, financial), VPC-SC crea un perímetro que evita exfiltración:

```hcl
resource "google_access_context_manager_service_perimeter" "perimeter" {
  parent = "accessPolicies/${var.policy_id}"
  name   = "accessPolicies/${var.policy_id}/servicePerimeters/sensitive_data"
  title  = "Sensitive Data Perimeter"

  status {
    restricted_services = [
      "bigquery.googleapis.com",
      "storage.googleapis.com",
      "secretmanager.googleapis.com",
    ]
    resources = ["projects/${var.project_number}"]
  }
}
```

### Private Google Access + Private Service Connect

```hcl
resource "google_compute_subnetwork" "private" {
  name                     = "private-subnet"
  ip_cidr_range            = "10.0.1.0/24"
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true   # Acceso a APIs de Google sin internet
}
```

---

## Cloud Run en Terraform

```hcl
resource "google_cloud_run_v2_service" "service" {
  name     = var.service_name
  location = "us-east1"
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.svc.email

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = "us-east1-docker.pkg.dev/${var.project}/svcs/${var.service_name}:${var.image_tag}"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_pass.secret_id
            version = "latest"
          }
        }
      }

      ports {
        container_port = 8080
      }
    }
  }
}

# IAM: NO allUsers
# Solo el LB o servicios autorizados
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  location = google_cloud_run_v2_service.service.location
  name     = google_cloud_run_v2_service.service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.lb_invoker.email}"
}
```

---

## Storage (GCS)

```hcl
resource "google_storage_bucket" "data" {
  name          = "cashea-${var.env}-${var.purpose}"
  location      = "US-EAST1"
  storage_class = "STANDARD"

  # Anti acceso público accidental
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  # Versioning para rollback
  versioning {
    enabled = true
  }

  # Lifecycle
  lifecycle_rule {
    condition {
      age = 30  # días
    }
    action {
      type = "Delete"
    }
  }

  # CMEK para datos restringidos
  encryption {
    default_kms_key_name = google_kms_crypto_key.bucket_key.id
  }
}
```

**Reglas:**
- `public_access_prevention = "enforced"` siempre
- `uniform_bucket_level_access = true` siempre (no ACLs por objeto)
- Lifecycle rules para data retention
- CMEK para Restringido

---

## BigQuery

```hcl
resource "google_bigquery_dataset" "ds" {
  dataset_id = "analytics"
  location   = "US"

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.bq_key.id
  }

  default_table_expiration_ms = 7776000000  # 90 días
}

# Access via google_bigquery_dataset_iam_member, no en `access` block del dataset
```

---

## Cloud SQL

```hcl
resource "google_sql_database_instance" "db" {
  name             = "primary-db"
  database_version = "POSTGRES_15"
  region           = "us-east1"

  settings {
    tier              = "db-custom-2-8192"
    availability_type = "REGIONAL"

    # SSL obligatorio
    ip_configuration {
      ipv4_enabled    = false   # NO IP pública
      private_network = google_compute_network.vpc.id
      require_ssl     = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 30
      }
    }
  }

  encryption_key_name = google_kms_crypto_key.db_key.id   # CMEK
  deletion_protection = true
}
```

---

## Scanning de IaC

### En CI

```yaml
# .github/workflows/iac-scan.yml
- name: Checkov scan
  uses: bridgecrewio/checkov-action@master
  with:
    directory: terraform/
    framework: terraform
    soft_fail: false   # bloquea el merge si hay findings
```

Alternativas:
- `tfsec` — focused en security
- `terraform validate` — validación de syntax
- `terraform plan` con review obligatorio

---

## Lo que NUNCA se hace

```
❌ Hardcodear secrets en .tf o .tfvars
❌ Commitear .terraform/ o terraform.tfstate
❌ Usar roles/owner, roles/editor en SA de servicios
❌ Crear google_service_account_key en producción
❌ Firewall rules con source 0.0.0.0/0 sin razón documentada
❌ Buckets / DBs con IPv4 público sin auth
❌ public_access_prevention = "inherited" (debe ser "enforced")
❌ uniform_bucket_level_access = false
❌ allUsers / allAuthenticatedUsers como members
❌ deletion_protection = false en DBs de producción
❌ require_ssl = false en Cloud SQL
❌ Modules pulleando from main sin pinear
❌ State local (sin backend remoto)
```

---

## Checklist al escribir Terraform

```
[ ] State remoto en GCS (con versioning + state locking)
[ ] Secrets vienen de Secret Manager (no en .tf, no en .tfvars commited)
[ ] Cada SA tiene los roles MÍNIMOS scoped al recurso específico
[ ] No roles/owner, roles/editor, roles/viewer en SAs
[ ] Buckets: public_access_prevention=enforced, UBLA=true
[ ] DBs: SSL obligatorio, sin IP pública, CMEK si Restringido
[ ] Cloud Run: ingress internal, no allUsers, SA dedicada
[ ] Firewall rules: deny by default, fuentes específicas
[ ] VPC-SC habilitado para datos sensibles (Restringido)
[ ] Modules pinneados a tag/SHA, no main
[ ] Checkov / tfsec corriendo en CI
[ ] Plan review obligatorio antes de apply
[ ] Apply solo desde CI/CD, nunca desde laptops
```
