# Trend Vision One User Security Dashboard

Proyecto local en Python para integrar TrendAI Vision One en modo read-only y visualizar, por usuario, sus dispositivos relacionados, señales de seguridad, cobertura y telemetría visible.

## Objetivo del proyecto

- Consumir datos de TrendAI Vision One sin ejecutar cambios, remediaciones, aislamiento, respuestas, actualizaciones ni borrados.
- Unificar usuarios, endpoints/devices, señales de riesgo y cobertura visible en un dashboard local.
- Dejar una base modular, mantenible y lista para evolucionar hacia un despliegue productivo.

## Estado actual

- Backend local con FastAPI.
- UI local con Streamlit.
- Caché/persistencia local con SQLite.
- Cliente HTTP desacoplado para Trend Vision One con autenticación Bearer.
- Normalización y correlación usuario-dispositivo.
- Modo demo seguro para levantar la app sin credenciales reales.
- Registro centralizado de endpoints con trazabilidad de verificación.

## Arquitectura

```text
Trend Vision One API (read-only)
        |
        v
  app/clients/trend_vision_one.py
        |
        v
  app/services/ingestion.py
        |
        v
  app/services/normalizer.py
        |
        v
  app/repositories/snapshot_repository.py  --> SQLite local
        |
        +--> FastAPI backend (/api/v1/...)
        |
        +--> Streamlit UI local
```

## Stack elegida

- Backend API: FastAPI
- UI local: Streamlit
- HTTP client: httpx
- Configuración: pydantic-settings
- Reintentos/backoff: tenacity
- Persistencia local: sqlite3 estándar

Se eligió esta stack por simplicidad operativa, facilidad de desarrollo local y buen punto de partida para crecimiento posterior.

## Estructura de carpetas

```text
trend-vision-one-dashboard/
├── app/
│   ├── api/routes/
│   ├── clients/
│   ├── core/
│   ├── data/
│   ├── models/
│   ├── repositories/
│   └── services/
├── data/
├── scripts/
├── tests/
├── ui/
│   └── pages/
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Requisitos

- Python 3.11+
- API key Bearer de Trend Vision One con rol read-only, idealmente tipo Auditor
- Acceso saliente HTTPS hacia el dominio regional configurado

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

El archivo `.env` es cargado automáticamente por `scripts/start_backend.sh` y `scripts/start_ui.sh`.

## Configuración

Toda configuración sensible entra por variables de entorno. No se hardcodean secretos.

### Variables de entorno

| Variable | Descripción | Requerida |
|---|---|---|
| `APP_ENV` | entorno lógico | no |
| `APP_DEBUG` | modo debug | no |
| `APP_DEMO_MODE` | usa snapshot demo si no hay token o endpoints validados | no |
| `APP_BACKEND_HOST` | bind host FastAPI | no |
| `APP_BACKEND_PORT` | puerto FastAPI | no |
| `APP_STREAMLIT_PORT` | puerto Streamlit | no |
| `APP_CACHE_TTL_MINUTES` | TTL del snapshot cacheado | no |
| `APP_DB_PATH` | ruta SQLite local | no |
| `APP_LOG_LEVEL` | nivel de logs | no |
| `APP_REGION` | región lógica (`us`, `eu`, `sg`, etc.) | sí |
| `TREND_VISION_ONE_BASE_URL` | override explícito del dominio regional | no |
| `TREND_VISION_ONE_API_TOKEN` | token Bearer read-only | sí para modo real |
| `TREND_VISION_ONE_TIMEOUT_SECONDS` | timeout por request | no |
| `TREND_VISION_ONE_MAX_RETRIES` | cantidad de reintentos | no |
| `TREND_VISION_ONE_BACKOFF_SECONDS` | backoff base | no |
| `TREND_VISION_ONE_USER_AGENT` | user-agent del cliente | no |
| `TREND_VISION_ONE_DEFAULT_PAGE_SIZE` | page size inicial para endpoints de colección | no |
| `TREND_VISION_ONE_MAX_PAGES` | máximo de páginas por sync | no |
| `TREND_VISION_ONE_USERS_PATH` | override path de usuarios | no |
| `TREND_VISION_ONE_ENDPOINTS_PATH` | override path de endpoint inventory | no |
| `TREND_VISION_ONE_RISK_INSIGHTS_PATH` | override path de risk insights | no |
| `TREND_VISION_ONE_CONNECTED_PRODUCTS_PATH` | override path de connected products | no |
| `TREND_VISION_ONE_WORKBENCH_ALERTS_PATH` | override path de alerts/workbench | no |
| `TREND_VISION_ONE_SEARCH_PATH` | path de search read-only | no |
| `TREND_VISION_ONE_ENDPOINT_INVENTORY_ORDER_BY` | `orderBy` para endpoint inventory | no |
| `TREND_VISION_ONE_ENDPOINT_INVENTORY_SELECT` | `select` para endpoint inventory | no |
| `TREND_VISION_ONE_ENDPOINT_INVENTORY_FILTER` | header `TMV1-Filter` para endpoint inventory | no |

## Cómo ejecutar localmente

### Backend

```bash
./scripts/start_backend.sh
```

### UI

```bash
./scripts/start_ui.sh
```

El script de UI ya desactiva el prompt inicial de Streamlit y toma `BACKEND_URL` automáticamente a partir de `APP_BACKEND_PORT`, salvo que lo overrides manualmente.

Para evitar conflictos locales, `.env.example` deja por defecto el backend en `8001`.

### Sincronización manual

```bash
python scripts/sync_once.py
```

## Endpoints consumidos

La referencia pública offline de Trend Automation Center permitió verificar autenticación Bearer, dominios regionales, límites y el ejemplo exacto `GET /v3.0/workbench/alerts`. Para varias categorías, la referencia interactiva requiere validación adicional en tu tenant/región.

### Endpoints verificados oficialmente

| Feature | Método | Path | Estado |
|---|---|---|---|
| Accounts | `GET` | `/v3.0/accounts` | verificado por input del usuario |
| Account detail | `GET` | `/v3.0/accounts/{accountId}` | verificado por input del usuario |
| Endpoints | `GET` | `/v3.0/endpointSecurity/endpoints` | verificado por input del usuario y respuesta real `400` |
| Endpoint detail | `GET` | `/v3.0/endpoints/{endpointId}` | verificado por input del usuario |
| Workbench Alerts | `GET` | `/v3.0/workbench/alerts` | verificado en guía de autenticación |
| Search | `POST` | `/v3.0/search` | verificado por input del usuario, uso read-only |

### Categorías confirmadas por documentación, pero path exacto pendiente de validar en API Reference interactiva

| Feature | Categoría doc | Path por defecto en este proyecto |
|---|---|---|
| Accounts / Users detail enrichment | Accounts | `/v3.0/accounts` y detalle por id ya fijados |
| Search / Endpoint Inventory detail enrichment | Search / Endpoint Inventory | `/v3.0/endpointSecurity/endpoints` confirmado; faltan params/header exactos |
| Risk Insights | Risk Insights | vacío, configurable por env |
| Connected Products | Connected Products | vacío, configurable por env |

### Qué endpoint usa cada pantalla o feature

| Pantalla/feature | Fuente |
|---|---|
| Home | snapshot normalizado almacenado localmente |
| Users list | snapshot normalizado almacenado localmente |
| User detail | snapshot normalizado almacenado localmente |
| Sync status | tabla local de snapshots |
| Risk summary | `risk_insights` si está configurado; si no, señales derivadas de alerts/demo |
| Device coverage | `endpoint_inventory` y `connected_products` si están configurados |
| Alerts context | `workbench_alerts` |
| Advanced correlation | `search` read-only por `POST /v3.0/search` |

## Modelo de datos

El dashboard usa un modelo interno normalizado:

- `UserRecord`: identidad principal del usuario
- `DeviceRecord`: endpoint/device visible
- `SignalRecord`: alertas o señales asociadas a usuario o dispositivo
- `CoverageRecord`: productos/capacidades/cobertura visible por device o usuario
- `CorrelationLink`: vínculo usuario-dispositivo con `deterministic` o `inferred`
- `DashboardSnapshot`: snapshot completo persistido

## Correlación usuario-dispositivo

- Determinística si hay match por `user_id`, `account_id`, `email` o `owner`.
- Inferida si el match surge de campos parciales o listas de usuarios asociados.
- Mientras el endpoint `Accounts` siga pendiente de validación final, el dashboard puede crear usuarios inferidos a partir de `lastLoggedOnUser` y otros campos de Endpoint Inventory.
- Si no puede inferirse de forma confiable, la relación queda sin vincular y se documenta como tal.

## Decisiones técnicas

- No se implementan métodos `POST`, `PATCH`, `PUT` ni `DELETE` hacia Trend Vision One.
- Los endpoints se centralizan en un único módulo con estado de verificación.
- El sistema tolera respuestas parciales e incompletas.
- El cliente soporta paginación de colecciones con `nextLink`, cursor y patrones comunes `top/skip`, `limit/offset`, `page`.
- Endpoint Inventory ya aporta usuarios inferidos, último usuario logueado, IP visible y cobertura derivada de `eppAgent.productNames`.
- Se evita exponer secretos en logs.
- Se agrega caché local para reducir carga y dependencia de red.
- El frontend consume solo el backend local, no la API externa directamente.

## Limitaciones

- Los paths exactos de varias categorías dependen de validación contra la API Reference interactiva oficial de Trend Vision One para la región/tenant configurados.
- El normalizador usa extractores tolerantes porque los esquemas exactos pueden variar entre endpoints.
- El dashboard no intenta resolver relaciones imposibles de probar con datos incompletos.

## Roadmap

- Validar y fijar los paths exactos de `accounts`, `endpoint inventory`, `risk insights` y `connected products`.
- Añadir refresh programado.
- Incorporar autenticación local para el dashboard.
- Preparar empaquetado para despliegue productivo.

## Troubleshooting

- Si ves `Feature unavailable`, revisá el path correspondiente en `.env`.
- Si la API responde `401`, el token es inválido o expiró.
- Si responde `403`, el rol no tiene permisos de lectura suficientes.
- Si responde `429`, el cliente reintenta con backoff y respeta `Retry-After` cuando existe.
- Si no configurás token y `APP_DEMO_MODE=true`, la app cae en modo demo.

## Consideraciones de seguridad

- No hardcodear secretos, dominios específicos de tenant ni credenciales.
- Usar una API key read-only y principio de mínimo privilegio.
- No ejecutar acciones de respuesta ni modificación.
- Sanitizar y escapar texto mostrado en UI.
- Manejar timeouts, reintentos y errores parciales.
- No registrar tokens ni payloads sensibles completos.

## Referencias oficiales utilizadas

- Regional domains: `https://automation.trendmicro.com/xdr/Guides/Regional-domains/`
- Authentication: `https://automation.trendmicro.com/xdr/Guides/Authentication/`
- Resource types: `https://automation.trendmicro.com/xdr/Guides/Resource-types/`
- API request limits: `https://automation.trendmicro.com/xdr/Guides/API-Request-Limits/`
- Versioning/deprecation: `https://automation.trendmicro.com/xdr/Guides/Versioning-and-deprecation/`
