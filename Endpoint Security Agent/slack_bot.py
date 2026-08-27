"""
Slack Bot — Endpoint Security Agent
Escucha mensajes directos via Socket Mode.
Usa Claude para entender lenguaje natural y decidir qué acción ejecutar.
"""
import os
import sys
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Historial de conversación por canal (últimos 20 turnos)
conversation_history: dict[str, list] = {}
MAX_HISTORY = 20

TREND_BASE = "https://api.xdr.trendmicro.com"

TOOLS = [
    {
        "name": "generar_reporte",
        "description": (
            "Genera un reporte de seguridad de endpoints y lo sube como archivo Excel. "
            "Usá esta herramienta cuando el usuario pida cualquiera de estos reportes:\n"
            "- 'qué máquinas hay en Trend que no están en JumpCloud', 'lanzá el reporte trend not in jumpcloud', "
            "'máquinas en Trend sin JumpCloud', 'reporte de Trend vs JumpCloud' → tipo=macs_sin_trend\n"
            "- 'qué máquinas están en JumpCloud sin Trend', 'laptops sin agente Trend', 'reporte jumpcloud sin trend' → tipo=jumpcloud_sin_trend\n"
            "- 'laptops sin owner', 'laptops sin usuario asignado' → tipo=laptops_sin_owner\n"
            "- 'endpoints sin conexión', 'máquinas offline en Trend' → tipo=endpoints_sin_conexion\n"
            "También usala cuando el usuario pida 'los reportes de los lunes' o 'los reportes semanales' para generar todos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": ["macs_sin_trend", "jumpcloud_sin_trend", "laptops_sin_owner", "endpoints_sin_conexion"],
                    "description": (
                        "macs_sin_trend = endpoints en Trend que NO existen en JumpCloud (máquinas eliminadas de JC pero no de Trend); "
                        "jumpcloud_sin_trend = máquinas en JumpCloud sin agente Trend instalado; "
                        "laptops_sin_owner = Laptops con estado In Use sin owner asignado; "
                        "endpoints_sin_conexion = Endpoints en Trend sin conexión hace +10 días."
                    ),
                }
            },
            "required": ["tipo"],
        },
    },
    {
        "name": "consultar_software",
        "description": "Consulta la versión de cualquier software instalado en una o varias máquinas via JumpCloud System Insights (Chrome, Office, cualquier app).",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
                "app_name": {"type": "string", "description": "Nombre de la app, ej: 'Google Chrome'."},
            },
            "required": ["hostnames", "app_name"],
        },
    },
    {
        "name": "consultar_usuario",
        "description": "Consulta qué usuario tiene asignado uno o varios equipos en JumpCloud. Excluye adminit@cashea.app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["hostnames"],
        },
    },
    {
        "name": "trend_vulnerabilidades",
        "description": "Muestra los CVEs detectados en un equipo específico según Trend Vision One Vulnerability Management. Dado un hostname, devuelve la lista de CVEs con severidad, componente afectado y score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostname": {"type": "string", "description": "Nombre del equipo, ej: DESKTOP-06DBPH7"},
            },
            "required": ["hostname"],
        },
    },
    {
        "name": "verificar_parches",
        "description": "Verifica parches instalados en equipos Windows via JumpCloud System Insights. Puede buscar por número de KB (ej: KB5101650) o por mes (ej: 2026-07). Usá kb_id para buscar un parche específico, mes para listar todos los parches de un mes. Al menos uno de los dos es requerido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
                "mes": {"type": "string", "description": "Mes en formato YYYY-MM, ej: '2026-07'. Opcional si se especifica kb_id."},
                "kb_id": {"type": "string", "description": "Número de KB a buscar, ej: 'KB5101650'. Opcional si se especifica mes."},
            },
            "required": ["hostnames"],
        },
    },
    {
        "name": "enviar_comando",
        "description": "Envía un comando existente de JumpCloud (por su command_id) a una lista de equipos (por hostname). El comando debe existir previamente en JumpCloud.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command_id": {
                    "type": "string",
                    "description": "ID del comando en JumpCloud, ej: 6a21e3468cdfa30d628c2e39",
                },
                "hostnames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de hostnames a los que enviar el comando.",
                },
            },
            "required": ["command_id", "hostnames"],
        },
    },
    {
        "name": "matchear_equipos",
        "description": "Compara una lista de hostnames con JumpCloud/Trend y devuelve cuáles cumplen cierto criterio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
                "criterio": {
                    "type": "string",
                    "enum": ["sin_trend", "sin_usuario", "no_en_jumpcloud"],
                },
            },
            "required": ["hostnames", "criterio"],
        },
    },
    {
        "name": "jc_estadisticas",
        "description": "Devuelve estadísticas generales del inventario de JumpCloud: total de equipos, activos, con usuario asignado, por OS, etc. Usá esta herramienta cuando pregunten por conteos, totales o resúmenes del inventario.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "jc_estado_equipo",
        "description": "Muestra el estado de un equipo en JumpCloud: online/offline, último check-in, OS, versión, disk encryption.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["hostnames"],
        },
    },
    {
        "name": "jc_equipos_sin_conexion",
        "description": "Lista equipos de JumpCloud que no se conectaron hace más de N días.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {"type": "integer", "description": "Cantidad de días sin conexión, ej: 7"},
                "solo_macs": {"type": "boolean", "description": "Si true, solo devuelve Macs."},
            },
            "required": ["dias"],
        },
    },
    {
        "name": "buscar_hostname",
        "description": "Busca un equipo en JumpCloud por nombre parcial o por nombre/apellido del usuario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nombre parcial del hostname, o nombre/apellido del usuario, ej: 'garcia' o 'CASHEA-MAC-CK'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "trend_alertas",
        "description": "Trae alertas de seguridad de Trend Vision One (workbench alerts) de las últimas N horas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "horas": {"type": "integer", "description": "Últimas N horas a consultar, ej: 24"},
            },
            "required": ["horas"],
        },
    },
    {
        "name": "trend_estado_endpoint",
        "description": "Muestra el estado de un endpoint en Trend Vision One: conectado, última conexión, nivel de riesgo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostnames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["hostnames"],
        },
    },
    {
        "name": "checklist_onboarding",
        "description": "Verifica el checklist de onboarding para un usuario nuevo: equipo asignado en JumpCloud, Trend instalado, conexión reciente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email del usuario nuevo, ej: nuevousuario@cashea.app"},
            },
            "required": ["email"],
        },
    },
    {
        "name": "monitorear_cloudflare",
        "description": (
            "Inicia el monitoreo de resultados del comando 'Cloudflare Install' (ID: 6a4e5b318cf704c8149dbdf9) "
            "en JumpCloud. Hace polling cada 30 segundos y escribe los resultados en un Excel en /reports/. "
            "Usá esta herramienta cuando el usuario diga que va a lanzar o ya lanzó ese comando y quiere monitorear los resultados."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "lanzar_script_matches",
        "description": (
            "Ejecuta el script de matches JumpCloud vs Trend Vision One y sube el reporte .xls al chat. "
            "Usá esta herramienta cuando el usuario diga 'lanza el script de matches', 'genera el reporte de matches', "
            "'corré el script de matches', 'reporte de matches', 'matches de JumpCloud y Trend', "
            "'qué máquinas están en los dos sistemas', 'cruzá JumpCloud con Trend' o similar."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detener_monitoreo_cloudflare",
        "description": (
            "Detiene el monitoreo activo de Cloudflare Install. "
            "Usá esta herramienta cuando el usuario diga 'detené el monitoreo', 'pará de monitorear', 'deja de monitorear Cloudflare' o similar."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "monitorear_cve",
        "description": (
            "Inicia el monitoreo de resultados del comando CVE-2026-50390 (ID: 6a7cb67afa053a5729c59c4e) "
            "en JumpCloud. Hace polling cada 30 segundos y escribe hostname y status en un Excel en /reports/. "
            "Usá esta herramienta cuando el usuario diga que va a lanzar o ya lanzó ese comando y quiere monitorear los resultados de la remediación del CVE."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "detener_monitoreo_cve",
        "description": (
            "Detiene el monitoreo activo del CVE-2026-50390. "
            "Usá esta herramienta cuando el usuario diga 'detené el monitoreo del CVE', 'pará de monitorear el CVE' o similar."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "generar_script",
        "description": (
            "Genera un script (bash, python o powershell) a partir de una descripción en lenguaje natural. "
            "Usá esta herramienta cuando el usuario pida crear, escribir o armar un script o comando. "
            "Devuelve el script como archivo .txt adjunto en Slack."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "descripcion": {
                    "type": "string",
                    "description": "Qué debe hacer el script, con todos los detalles que dio el usuario.",
                },
                "lenguaje": {
                    "type": "string",
                    "enum": ["bash", "python", "powershell"],
                    "description": "Lenguaje del script. Si el usuario no especificó, inferilo del contexto (bash para Mac/Linux, powershell para Windows, python si es más complejo).",
                },
            },
            "required": ["descripcion", "lenguaje"],
        },
    },
]

REPORT_MAP = {
    "macs_sin_trend":         ("scripts/report_trend_not_in_jumpcloud.py",  "trend_not_in_jumpcloud"),
    "jumpcloud_sin_trend":    ("scripts/report_jumpcloud_not_in_trend.py",  "jumpcloud_not_in_trend"),
    "laptops_sin_owner":      ("scripts/report_laptops_sin_owner.py",       "laptops_in_use_sin_owner"),
    "endpoints_sin_conexion": ("scripts/report_trend_sin_conexion.py",      "trend_endpoints_sin_conexion_10d"),
}

SYSTEM_PROMPT = """Sos el Endpoint Security Agent de Cashea, un asistente de seguridad IT con acceso completo a JumpCloud y Trend Vision One.

## Capacidades

### Reportes (generar_reporte):
- Macs sin Trend, JumpCloud sin Trend, Laptops sin owner, Endpoints sin conexión
- Se generan automáticamente cada lunes a las 10 AM (GMT-3)
- También se pueden pedir en cualquier momento con frases como "lanzá el reporte de trend not in jumpcloud", "qué máquinas hay en Trend que no están en JumpCloud", "los reportes de los lunes", etc.
- Si el usuario pide "los reportes de los lunes" o "todos los reportes semanales", generá los 4 tipos en secuencia.

### Software instalado (consultar_software):
- Versión de cualquier app en Mac (System Insights apps) o Windows (programs)
- SIEMPRE usá esta herramienta cuando pregunten por versiones

### Usuarios y equipos:
- consultar_usuario: hostname → usuario asignado
- buscar_hostname: búsqueda por hostname parcial, nombre o email del usuario
- Excluir siempre adminit@cashea.app

### Estadísticas JumpCloud (jc_estadisticas):
- Total de equipos, activos, inactivos, por OS, con/sin usuario asignado
- Usá esta herramienta ante cualquier pregunta de conteo o resumen: "cuántas máquinas hay", "cuántas activas", "cuántas tienen usuario", etc.

### Estado JumpCloud (jc_estado_equipo):
- Online/offline, último check-in, OS, versión, disk encryption

### Equipos sin conexión (jc_equipos_sin_conexion):
- Lista equipos que no se conectaron en los últimos N días

### Parches Windows (verificar_parches):
- Buscar por KB específico (ej: KB5101650) o por mes (ej: 2026-07)
- kb_id y mes son opcionales pero al menos uno es requerido

### Comandos remotos (enviar_comando):
- Recibe un command_id de JumpCloud y una lista de hostnames
- Asocia los sistemas al comando y lo ejecuta via /api/runCommand
- El comando debe existir previamente en JumpCloud

### Comparar listas (matchear_equipos):
- Encuentra equipos sin Trend, sin usuario, o que no están en JumpCloud

### Trend Vision One:
- trend_alertas: workbench alerts (incidentes/detecciones de seguridad) con severidad LOW/MEDIUM/HIGH/CRITICAL. Usá esta herramienta cuando pregunten por alertas, incidentes, detecciones, o cuando quieran investigar una alerta específica por severidad. Si el usuario dice "investiga la HIGH" o "dame más info de la alerta HIGH", llamá trend_alertas con las últimas horas relevantes.
- trend_estado_endpoint: estado de conexión y nivel de riesgo de un endpoint específico por hostname. Usá esta cuando pregunten por el estado de una máquina puntual.
- trend_vulnerabilidades: lista los CVEs detectados en un equipo específico con severidad, CVSS score y componente afectado. Usá cuando pregunten qué vulnerabilidades tiene una máquina.

### Onboarding / Offboarding:
- checklist_onboarding: verifica equipo asignado + Trend instalado + conexión reciente

### Script de matches JumpCloud ↔ Trend (lanzar_script_matches):
- Ejecuta el script de matches y sube el reporte .xls al chat
- Usá cuando el usuario diga "lanza el script de matches", "generá el reporte de matches" o similar

### Monitoreo de comandos JumpCloud (monitorear_cloudflare):
- Monitorea los resultados del comando "Cloudflare Install" (ID: 6a4e5b318cf704c8149dbdf9) en tiempo real
- Hace polling cada 30 segundos y escribe los resultados en un Excel en /reports/
- Usá esta herramienta cuando el usuario diga que va a lanzar o ya lanzó ese comando

### Scripts (generar_script):
- Escribe un script bash, python o powershell según lo que pida el usuario
- Lo sube como archivo .txt al chat
- Usá esta herramienta cuando pidan "escribime un script", "haceme un script que...", "armame un comando para..."

## Contexto de Cashea
- Macs: CASHEA-MAC-XXXXXXXXXX | Windows: DESKTOP-XXXXXXX o LAPTOP-XXXXXXX
- Admin genérico: adminit@cashea.app (siempre excluir)
- ~1100+ sistemas en JumpCloud, ~300+ Macs

## Troubleshooting guiado
Cuando el usuario pida ayuda con un problema (lentitud, conectividad, agente caído, disco lleno, etc.):
1. Entendé el problema y preguntá lo mínimo necesario si falta contexto (OS, hostname, síntoma exacto).
2. Guiá paso a paso: generá UN script por vez con `generar_script`, explicá en 1-2 líneas qué hace y qué debe mirar el usuario en el resultado.
3. Esperá que el usuario te cuente qué devolvió el script antes de dar el siguiente paso.
4. Adaptá el diagnóstico según lo que te reportan — no des todos los pasos de una.
5. Cuando identifiques la causa, generá el script de remediación.
Ejemplos: "el agente de JumpCloud no conecta", "el equipo está lento", "Trend no reporta", "hay poco espacio en disco", "Chrome no actualiza".

## Instrucciones
- Respondé en español, conciso y profesional
- NUNCA digas que no podés hacer algo que está en tus capacidades
- Usá siempre la herramienta más específica para cada consulta
- En troubleshooting: UN script por vez, esperá el resultado antes de continuar
- Si el usuario pide algo que no está dentro de tus capacidades y no tenés una herramienta para resolverlo, respondé EXACTAMENTE: "No estoy autorizado a realizar esa tarea." Sin explicaciones adicionales."""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_jc_headers():
    return {"x-api-key": os.environ.get("JUMPCLOUD_API_KEY", "").strip(), "Accept": "application/json"}

def get_trend_headers():
    token = os.environ.get("TREND_VISION_ONE_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def get_systems_map(hostnames: list) -> dict:
    targets = {h.upper(): h for h in hostnames}
    systems = {}
    skip = 0
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        for s in items:
            hn = s.get("hostname", "").upper()
            if hn in targets:
                systems[targets[hn]] = {"id": s["_id"], "os": s.get("osFamily", "").lower()}
        if len(targets) == len(systems) or len(items) < 100:
            break
        skip += 100
    return systems

_trend_cache: dict = {"endpoints": [], "ts": 0.0}
_trend_cache_lock = threading.Lock()
_TREND_CACHE_TTL = 300  # 5 minutos

def _refresh_trend_cache():
    """Pagina todos los endpoints de Trend usando skipToken del nextLink."""
    endpoints = []
    # Primera página con top=200
    url = f"{TREND_BASE}/v3.0/endpointSecurity/endpoints"
    first = True
    try:
        while url:
            if first:
                r = httpx.get(url, headers=get_trend_headers(), params={"top": 200}, timeout=30)
                first = False
            else:
                # Llamar nextLink directo — ya lleva skipToken en la URL
                r = httpx.get(url, headers=get_trend_headers(), timeout=30)
            if not r.is_success:
                print(f"[trend_cache] HTTP {r.status_code}: {r.text[:100]}", flush=True)
                break
            data = r.json()
            items = data.get("items", [])
            if not items:
                break
            endpoints.extend(items)
            url = data.get("nextLink")
            print(f"[trend_cache] +{len(items)} | total={len(endpoints)}", flush=True)
    except Exception as e:
        print(f"[trend_cache] error: {e}", flush=True)
    if endpoints:
        with _trend_cache_lock:
            _trend_cache["endpoints"] = endpoints
            _trend_cache["ts"] = time.time()
        print(f"[trend_cache] listo: {len(endpoints)} endpoints", flush=True)

def _trend_cache_loop():
    """Refresca el cache de Trend cada 5 minutos en background."""
    while True:
        _refresh_trend_cache()
        time.sleep(_TREND_CACHE_TTL)

def get_all_trend_endpoints() -> list:
    """Devuelve el cache de endpoints de Trend (puede estar vacío si aún no cargó)."""
    with _trend_cache_lock:
        return list(_trend_cache["endpoints"])

def get_trend_endpoints(filter_str: str = None, top: int = 200) -> list:
    """Devuelve endpoints del cache. filter_str ignorado (la API no soporta filtros GET)."""
    return get_all_trend_endpoints()


# ─── Tool implementations ──────────────────────────────────────────────────────

def consultar_software(hostnames: list, app_name: str) -> str:
    systems = get_systems_map(hostnames)
    if not systems:
        return "No se encontró ninguna de las máquinas en JumpCloud."
    app_lower = app_name.lower()

    def get_version(hostname, info):
        sid = info["id"]
        is_mac = "darwin" in info["os"] or "mac" in hostname.lower()
        version = None
        if is_mac:
            skip2 = 0
            while True:
                r = httpx.get("https://console.jumpcloud.com/api/v2/systeminsights/apps",
                    headers=get_jc_headers(),
                    params={"limit": 100, "skip": skip2, "filter": f"system_id:eq:{sid}"}, timeout=20)
                apps = r.json() if isinstance(r.json(), list) else []
                if not apps:
                    break
                for a in apps:
                    if a.get("system_id") != sid:
                        continue
                    bundle_id = (a.get("bundle_identifier") or "").lower()
                    display = (a.get("display_name") or a.get("bundle_name") or "").lower()
                    is_match = bundle_id == "com.google.chrome" or all(w in display for w in app_lower.split())
                    if is_match and "alertnotification" not in bundle_id:
                        if bundle_id == "com.google.chrome":
                            version = a.get("bundle_short_version")
                            break
                        elif not version:
                            version = a.get("bundle_short_version")
                if version or len(apps) < 100:
                    break
                skip2 += 100
        else:
            skip2 = 0
            while True:
                r = httpx.get("https://console.jumpcloud.com/api/v2/systeminsights/programs",
                    headers=get_jc_headers(),
                    params={"limit": 100, "skip": skip2, "filter": f"system_id:eq:{sid}"}, timeout=20)
                progs = r.json() if isinstance(r.json(), list) else []
                if not progs:
                    break
                for p in progs:
                    if p.get("system_id") != sid:
                        continue
                    if app_lower in p.get("name", "").lower():
                        version = p.get("version")
                        break
                if version or len(progs) < 100:
                    break
                skip2 += 100
        return hostname, version

    with ThreadPoolExecutor(max_workers=10) as ex:
        version_map = {hn: ver for hn, ver in (f.result() for f in as_completed(
            {ex.submit(get_version, hn, info): hn for hn, info in systems.items()}))}

    return "\n".join(
        f"{hn}: No está en JumpCloud" if hn not in systems
        else f"{hn}: {version_map.get(hn) or 'No encontrado'}"
        for hn in hostnames
    )


def consultar_usuario(hostnames: list) -> str:
    systems = get_systems_map(hostnames)

    def get_user(hostname, info):
        sid = info["id"]
        try:
            r = httpx.get(f"https://console.jumpcloud.com/api/v2/systems/{sid}/users",
                headers=get_jc_headers(), params={"limit": 10}, timeout=15)
            users = r.json() if isinstance(r.json(), list) else []
            emails = []
            for u in users:
                r2 = httpx.get(f"https://console.jumpcloud.com/api/systemusers/{u['id']}",
                    headers=get_jc_headers(), timeout=15)
                email = r2.json().get("email", "")
                if email.lower() != "adminit@cashea.app":
                    emails.append(email)
            return hostname, emails
        except Exception:
            return hostname, []

    with ThreadPoolExecutor(max_workers=10) as ex:
        user_map = {hn: emails for hn, emails in (f.result() for f in as_completed(
            {ex.submit(get_user, hn, info): hn for hn, info in systems.items()}))}

    return "\n".join(
        f"{hn}: No está en JumpCloud" if hn not in systems
        else f"{hn}: {', '.join(user_map.get(hn, [])) or 'Sin usuario asignado'}"
        for hn in hostnames
    )



def trend_vulnerabilidades(hostname: str) -> str:
    hn_upper = hostname.upper()
    all_items = []
    url = f"{TREND_BASE}/v3.0/asrm/vulnerableDevices"
    while url:
        r = httpx.get(url, headers=get_trend_headers(), timeout=30)
        if not r.is_success:
            return f"❌ Error al consultar Trend: {r.status_code}"
        data = r.json()
        all_items.extend(data.get("items", []))
        url = data.get("nextLink")

    device = next((d for d in all_items if d.get("deviceName", "").upper() == hn_upper), None)
    if not device:
        return f"❌ {hostname}: no encontrado en Trend Vulnerability Management."

    cves = device.get("cveRecords", [])
    if not cves:
        return f"✅ {hostname}: sin CVEs detectados en Trend."

    def cvss_level(score):
        try:
            s = float(score)
            if s >= 9.0: return "critical", "🔴"
            if s >= 7.0: return "high", "🟠"
            if s >= 4.0: return "medium", "🟡"
            return "low", "🟢"
        except Exception:
            return "unknown", "⚪"

    cves_sorted = sorted(cves, key=lambda c: -(float(c.get("cvssScore") or 0)))
    lines = [f"*{hostname}* — {len(cves)} CVE(s) detectado(s):\n"]
    for c in cves_sorted:
        cve_id = c.get("id", "N/A")
        score = c.get("cvssScore", "N/A")
        level, icon = cvss_level(score)
        components = ", ".join(c.get("affectedComponents", [])) or "N/A"
        mitigation = c.get("mitigationStatus", "")
        mit_tag = " _(cerrado)_" if mitigation == "closed" else ""
        lines.append(f"{icon} *{cve_id}* — {level.upper()} (CVSS {score}) — {components}{mit_tag}")

    return "\n".join(lines)


def verificar_parches(hostnames: list, mes: str = None, kb_id: str = None) -> str:
    if not mes and not kb_id:
        return "⚠️ Especificá un mes (ej: 2026-07) o un número de KB (ej: KB5101650)."
    MAX_HOSTS = 50
    if len(hostnames) > MAX_HOSTS:
        return f"⚠️ Demasiadas máquinas ({len(hostnames)}). Máximo permitido: {MAX_HOSTS}. Dividí la lista en grupos más chicos."
    systems = get_systems_map(hostnames)
    kb_upper = kb_id.upper() if kb_id else None

    def check_patches(hostname):
        if hostname not in systems:
            return hostname, None
        sid = systems[hostname]["id"]
        found = []
        skip2 = 0
        while True:
            r = httpx.get("https://console.jumpcloud.com/api/v2/systeminsights/patches",
                headers=get_jc_headers(),
                params={"limit": 100, "skip": skip2, "filter": f"system_id:eq:{sid}"}, timeout=20)
            items = r.json() if isinstance(r.json(), list) else []
            if not items:
                break
            for p in items:
                if p.get("system_id") != sid:
                    continue
                hotfix = p.get("hotfix_id", "").upper()
                installed_raw = p.get("installed_on", "") or ""
                # Normalizar M/D/YYYY → YYYY-MM
                try:
                    parts = installed_raw.strip().split("/")
                    installed_ym = f"{parts[2]}-{int(parts[0]):02d}" if len(parts) == 3 else installed_raw[:7]
                except Exception:
                    installed_ym = installed_raw[:7]

                if kb_upper:
                    if hotfix == kb_upper:
                        found.append({"kb": hotfix, "fecha": installed_raw, "desc": p.get("description", "")})
                elif mes:
                    if installed_ym == mes:
                        found.append({"kb": hotfix, "fecha": installed_raw, "desc": p.get("description", "")})
            if len(items) < 100:
                break
            skip2 += 100
        return hostname, found

    with ThreadPoolExecutor(max_workers=20) as ex:
        patch_map = dict(f.result() for f in as_completed(
            [ex.submit(check_patches, hn) for hn in hostnames]))

    results = []
    for hn in hostnames:
        data = patch_map.get(hn)
        if data is None:
            results.append(f"❓ {hn}: No está en JumpCloud")
        elif not data:
            label = kb_upper if kb_upper else f"parches de {mes}"
            results.append(f"❌ {hn}: {label} no encontrado")
        else:
            if kb_upper:
                p = data[0]
                results.append(f"✅ {hn}: {p['kb']} instalado el {p['fecha']} ({p['desc']})")
            else:
                kbs = ", ".join(d["kb"] for d in data)
                results.append(f"✅ {hn}: {len(data)} parche(s) en {mes} — {kbs}")
    return "\n".join(results)


def enviar_comando(command_id: str, hostnames: list) -> str:
    """Asocia el command_id a los sistemas dados y lo ejecuta via /api/runCommand."""
    systems = get_systems_map(hostnames)
    if not systems:
        return "No se encontró ninguna de las máquinas en JumpCloud."

    not_found = [h for h in hostnames if h not in systems]
    system_ids = [info["id"] for info in systems.values()]

    h = {**get_jc_headers(), "Content-Type": "application/json"}

    # Obtener el nombre del comando para mostrarlo
    cmd_info_r = httpx.get(f"https://console.jumpcloud.com/api/commands/{command_id}",
        headers=h, timeout=15)
    cmd_name = cmd_info_r.json().get("name", command_id) if cmd_info_r.is_success else command_id

    def associate_and_run(sid):
        httpx.post(
            f"https://console.jumpcloud.com/api/v2/commands/{command_id}/associations",
            headers=h,
            json={"op": "add", "type": "system", "id": sid},
            timeout=15,
        )

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(associate_and_run, system_ids))

    # Ejecutar el comando
    run_r = httpx.post(
        "https://console.jumpcloud.com/api/runCommand",
        headers=h,
        json={"_id": command_id},
        timeout=15,
    )

    if not run_r.is_success:
        return f"Error al ejecutar el comando: {run_r.status_code} {run_r.text}"

    lines = [f"Comando *{cmd_name}* (`{command_id}`) enviado a {len(system_ids)} equipo(s):"]
    for hn in systems:
        lines.append(f"  ✓ {hn}")
    if not_found:
        lines.append(f"\nNo encontrados en JumpCloud: {', '.join(not_found)}")
    return "\n".join(lines)


def matchear_equipos(hostnames: list, criterio: str) -> str:
    systems = get_systems_map(hostnames)

    if criterio == "no_en_jumpcloud":
        faltantes = [h for h in hostnames if h not in systems]
        return (f"Equipos NO en JumpCloud ({len(faltantes)}):\n" + "\n".join(faltantes)) if faltantes else "Todos están en JumpCloud."

    if criterio == "sin_usuario":
        def check_has_user(hn_info):
            hn, info = hn_info
            sid = info["id"]
            r = httpx.get(f"https://console.jumpcloud.com/api/v2/systems/{sid}/users",
                headers=get_jc_headers(), params={"limit": 10}, timeout=15)
            raw = r.json() if isinstance(r.json(), list) else []
            real_users = []
            for u in raw:
                ud = httpx.get(f"https://console.jumpcloud.com/api/systemusers/{u['id']}",
                    headers=get_jc_headers(), timeout=15).json()
                if ud.get("email", "").lower() != "adminit@cashea.app":
                    real_users.append(u)
            return hn if not real_users else None

        with ThreadPoolExecutor(max_workers=10) as ex:
            results_raw = list(ex.map(check_has_user, systems.items()))
        sin_user = [r for r in results_raw if r]
        return (f"Sin usuario ({len(sin_user)}):\n" + "\n".join(sin_user)) if sin_user else "Todos tienen usuario asignado."

    if criterio == "sin_trend":
        trend_names = {ep.get("endpointName", "").upper() for ep in get_all_trend_endpoints()}
        sin_trend = [h for h in hostnames if h.upper() not in trend_names]
        return (f"Sin Trend ({len(sin_trend)}):\n" + "\n".join(sin_trend)) if sin_trend else "Todos tienen Trend instalado."

    return "Criterio no reconocido."


def jc_estadisticas() -> str:
    all_systems = []
    skip = 0
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        all_systems.extend(items)
        if len(items) < 100:
            break
        skip += 100

    total = len(all_systems)
    activos = sum(1 for s in all_systems if s.get("active"))
    por_os: dict[str, int] = {}
    con_primary = 0
    sin_primary = 0

    for s in all_systems:
        os_fam = (s.get("osFamily") or "Unknown").capitalize()
        por_os[os_fam] = por_os.get(os_fam, 0) + 1
        if s.get("primarySystemUser"):
            con_primary += 1
        else:
            sin_primary += 1

    # Solo macOS y Windows (excluir otros)
    mac_count = por_os.get("Darwin", 0)
    win_count = por_os.get("Windows", 0)

    # Con primary user en macOS/Windows activos
    mac_win_activos = [s for s in all_systems if s.get("active") and s.get("osFamily", "").lower() in ("darwin", "windows")]
    mac_win_con = sum(1 for s in mac_win_activos if s.get("primarySystemUser"))
    mac_win_sin = len(mac_win_activos) - mac_win_con

    # Por OS con/sin Primary User (total, sin importar activo/inactivo)
    darwin  = [s for s in all_systems if s.get("osFamily","").lower() == "darwin"]
    windows = [s for s in all_systems if s.get("osFamily","").lower() == "windows"]
    otros   = [s for s in all_systems if s.get("osFamily","").lower() not in ("darwin","windows")]

    def resumen_os(lista):
        con = sum(1 for s in lista if s.get("primarySystemUser"))
        sin = len(lista) - con
        return len(lista), con, sin

    mac_total, mac_con, mac_sin = resumen_os(darwin)
    win_total, win_con, win_sin = resumen_os(windows)
    otros_total, otros_con, otros_sin = resumen_os(otros)
    total_con = mac_con + win_con + otros_con
    total_sin = mac_sin + win_sin + otros_sin

    sin_primary_nombres = [s.get("hostname","") for s in all_systems if not s.get("primarySystemUser")]

    lines = [
        "*Inventario JumpCloud — Devices*",
        f"_(filtro: macOS + Windows, Primary User: Assigned — igual que la consola)_\n",
        f"✅ *macOS + Windows con usuario asignado: {mac_con + win_con}*",
        "",
        "*Desglose:*",
        f"  🍎 macOS:   {mac_total} registrados → *{mac_con} con usuario*, {mac_sin} sin usuario",
        f"  🪟 Windows: {win_total} registrados → *{win_con} con usuario*, {win_sin} sin usuario",
        "",
        f"📦 Total general JumpCloud (todos los OS): {total}",
    ]
    if otros_total:
        lines.append(f"  🖥️ Otros (Linux/etc.): {otros_total} → {otros_con} con usuario, {otros_sin} sin usuario")
    if sin_primary_nombres:
        lines.append(f"\n⚠️ Sin Primary User ({total_sin}): {', '.join(sin_primary_nombres)}")
    return "\n".join(lines)


def jc_estado_equipo(hostnames: list) -> str:
    systems_raw = {}
    skip = 0
    targets = {h.upper() for h in hostnames}
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        for s in items:
            hn = s.get("hostname", "").upper()
            if hn in targets:
                systems_raw[s.get("hostname")] = s
        if len(systems_raw) == len(targets) or len(items) < 100:
            break
        skip += 100

    def fetch_host_info(hn_orig):
        s = systems_raw.get(hn_orig) or systems_raw.get(hn_orig.upper())
        if not s:
            return f"*{hn_orig}*: No está en JumpCloud"

        last_contact = s.get("lastContact", "")
        if last_contact:
            try:
                dt = datetime.fromisoformat(last_contact.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - dt
                ago = f"hace {delta.days}d {delta.seconds // 3600}h" if delta.days else f"hace {delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
                last_contact_str = f"{dt.strftime('%Y-%m-%d %H:%M')} UTC ({ago})"
            except Exception:
                last_contact_str = last_contact
        else:
            last_contact_str = "Nunca"

        active = "🟢 Online" if s.get("active") else "🔴 Offline"
        os_name = f"{s.get('os', '')} {s.get('version', '')}".strip()
        agent_v = s.get("agentVersion", "N/A")

        sid = s["_id"]
        enc_r = httpx.get("https://console.jumpcloud.com/api/v2/systeminsights/disk_encryption",
            headers=get_jc_headers(),
            params={"limit": 10, "filter": f"system_id:eq:{sid}"}, timeout=15)
        enc_items = [e for e in (enc_r.json() if isinstance(enc_r.json(), list) else [])
                     if e.get("system_id") == sid]
        if enc_items:
            encrypted = all(e.get("encrypted") == "1" or e.get("encrypted") is True for e in enc_items)
            enc_str = "✅ Activado" if encrypted else "❌ Desactivado"
        else:
            enc_str = "⚠️ Sin datos"

        return (
            f"*{hn_orig}*\n"
            f"  Estado: {active}\n"
            f"  Último check-in: {last_contact_str}\n"
            f"  OS: {os_name}\n"
            f"  Agente JC: {agent_v}\n"
            f"  Disk encryption: {enc_str}"
        )

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(fetch_host_info, hostnames))
    return "\n\n".join(results)


def jc_equipos_sin_conexion(dias: int, solo_macs: bool = False) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=dias)
    sin_conexion = []
    skip = 0
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        MOBILE_SKIP = ("redmi", "honor", "samsung", "iphone")
        for s in items:
            hn = s.get("hostname", "") or s.get("displayName", "") or s.get("_id", "sin nombre")
            if any(k in hn.lower() for k in MOBILE_SKIP):
                continue
            if solo_macs and "mac" not in hn.lower():
                continue
            last = s.get("lastContact", "")
            if not last:
                sin_conexion.append((hn, "Nunca"))
                continue
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if dt < cutoff:
                    delta = datetime.now(timezone.utc) - dt
                    sin_conexion.append((hn, f"{delta.days} días"))
            except Exception:
                pass
        if len(items) < 100:
            break
        skip += 100

    if not sin_conexion:
        return f"Todos los equipos se conectaron en los últimos {dias} días."
    sin_conexion.sort(key=lambda x: x[1], reverse=True)
    lines = [f"{hn}: sin conexión hace {d}" for hn, d in sin_conexion]
    return f"Equipos sin conexión hace +{dias} días ({len(sin_conexion)}):\n" + "\n".join(lines)


def buscar_hostname(query: str) -> str:
    q = query.lower().strip()
    matches = []

    # Buscar en sistemas por hostname parcial
    skip = 0
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        for s in items:
            hn = s.get("hostname", "")
            dn = s.get("displayName", "")
            if q in hn.lower() or q in dn.lower():
                matches.append(("hostname", hn, dn))
        if len(items) < 100:
            break
        skip += 100

    if not matches:
        # Si parece un email, usar filtro exacto; si no, usar search por nombre
        if "@" in query:
            r2 = httpx.get("https://console.jumpcloud.com/api/systemusers",
                headers=get_jc_headers(),
                params={"filter": f"email:eq:{query}", "limit": 5}, timeout=15)
        else:
            r2 = httpx.get("https://console.jumpcloud.com/api/systemusers",
                headers=get_jc_headers(),
                params={"search[fields]": "firstname,lastname", "search[term]": query, "limit": 10}, timeout=15)
        users_found = r2.json().get("results", [])

        def fetch_user_systems(u):
            uid = u["_id"]
            display = f"{u.get('firstname', '')} {u.get('lastname', '')}".strip()
            email = u.get("email", "")
            r3 = httpx.get(f"https://console.jumpcloud.com/api/v2/users/{uid}/systems",
                headers=get_jc_headers(), params={"limit": 10}, timeout=15)
            refs = r3.json() if isinstance(r3.json(), list) else []
            results_u = []
            for ref in refs:
                r4 = httpx.get(f"https://console.jumpcloud.com/api/systems/{ref['id']}",
                    headers=get_jc_headers(), timeout=15)
                hn = r4.json().get("hostname", ref["id"])
                results_u.append(("usuario", hn, f"{display} ({email})"))
            return results_u

        with ThreadPoolExecutor(max_workers=10) as ex:
            for batch in ex.map(fetch_user_systems, users_found):
                matches.extend(batch)

    if not matches:
        return f"No se encontró ningún equipo que coincida con '{query}'."

    lines = []
    for match_type, hn, extra in matches:
        if match_type == "hostname":
            # extra = displayName; show it if it differs from hostname
            label = f"{hn} (nombre en JumpCloud: *{extra}*)" if extra and extra.lower() != hn.lower() else hn
            lines.append(label)
        else:
            lines.append(f"{hn} — asignado a {extra}")
    # Return hostnames (not display names) so Claude can pass them to other tools
    hostnames_only = [hn for _, hn, _ in matches]
    result = f"Equipos encontrados para '{query}':\n" + "\n".join(lines)
    result += f"\n\n_Hostnames reales: {', '.join(hostnames_only)}_"
    return result


def trend_alertas(horas: int) -> str:
    start = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = httpx.get(f"{TREND_BASE}/v3.0/workbench/alerts",
        headers=get_trend_headers(),
        params={"startDateTime": start, "orderBy": "createdDateTime desc", "top": 50}, timeout=30)
    data = r.json()
    if not isinstance(data, dict):
        return f"Error en la API de Trend (HTTP {r.status_code}): {str(data)[:300]}"
    if not r.is_success:
        return f"Error Trend API: {data.get('message') or str(data)[:300]}"
    items = data.get("items", [])
    if not items:
        return f"No hubo alertas de seguridad en las últimas {horas} horas."

    lines = [f"*Alertas Trend Vision One — últimas {horas}h ({len(items)} total):*\n"]
    for alert in items:
        severity = (alert.get("severity") or "unknown").upper()
        icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(severity, "⚪")
        name = alert.get("model") or alert.get("modelName") or "Sin nombre"
        created = alert.get("createdDateTime", "")[:16].replace("T", " ")
        description = alert.get("description", "")
        link = alert.get("workbenchLink", "")

        # Hostnames afectados
        hostnames = []
        accounts = []
        for entity in alert.get("impactScope", {}).get("entities", []):
            if entity.get("entityType") == "host":
                val = entity.get("entityValue", {})
                if isinstance(val, dict):
                    hostnames.append(val.get("name", ""))
                elif isinstance(val, str):
                    hostnames.append(val)
            elif entity.get("entityType") == "account":
                accounts.append(entity.get("entityValue", ""))

        # MITRE techniques
        mitre = []
        for rule in alert.get("matchedRules", []):
            for f in rule.get("matchedFilters", []):
                mitre.extend(f.get("mitreTechniqueIds", []))
        mitre = list(dict.fromkeys(mitre))  # dedup

        block = [f"{icon} *[{severity}] {name}*  ({created} UTC)"]
        if hostnames:
            block.append(f"  🖥️ Equipo: {', '.join(h for h in hostnames if h)}")
        if accounts:
            block.append(f"  👤 Usuario: {', '.join(accounts)}")
        if description:
            block.append(f"  📋 {description}")
        if mitre:
            block.append(f"  🎯 MITRE: {', '.join(mitre)}")
        if link:
            block.append(f"  🔗 {link}")
        lines.append("\n".join(block))

    return "\n\n".join(lines)


def trend_estado_endpoint(hostnames: list) -> str:
    all_eps = get_all_trend_endpoints()
    if not all_eps:
        return "⏳ El cache de Trend aún se está cargando (puede tardar ~20 segundos al iniciar el bot). Intentá de nuevo en un momento."
    ep_map = {ep.get("endpointName", "").upper(): ep for ep in all_eps}

    results = []
    for hn in hostnames:
        ep = ep_map.get(hn.upper()) or next(
            (v for k, v in ep_map.items() if hn.upper() in k), None
        )
        if not ep:
            results.append(f"*{hn}*: No encontrado en Trend Vision One")
            continue

        edr = ep.get("edrSensor") or {}
        epp = ep.get("eppAgent") or {}

        connectivity = edr.get("connectivity") or epp.get("status") or "unknown"
        conn_icon = "🟢" if connectivity == "connected" else "🔴"

        last_edr = (edr.get("lastConnectedDateTime") or "")[:16].replace("T", " ")
        last_epp = (epp.get("lastConnectedDateTime") or "")[:16].replace("T", " ")
        last_seen = last_edr or last_epp or "N/A"

        epp_status = epp.get("status", "")
        epp_icon = "🟢" if epp_status == "on" else ("🔴" if epp_status == "off" else "⚪")

        os_name = ep.get("osName", "")
        real_name = ep.get("endpointName") or ep.get("displayName") or hn

        results.append(
            f"*{real_name}*\n"
            f"  EDR: {conn_icon} {connectivity}\n"
            f"  EPP (Trend Antivirus): {epp_icon} {epp_status or 'N/A'}\n"
            f"  Última conexión: {last_seen}\n"
            f"  OS: {os_name}"
        )
    return "\n\n".join(results)



def checklist_onboarding(email: str) -> str:
    lines = [f"*Checklist onboarding: {email}*\n"]

    # 1. Buscar equipo en JumpCloud
    r = httpx.get("https://console.jumpcloud.com/api/systemusers",
        headers=get_jc_headers(),
        params={"filter": f"email:eq:{email}", "limit": 5}, timeout=15)
    users = r.json().get("results", [])
    if not users:
        lines.append("❌ Usuario no encontrado en JumpCloud")
        return "\n".join(lines)

    user = users[0]
    uid = user["_id"]
    display = f"{user.get('firstname', '')} {user.get('lastname', '')}".strip()
    lines.append(f"✅ Usuario encontrado: {display}")

    # 2. Equipos asignados
    r2 = httpx.get(f"https://console.jumpcloud.com/api/v2/users/{uid}/systems",
        headers=get_jc_headers(), params={"limit": 10}, timeout=15)
    system_refs = r2.json() if isinstance(r2.json(), list) else []
    if not system_refs:
        lines.append("❌ Sin equipo asignado en JumpCloud")
        return "\n".join(lines)

    def fetch_system(ref):
        sid = ref.get("id")
        if not sid:
            return None
        r3 = httpx.get(f"https://console.jumpcloud.com/api/systems/{sid}",
            headers=get_jc_headers(), timeout=15)
        s = r3.json()
        hn = s.get("hostname") or s.get("displayName") or sid
        return (hn, sid, s)

    with ThreadPoolExecutor(max_workers=10) as ex:
        system_ids = [r for r in ex.map(fetch_system, system_refs) if r]

    hostnames = [hn for hn, _, _ in system_ids]
    lines.append(f"✅ Equipo(s) asignado(s): {', '.join(hostnames)}")

    def check_system(args):
        hn, sid, s = args
        result = []
        last = s.get("lastContact", "")
        if last:
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - dt
                if delta.days <= 3:
                    result.append(f"✅ {hn}: conexión reciente (hace {delta.days}d {delta.seconds // 3600}h)")
                else:
                    result.append(f"⚠️ {hn}: último check-in hace {delta.days} días")
            except Exception:
                result.append(f"⚠️ {hn}: no se pudo verificar última conexión")
        all_eps = get_all_trend_endpoints()
        has_trend = any(ep.get("endpointName", "").upper() == hn.upper() for ep in all_eps)
        result.append(f"✅ {hn}: agente Trend instalado" if has_trend else f"❌ {hn}: agente Trend NO instalado")
        # Cloudflare WARP — buscar en System Insights apps (Mac) o programs (Windows)
        os_family = s.get("os", "").lower()
        endpoint = "apps" if "mac" in os_family or "darwin" in os_family else "programs"
        name_field = "display_name" if endpoint == "apps" else "name"
        cf_apps = []
        skip_cf = 0
        while True:
            cf_r = httpx.get(
                f"https://console.jumpcloud.com/api/v2/systeminsights/{endpoint}",
                headers=get_jc_headers(),
                params={"filter": f"system_id:eq:{sid}", "limit": 200, "skip": skip_cf}, timeout=20,
            )
            page = cf_r.json() if isinstance(cf_r.json(), list) else []
            cf_apps.extend(page)
            if len(page) < 200:
                break
            skip_cf += 200
        cf_keywords = ("cloudflare warp", "cloudflare one client")
        has_cf = any(
            any(kw in (a.get(name_field) or a.get("bundle_name") or a.get("name") or "").lower() for kw in cf_keywords)
            for a in cf_apps
        )
        result.append(f"✅ {hn}: Cloudflare WARP instalado" if has_cf else f"❌ {hn}: Cloudflare WARP NO instalado")
        return result

    with ThreadPoolExecutor(max_workers=10) as ex:
        for chunk in ex.map(check_system, system_ids):
            lines.extend(chunk)

    return "\n".join(lines)



def generar_script(descripcion: str, lenguaje: str, say, channel_id: str) -> str:
    ext_map = {"bash": "sh", "python": "py", "powershell": "ps1"}
    shebang_map = {
        "bash": "#!/bin/bash\n",
        "python": "#!/usr/bin/env python3\n",
        "powershell": "",
    }

    prompt = (
        f"Write a {lenguaje} script that does the following:\n\n"
        f"{descripcion}\n\n"
        f"MANDATORY rules — do not break any of these:\n"
        f"1. SILENT: no output whatsoever (no echo, no print, no Write-Host, no progress bars, no prompts). "
        f"   The user must never see anything and must never need to interact. Redirect all output to null "
        f"   (>/dev/null 2>&1 for bash, -ErrorAction SilentlyContinue / Out-Null for powershell, "
        f"   suppress all print/logging for python).\n"
        f"2. ASCII ONLY: every single character in the script — including comments and strings — "
        f"   must be plain ASCII (0x00-0x7F). No accented letters, no smart quotes, no em-dashes, "
        f"   no Unicode of any kind. If you need to express a concept in a comment, use English or "
        f"   transliterate to ASCII (e.g. 'configuracion' not 'configuración').\n"
        f"3. No user interaction: no read/input/pause/prompt calls.\n"
        f"4. Basic error handling so the script does not crash with an unhandled exception.\n"
        f"5. Return only the raw code — no markdown fences, no explanations."
    )

    resp = claude.messages.create(
        model=os.environ.get("AGENT_MODEL", "claude-sonnet-4-6"),
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    code = resp.content[0].text.strip()

    # Quitar bloques de markdown si Claude los incluyó igual
    if code.startswith("```"):
        lines = code.split("\n")
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Sanitize: replace any non-ASCII character that slipped through
    code = code.encode("ascii", errors="replace").decode("ascii").replace("?", "_")

    ext = ext_map.get(lenguaje, "txt")
    shebang = shebang_map.get(lenguaje, "")
    final_code = shebang + code if shebang and not code.startswith("#!") else code

    filename = f"script_{lenguaje}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    tmp_path = ROOT / "reports" / filename
    tmp_path.write_text(final_code, encoding="utf-8")

    try:
        app.client.files_upload_v2(
            channel=channel_id,
            file=tmp_path.read_bytes(),
            filename=filename,
            initial_comment=f"✅ Script `{lenguaje}` generado:",
        )
        tmp_path.unlink(missing_ok=True)
        return f"Script generado y subido: {filename}"
    except Exception as e:
        return f"Script generado pero no se pudo subir: {e}\n\n```{lenguaje}\n{final_code}\n```"


def run_report(tipo: str, say, channel_id: str) -> str:
    script_path, report_key = REPORT_MAP[tipo]
    say("⏳ Generando reporte, un momento...")
    try:
        env = os.environ.copy()
        env["SKIP_SLACK_NOTIFY"] = "1"
        result = subprocess.run(
            [str(ROOT / ".venv/bin/python3"), str(ROOT / script_path)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=300, env=env,
        )
        if result.returncode != 0:
            say(f"❌ Error al generar el reporte:\n```{result.stderr[-1000:]}```")
            return f"Error: {result.stderr[-500:]}"

        files = sorted((ROOT / "reports").glob(f"{report_key}*.xlsx"), reverse=True)
        if not files:
            say("⚠️ El reporte no generó ningún archivo.")
            return "Error: no se generó archivo"

        latest = files[0]
        with open(latest, "rb") as f:
            app.client.files_upload_v2(
                channel=channel_id, file=f.read(), filename=latest.name,
                initial_comment=f"✅ Reporte generado: *{latest.name}*",
            )
        say("✅ Listo!")
        return f"Reporte generado: {latest.name}"
    except subprocess.TimeoutExpired:
        say("❌ El reporte tardó demasiado y fue cancelado.")
        return "Error: timeout"
    except Exception as e:
        say(f"❌ Error inesperado: {e}")
        return f"Error: {e}"


# ─── Daily summary ─────────────────────────────────────────────────────────────

def _get_new_systems(since_utc_dt) -> list:
    """Return systems created after since_utc_dt by querying /api/systems sorted by -created."""
    new_systems = []
    skip = 0
    since_str = since_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    while True:
        r = httpx.get("https://console.jumpcloud.com/api/systems",
            headers=get_jc_headers(),
            params={"limit": 100, "skip": skip, "sort": "-created"}, timeout=20)
        items = r.json().get("results", [])
        if not items:
            break
        found_older = False
        for s in items:
            created = s.get("created", "")
            if created and created >= since_str:
                new_systems.append(s)
            else:
                found_older = True
        if found_older or len(items) < 100:
            break
        skip += 100
    return new_systems


SNAPSHOT_FILE = ROOT / "reports" / ".systems_snapshot.json"

def _load_snapshot() -> dict:
    import json as _json
    if SNAPSHOT_FILE.exists():
        try:
            return _json.loads(SNAPSHOT_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_snapshot(systems: list):
    import json as _json
    snapshot = {s["_id"]: s.get("hostname", "") for s in systems}
    SNAPSHOT_FILE.write_text(_json.dumps(snapshot))

def _get_deleted_systems(since_str: str, until_str: str) -> list:
    """Return systems deleted in [since_str, until_str] using Directory Insights API."""
    import json as _json
    deleted = []
    search_after = None
    while True:
        body = {
            "service": ["directory"],
            "start_time": since_str,
            "end_time": until_str,
            "limit": 10000,
            "q": "event_type:system_delete",
        }
        if search_after:
            body["search_after"] = search_after
        r = httpx.post(
            "https://api.jumpcloud.com/insights/directory/v1/events",
            headers=get_jc_headers(),
            json=body,
            timeout=30,
        )
        if not r.is_success:
            break
        page = [e for e in r.json() if isinstance(e, dict)] if isinstance(r.json(), list) else []
        for e in page:
            if e.get("event_type") == "system_delete":
                hostname = e.get("resource", {}).get("hostname", "desconocido")
                deleted.append({"hostname": hostname})
        cursor = r.headers.get("x-search_after", "")
        if len(page) < 10000 or not cursor:
            break
        try:
            search_after = _json.loads(cursor)
        except Exception:
            break
    return deleted


# Commands de onboarding: cmd_id → nombre en JumpCloud
CMD_ID_NAMES = {
    "6a21e3468cdfa30d628c2e39": "Install TrendMicro Windows Completo NUEVO - post agente",
    "6a0f4863b40cb74ab3c61939": "Rename MacOS post Agente",
    "6a104c6cf1839c8c2e447a0e": "Rename Jumpcloud post Agente",
}
WIN_CMD_IDS = ["6a21e3468cdfa30d628c2e39"]
MAC_CMD_IDS = ["6a21e3468cdfa30d628c2e39", "6a0f4863b40cb74ab3c61939", "6a104c6cf1839c8c2e447a0e"]

def _get_command_results_for_system(system_id: str, cmd_ids: list, since_utc: str) -> list:
    """Return command results for a system filtered by command name and requestTime.
    JumpCloud commandresults API ignores field filters, so we fetch pages and filter in Python.
    """
    target_names = {CMD_ID_NAMES[cid] for cid in cmd_ids if cid in CMD_ID_NAMES}
    # API max limit is 100; skip > ~100 returns 400, so we only get the most recent page.
    # For the daily 15h window this is sufficient — onboarding commands run right after enrollment.
    r = httpx.get("https://console.jumpcloud.com/api/commandresults",
        headers=get_jc_headers(),
        params={"sort": "-requestTime", "limit": 100},
        timeout=15)
    if not r.is_success or not r.content:
        return []
    raw = r.json()
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    seen_ids = set()
    results = []
    for item in (items if isinstance(items, list) else []):
        req_time = item.get("requestTime", "")
        if req_time < since_utc:
            continue
        if item.get("systemId") != system_id:
            continue
        if item.get("name", "") not in target_names:
            continue
        result_id = item.get("_id", "")
        if result_id in seen_ids:
            continue
        seen_ids.add(result_id)
        output    = item.get("response", {}).get("data", {}).get("output", "").strip()
        error     = item.get("response", {}).get("error", "").strip()
        results.append({
            "name":      item.get("name", ""),
            "exit_code": item.get("exitCode", "?"),
            "output":    output,
            "error":     error,
            "time":      req_time[:16].replace("T", " "),
        })
    return results


def send_daily_summary():
    """Resumen diario: maquinas dadas de alta/baja en JumpCloud desde las 6 PM GMT-3."""
    channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    if not channel_id:
        print("[daily_summary] SLACK_CHANNEL_ID no configurado")
        return

    # Ventana: desde las 6 PM GMT-3 mas reciente hasta ahora.
    # Los lunes: miramos desde el viernes 18:00 GMT-3 (cubre viernes noche + fin de semana).
    now_utc   = datetime.now(timezone.utc)
    now_local = now_utc - timedelta(hours=3)
    today_6pm = now_local.replace(hour=18, minute=0, second=0, microsecond=0)
    if now_local.weekday() == 0:  # lunes
        days_back = 3 if now_local.hour < 18 else 2  # viernes pasado
        since_local = today_6pm - timedelta(days=days_back)
    else:
        since_local = today_6pm if now_local.hour >= 18 else today_6pm - timedelta(days=1)
    since_utc_dt = since_local + timedelta(hours=3)
    since_str = since_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"*Resumen diario - Endpoint Security Agent*",
        f"Periodo: {since_local.strftime('%d/%m/%Y %H:%M')} a {now_local.strftime('%d/%m/%Y %H:%M')} (GMT-3)\n",
    ]

    # ── Maquinas dadas de alta ──────────────────────────────────────────────────
    try:
        new_systems = _get_new_systems(since_utc_dt)
    except Exception as e:
        print(f"[daily_summary] error get_new_systems: {e}")
        new_systems = []

    if new_systems:
        lines.append(f"*Maquinas dadas de alta ({len(new_systems)}):*")

        def process_new_system(s):
            hostname  = s.get("hostname", "N/A")
            system_id = s["_id"]
            os_fam    = s.get("osFamily", "").lower()
            is_mac    = os_fam == "darwin"

            # Email del usuario asignado via primarySystemUser
            email = "sin usuario"
            try:
                pu = s.get("primarySystemUser")
                if pu and isinstance(pu, dict):
                    uid = pu.get("id", "")
                    if uid:
                        r_usr = httpx.get(f"https://console.jumpcloud.com/api/systemusers/{uid}",
                            headers=get_jc_headers(), timeout=10)
                        if r_usr.is_success:
                            email = r_usr.json().get("email", "sin usuario")
                elif not pu:
                    # Intentar via /v2/systems/{id}/users
                    r_u = httpx.get(f"https://console.jumpcloud.com/api/v2/systems/{system_id}/users",
                        headers=get_jc_headers(), params={"limit": 5}, timeout=10)
                    users = r_u.json() if isinstance(r_u.json(), list) else []
                    real = [u for u in users if u.get("email", "") != "adminit@cashea.app"]
                    if real:
                        email = real[0].get("email", "sin usuario")
            except Exception:
                pass

            # Resultados de comandos
            cmd_ids = MAC_CMD_IDS if is_mac else WIN_CMD_IDS
            cmd_results = []
            try:
                cmd_results = _get_command_results_for_system(system_id, cmd_ids, since_str)
            except Exception:
                pass

            os_label = "macOS" if is_mac else "Windows"
            block = [f"  *{hostname}*  ({os_label}) | {email}"]
            if cmd_results:
                for cr in cmd_results:
                    status = "OK" if str(cr["exit_code"]) == "0" else f"exit {cr['exit_code']}"
                    out = cr["output"][:200] if cr["output"] else (cr["error"][:200] if cr["error"] else "sin output")
                    block.append(f"    [{status}] {cr['name']} ({cr['time']})")
                    if out:
                        block.append(f"    > {out}")
            else:
                block.append(f"    Sin resultados de comandos para IDs: {', '.join(cmd_ids)}")
            return "\n".join(block)

        with ThreadPoolExecutor(max_workers=5) as ex:
            lines.extend(ex.map(process_new_system, new_systems))
    else:
        lines.append("*Maquinas dadas de alta:* ninguna en el periodo")

    lines.append("")

    # ── Maquinas eliminadas (diff vs snapshot anterior) ─────────────────────────
    # JumpCloud no emite system_delete en Directory Insights, así que comparamos
    # el snapshot guardado ayer contra el estado actual.
    deleted = []
    all_sys_r = []
    try:
        skip = 0
        while True:
            r = httpx.get("https://console.jumpcloud.com/api/systems",
                headers=get_jc_headers(), params={"limit": 100, "skip": skip}, timeout=20)
            items = r.json().get("results", [])
            if not items:
                break
            all_sys_r.extend(items)
            if len(items) < 100:
                break
            skip += 100

        prev_snapshot = _load_snapshot()  # {id: hostname}
        current_ids = {s["_id"] for s in all_sys_r}
        for sid, hostname in prev_snapshot.items():
            if sid not in current_ids:
                deleted.append({"hostname": hostname or sid})
    except Exception as e:
        print(f"[daily_summary] error get_deleted_systems: {e}")

    if deleted:
        lines.append(f"*Maquinas eliminadas ({len(deleted)}):*")
        for d in deleted:
            lines.append(f"  {d['hostname']}")
    else:
        lines.append("*Maquinas eliminadas:* ninguna en el periodo")

    # Actualizar snapshot con estado actual
    try:
        if all_sys_r:
            _save_snapshot(all_sys_r)
    except Exception as e:
        print(f"[daily_summary] error guardando snapshot: {e}")

    # ── Generar Excel ──────────────────────────────────────────────────────────
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()

        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        def hdr_cell(cell, text, bg="1A1A2E"):
            cell.value = text
            cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
            cell.fill = PatternFill("solid", fgColor=bg)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

        def data_cell(cell, text, bold=False, bg=None):
            cell.value = text
            cell.font = Font(name="Arial", bold=bold, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
            if bg:
                cell.fill = PatternFill("solid", fgColor=bg)

        # ── Hoja 1: Altas ──────────────────────────────────────────────────────
        ws1 = wb.active
        ws1.title = "Altas"
        headers_altas = ["Hostname", "OS", "Email usuario", "Comando", "Estado", "Output / Error", "Fecha ejecucion"]
        for col, h in enumerate(headers_altas, 1):
            hdr_cell(ws1.cell(1, col), h)
        ws1.row_dimensions[1].height = 28
        ws1.freeze_panes = "A2"

        row = 2
        for s in new_systems:
            hostname  = s.get("hostname", "N/A")
            system_id = s["_id"]
            is_mac    = s.get("osFamily", "").lower() == "darwin"
            os_label  = "macOS" if is_mac else "Windows"

            email = "sin usuario"
            try:
                pu = s.get("primarySystemUser")
                if pu and isinstance(pu, dict):
                    uid = pu.get("id", "")
                    if uid:
                        r_usr = httpx.get(f"https://console.jumpcloud.com/api/systemusers/{uid}",
                            headers=get_jc_headers(), timeout=10)
                        if r_usr.is_success:
                            email = r_usr.json().get("email", "sin usuario")
            except Exception:
                pass

            cmd_ids = MAC_CMD_IDS if is_mac else WIN_CMD_IDS
            try:
                cmd_results = _get_command_results_for_system(system_id, cmd_ids, since_str)
            except Exception:
                cmd_results = []

            bg = "EAF4FB" if is_mac else "EAF7EA"
            if cmd_results:
                for cr in cmd_results:
                    status = "OK" if str(cr["exit_code"]) == "0" else f"exit {cr['exit_code']}"
                    out = cr["output"] if cr["output"] else cr["error"]
                    data_cell(ws1.cell(row, 1), hostname, bold=True, bg=bg)
                    data_cell(ws1.cell(row, 2), os_label, bg=bg)
                    data_cell(ws1.cell(row, 3), email, bg=bg)
                    data_cell(ws1.cell(row, 4), cr["name"], bg=bg)
                    data_cell(ws1.cell(row, 5), status, bold=True, bg=bg)
                    data_cell(ws1.cell(row, 6), out[:500], bg=bg)
                    data_cell(ws1.cell(row, 7), cr["time"], bg=bg)
                    ws1.row_dimensions[row].height = 60
                    row += 1
            else:
                data_cell(ws1.cell(row, 1), hostname, bold=True, bg=bg)
                data_cell(ws1.cell(row, 2), os_label, bg=bg)
                data_cell(ws1.cell(row, 3), email, bg=bg)
                data_cell(ws1.cell(row, 4), "Sin resultados de comandos", bg=bg)
                data_cell(ws1.cell(row, 5), "-", bg=bg)
                data_cell(ws1.cell(row, 6), "", bg=bg)
                data_cell(ws1.cell(row, 7), "", bg=bg)
                ws1.row_dimensions[row].height = 30
                row += 1

        if row == 2:
            ws1.cell(2, 1).value = "Ninguna maquina dada de alta en el periodo"

        ws1.column_dimensions["A"].width = 28
        ws1.column_dimensions["B"].width = 10
        ws1.column_dimensions["C"].width = 32
        ws1.column_dimensions["D"].width = 42
        ws1.column_dimensions["E"].width = 12
        ws1.column_dimensions["F"].width = 55
        ws1.column_dimensions["G"].width = 18

        # ── Hoja 2: Bajas ──────────────────────────────────────────────────────
        ws2 = wb.create_sheet("Bajas")
        for col, h in enumerate(["Hostname"], 1):
            hdr_cell(ws2.cell(1, col), h)
        ws2.row_dimensions[1].height = 28
        if deleted:
            for i, d in enumerate(deleted, 2):
                data_cell(ws2.cell(i, 1), d["hostname"], bold=True, bg="FDEDEC")
                ws2.row_dimensions[i].height = 25
        else:
            ws2.cell(2, 1).value = "Ninguna maquina eliminada en el periodo"
        ws2.column_dimensions["A"].width = 35

        # Guardar y subir
        fname = f"daily_summary_{now_local.strftime('%Y%m%d_%H%M')}.xlsx"
        fpath = ROOT / "reports" / fname
        wb.save(str(fpath))

        from slack_sdk import WebClient
        wc = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
        periodo = f"{since_local.strftime('%d/%m/%Y %H:%M')} - {now_local.strftime('%d/%m/%Y %H:%M')} (GMT-3)"
        wc.files_upload_v2(
            channel=channel_id,
            file=fpath.read_bytes(),
            filename=fname,
            initial_comment=f"*Resumen diario — Endpoint Security Agent*\nPeriodo: {periodo}\nAltas: {len(new_systems)} | Bajas: {len(deleted)}",
        )
        fpath.unlink(missing_ok=True)
        print("[daily_summary] enviado OK")

    except Exception as e:
        import traceback
        print(f"[daily_summary] error: {e}")
        traceback.print_exc()


MATCHES_SCRIPT = Path("/Users/luciarasini/Documents/Desarrollo Lucia/trend-vision-one-dashboard/scripts/generate_matches_report.py")
MATCHES_VENV_PYTHON = Path("/Users/luciarasini/Documents/Desarrollo Lucia/trend-vision-one-dashboard/.venv/bin/python3")


def lanzar_script_matches(say, channel_id: str) -> str:
    say("⚙️ Ejecutando script de matches JumpCloud ↔ Trend... puede tardar unos minutos.")
    try:
        result = subprocess.run(
            [str(MATCHES_VENV_PYTHON), str(MATCHES_SCRIPT)],
            capture_output=True, text=True, timeout=600,
            cwd=str(MATCHES_SCRIPT.parent.parent),
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "sin output")[-1000:]
            return f"❌ El script falló (exit {result.returncode}):\n```{err}```"

        output_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        xls_path = Path(output_line) if output_line else None

        if not xls_path or not xls_path.exists():
            # fallback: buscar el .xls más reciente en reports/
            reports_dir = MATCHES_SCRIPT.parent.parent / "reports"
            candidates = sorted(reports_dir.glob("jumpcloud_windows_macos_trend_match_grid_*.xls"), reverse=True)
            xls_path = candidates[0] if candidates else None

        if not xls_path or not xls_path.exists():
            return "⚠️ El script terminó pero no encontré el archivo de reporte."

        from slack_sdk import WebClient
        wc = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
        wc.files_upload_v2(
            channel=channel_id,
            file=xls_path.read_bytes(),
            filename=xls_path.name,
            initial_comment=f"✅ *Reporte de matches JumpCloud ↔ Trend Vision One*\nArchivo: `{xls_path.name}`",
        )
        return f"✅ Reporte generado y subido: `{xls_path.name}`"
    except subprocess.TimeoutExpired:
        return "⏱️ El script tardó más de 10 minutos y fue cancelado."
    except Exception as e:
        return f"❌ Error al ejecutar el script: {e}"


_cloudflare_monitor_active = threading.Event()
_cloudflare_monitor_lock = threading.Lock()


def monitorear_cloudflare(say, channel_id: str) -> str:
    with _cloudflare_monitor_lock:
        if _cloudflare_monitor_active.is_set():
            return "⚠️ Ya hay un monitoreo de Cloudflare activo."
        _cloudflare_monitor_active.set()

    WORKFLOW_ID = "6a4e5b318cf704c8149dbdf9"
    REPORTS_DIR = Path(__file__).parent / "reports"
    REPORTS_DIR.mkdir(exist_ok=True)
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y%m%d_%H%M%S")
    excel_path = REPORTS_DIR / f"cloudflare_install_{now_str}.xlsx"
    cutoff_iso = None  # sin límite de tiempo — filtramos por workflowId

    say(f"📡 Monitoreo de *Cloudflare Install* iniciado. Archivo: `{excel_path.name}`\nHago polling cada 30 seg y actualizo el Excel a medida que llegan resultados.")

    def _extract_output(res):
        response = res.get("response", {})
        if isinstance(response, dict):
            data = response.get("data", {})
            if isinstance(data, dict):
                output = data.get("output", "")
                err = response.get("error", "")
                return output if output else err
            return str(data) if data else ""
        return str(response) if response else ""

    def _save_excel(results_map):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        wb2 = Workbook()
        ws2 = wb2.active
        ws2.title = "Resultados"
        ws2.append(["Device", "Exit Code", "Resultado"])
        for cell in ws2[1]:
            cell.fill = PatternFill("solid", fgColor="1A1A2E")
            cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
        ws2.row_dimensions[1].height = 28
        ws2.column_dimensions["A"].width = 28
        ws2.column_dimensions["B"].width = 12
        ws2.column_dimensions["C"].width = 80
        for i, res in enumerate(sorted(results_map.values(), key=lambda r: r.get("requestTime", "")), 2):
            device = res.get("system") or res.get("systemId", "desconocido")
            exit_code = res.get("exitCode")
            output = _extract_output(res)
            ws2.append([device, exit_code if exit_code is not None else "", output])
            if exit_code is None:
                fill_color = "FFF9E6"
            elif exit_code == 0:
                fill_color = "E8F8F5"
            else:
                fill_color = "FDEDEC"
            row_fill = PatternFill("solid", fgColor=fill_color)
            for cell in ws2[i]:
                cell.fill = row_fill
                cell.border = border
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(vertical="top", wrap_text=(cell.column == 3))
            ws2.row_dimensions[i].height = 40
        wb2.save(str(excel_path))

    def _run():
        results_map = {}
        last_slack_count = 0
        try:
            while _cloudflare_monitor_active.is_set():
                try:
                    skip = 0
                    changed = False
                    while True:
                        r = httpx.get(
                            "https://console.jumpcloud.com/api/commandresults",
                            headers=get_jc_headers(),
                            params={"limit": 100, "skip": skip, "sort": "-requestTime"},
                            timeout=20,
                        )
                        if not r.is_success:
                            break
                        batch = r.json().get("results", [])
                        if not batch:
                            break
                        for res in batch:
                            if res.get("workflowId") != WORKFLOW_ID:
                                continue
                            rid = res["_id"]
                            prev = results_map.get(rid)
                            if prev is None or (prev.get("exitCode") is None and res.get("exitCode") is not None):
                                results_map[rid] = res
                                changed = True
                        if len(batch) < 100:
                            break
                        skip += 100

                    if changed:
                        _save_excel(results_map)
                        print(f"[cloudflare_monitor] {len(results_map)} resultados guardados", flush=True)

                    total = len(results_map)
                    if total > 0 and total - last_slack_count >= 50:
                        last_slack_count = total
                        completed = sum(1 for r in results_map.values() if r.get("exitCode") is not None)
                        say(f"📊 Cloudflare Install: *{total}* máquinas en el Excel, *{completed}* completadas.")

                except Exception as e:
                    print(f"[cloudflare_monitor] poll error: {e}", flush=True)

                time.sleep(30)
        finally:
            _cloudflare_monitor_active.clear()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return f"✅ Monitoreo iniciado. Excel: `{excel_path.name}`"


def detener_monitoreo_cloudflare() -> str:
    if not _cloudflare_monitor_active.is_set():
        return "ℹ️ No hay monitoreo activo en este momento."
    _cloudflare_monitor_active.clear()
    return "🛑 Monitoreo detenido."


_cve_monitor_active = threading.Event()
_cve_monitor_lock = threading.Lock()


def monitorear_cve(say, channel_id: str) -> str:
    with _cve_monitor_lock:
        if _cve_monitor_active.is_set():
            return "⚠️ Ya hay un monitoreo de CVE activo."
        _cve_monitor_active.set()

    WORKFLOW_ID = "6a7cb67afa053a5729c59c4e"
    REPORTS_DIR = Path(__file__).parent / "reports"
    REPORTS_DIR.mkdir(exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    excel_path = REPORTS_DIR / f"cve_remediation_{now_str}.xlsx"

    say(f"📡 Monitoreo de *CVE-2026-50390* iniciado. Archivo: `{excel_path.name}`\nHago polling cada 30 seg y actualizo el Excel a medida que llegan resultados.")

    def _extract_status(res):
        response = res.get("response", {})
        output = ""
        if isinstance(response, dict):
            data = response.get("data", {})
            if isinstance(data, dict):
                output = data.get("output", "") or response.get("error", "")
            else:
                output = str(data) if data else ""
        else:
            output = str(response) if response else ""
        for line in output.splitlines():
            if "Status:" in line:
                return line.strip().lstrip("[VULS]").strip()
        return output.strip() if output.strip() else ""

    def _save_excel(results_map):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        wb = Workbook()
        ws = wb.active
        ws.title = "CVE Remediation"
        ws.append(["Hostname", "Result"])
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="1A1A2E")
            cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
        ws.row_dimensions[1].height = 28
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 60
        for i, res in enumerate(sorted(results_map.values(), key=lambda r: r.get("requestTime", "")), 2):
            hostname = res.get("system") or res.get("systemId", "desconocido")
            status = _extract_status(res)
            ws.append([hostname, status if status else ("pendiente" if res.get("exitCode") is None else "")])
            if res.get("exitCode") is None:
                fill_color = "FFF9E6"
            elif "NOT VULNERABLE" in status or "REMEDIATED" in status:
                fill_color = "E8F8F5"
            elif "VULNERABLE" in status:
                fill_color = "FDEDEC"
            else:
                fill_color = "F2F2F2"
            row_fill = PatternFill("solid", fgColor=fill_color)
            for cell in ws[i]:
                cell.fill = row_fill
                cell.border = border
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            ws.row_dimensions[i].height = 20
        wb.save(str(excel_path))

    def _run():
        results_map = {}
        last_slack_count = 0
        try:
            while _cve_monitor_active.is_set():
                try:
                    skip = 0
                    changed = False
                    while True:
                        r = httpx.get(
                            "https://console.jumpcloud.com/api/commandresults",
                            headers=get_jc_headers(),
                            params={"limit": 100, "skip": skip, "sort": "-requestTime"},
                            timeout=20,
                        )
                        if not r.is_success:
                            break
                        batch = r.json().get("results", [])
                        if not batch:
                            break
                        for res in batch:
                            if res.get("workflowId") != WORKFLOW_ID:
                                continue
                            rid = res["_id"]
                            prev = results_map.get(rid)
                            if prev is None or (prev.get("exitCode") is None and res.get("exitCode") is not None):
                                results_map[rid] = res
                                changed = True
                        if len(batch) < 100:
                            break
                        skip += 100

                    if changed:
                        _save_excel(results_map)
                        print(f"[cve_monitor] {len(results_map)} resultados guardados", flush=True)

                    total = len(results_map)
                    if total > 0 and total - last_slack_count >= 50:
                        last_slack_count = total
                        completed = sum(1 for r in results_map.values() if r.get("exitCode") is not None)
                        say(f"📊 CVE-2026-50390: *{total}* máquinas en el Excel, *{completed}* completadas.")

                except Exception as e:
                    print(f"[cve_monitor] poll error: {e}", flush=True)

                time.sleep(30)
        finally:
            _cve_monitor_active.clear()

    threading.Thread(target=_run, daemon=True).start()
    return f"✅ Monitoreo CVE iniciado. Excel: `{excel_path.name}`"


def detener_monitoreo_cve() -> str:
    if not _cve_monitor_active.is_set():
        return "ℹ️ No hay monitoreo de CVE activo en este momento."
    _cve_monitor_active.clear()
    return "🛑 Monitoreo de CVE detenido."


def _daily_summary_loop():
    """Verifica cada minuto si es hora de enviar el resumen (09:00 GMT-3 = 12:00 UTC)."""
    last_sent_date = None
    while True:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc - timedelta(hours=3)  # GMT-3
        today = now_local.date()
        if now_local.hour == 9 and now_local.minute == 0 and last_sent_date != today:
            last_sent_date = today
            send_daily_summary()
        time.sleep(60)


# ─── Tool registry ─────────────────────────────────────────────────────────────

TOOL_HANDLERS = {
    "generar_reporte":         lambda inp, say, ch: run_report(inp["tipo"], say, ch),
    "consultar_software":      lambda inp, say, ch: consultar_software(inp["hostnames"], inp["app_name"]),
    "consultar_usuario":       lambda inp, say, ch: consultar_usuario(inp["hostnames"]),
    "verificar_parches":       lambda inp, say, ch: verificar_parches(inp["hostnames"], inp.get("mes"), inp.get("kb_id")),
    "enviar_comando":          lambda inp, say, ch: enviar_comando(inp["command_id"], inp["hostnames"]),
    "matchear_equipos":        lambda inp, say, ch: matchear_equipos(inp["hostnames"], inp["criterio"]),
    "jc_estadisticas":         lambda inp, say, ch: jc_estadisticas(),
    "jc_estado_equipo":        lambda inp, say, ch: jc_estado_equipo(inp["hostnames"]),
    "jc_equipos_sin_conexion": lambda inp, say, ch: jc_equipos_sin_conexion(inp["dias"], inp.get("solo_macs", False)),
    "buscar_hostname":         lambda inp, say, ch: buscar_hostname(inp["query"]),
    "trend_alertas":           lambda inp, say, ch: trend_alertas(inp["horas"]),
    "trend_estado_endpoint":   lambda inp, say, ch: trend_estado_endpoint(inp["hostnames"]),
    "trend_vulnerabilidades":  lambda inp, say, ch: trend_vulnerabilidades(inp["hostname"]),
    "checklist_onboarding":    lambda inp, say, ch: checklist_onboarding(inp["email"]),
    "generar_script":          lambda inp, say, ch: generar_script(inp["descripcion"], inp["lenguaje"], say, ch),
    "lanzar_script_matches":        lambda inp, say, ch: lanzar_script_matches(say, ch),
    "monitorear_cloudflare":        lambda inp, say, ch: monitorear_cloudflare(say, ch),
    "detener_monitoreo_cloudflare": lambda inp, say, ch: detener_monitoreo_cloudflare(),
    "monitorear_cve":               lambda inp, say, ch: monitorear_cve(say, ch),
    "detener_monitoreo_cve":        lambda inp, say, ch: detener_monitoreo_cve(),
}

# Estas herramientas muestran el resultado directo sin que Claude lo reformule
DIRECT_OUTPUT_TOOLS = {"jc_estadisticas", "jc_equipos_sin_conexion", "trend_alertas"}

TOOL_MESSAGES = {
    "consultar_software":      "🔍 Consultando versiones de software...",
    "consultar_usuario":       "👤 Consultando usuarios asignados...",
    "verificar_parches":       "🔎 Verificando parches instalados...",
    "enviar_comando":          "⚡ Enviando comando a los equipos...",
    "matchear_equipos":        "🔄 Comparando listas...",
    "jc_estadisticas":         "📊 Consultando inventario de JumpCloud...",
    "jc_estado_equipo":        "📊 Consultando estado en JumpCloud...",
    "jc_equipos_sin_conexion": "📡 Buscando equipos sin conexión...",
    "buscar_hostname":         "🔎 Buscando equipo...",
    "trend_alertas":           "🚨 Consultando alertas de Trend...",
    "trend_estado_endpoint":   "🔍 Consultando estado en Trend Vision One...",
    "trend_vulnerabilidades":  "🔍 Consultando vulnerabilidades en Trend...",
    "checklist_onboarding":    "✅ Verificando checklist de onboarding...",
    "generar_script":          "✍️ Generando script...",
    "lanzar_script_matches":        "⚙️ Lanzando script de matches...",
    "monitorear_cloudflare":        "📡 Iniciando monitoreo de Cloudflare Install...",
    "detener_monitoreo_cloudflare": "🛑 Deteniendo monitoreo...",
    "monitorear_cve":               "📡 Iniciando monitoreo de CVE-2026-50390...",
    "detener_monitoreo_cve":        "🛑 Deteniendo monitoreo de CVE...",
}


# ─── Slack handler ─────────────────────────────────────────────────────────────

ALLOWED_USERS = {"U0A1MN5Q66P", "U0ALDS9ARN3"}  # Amaury Peña, Lucia Rasini


def _eliminar_endpoint_trend(hostname: str) -> tuple[bool, str]:
    """Busca el endpoint en Trend por hostname y lo elimina. Devuelve (ok, mensaje)."""
    try:
        from agent.clients.trend_vision_one import TrendVisionOneClient
        from agent.core.config import get_settings
        settings = get_settings()
        with TrendVisionOneClient(settings) as client:
            agent_guid = None
            for item in client.fetch_collection("/v3.0/endpointSecurity/endpoints", {"pageSize": "100"}, max_pages=20):
                name = item.get("endpointName", "")
                if name.lower().split(".")[0] == hostname.lower().split(".")[0]:
                    agent_guid = item.get("agentGuid")
                    break
            if not agent_guid:
                return False, f"No encontrado en Trend: `{hostname}`"
            r = client._client.post(
                f"{client._base_url}/v3.0/endpointSecurity/endpoints/delete",
                json=[{"agentGuid": agent_guid}],
                timeout=20,
            )
            if r.status_code in (200, 202, 204, 207):
                return True, f"✅ `{hostname}` eliminado de Trend (agentGuid: `{agent_guid}`)"
            return False, f"Error al eliminar `{hostname}` de Trend: {r.status_code} {r.text[:200]}"
    except Exception as e:
        return False, f"Error: {e}"


@app.event({"type": "message", "subtype": "bot_message"})
def handle_bot_message(event, say):
    """Intercepta emails de JumpCloud que llegan via Slack Email Integration."""
    text_raw = event.get("text", "") or ""
    attachments = event.get("attachments", []) or []
    attach_text = " ".join(
        (a.get("text", "") or "") + " " + (a.get("fallback", "") or "")
        for a in attachments
    )
    full_text = (text_raw + " " + attach_text).strip()
    print(f"[bot_message] text={text_raw[:300]} attach={attach_text[:300]}")

    if (
        "endpoint eliminado" in full_text.lower() or
        "a device is removed" in full_text.lower()
    ):
        import re
        match = re.search(r"SYSTEM[:\s]+([A-Za-z0-9_\-\.]+)", full_text, re.IGNORECASE)
        if match:
            hostname = match.group(1).strip()
            say(f"📧 Email de JumpCloud detectado: endpoint eliminado `{hostname}`. Eliminando de Trend Vision One...")
            def _run_delete():
                ok, msg = _eliminar_endpoint_trend(hostname)
                say(msg)
            threading.Thread(target=_run_delete, daemon=True).start()
        else:
            print(f"[bot_message] JumpCloud email detectado pero no se pudo extraer hostname. full_text={full_text[:500]}")


@app.event("message")
def handle_message(event, say):
    print(f"[msg] user={event.get('user')} channel_type={event.get('channel_type')} subtype={event.get('subtype')} text={str(event.get('text',''))[:80]}", flush=True)
    # Interceptar emails de JumpCloud "Endpoint Eliminado" que llegan via Slack Email Integration
    text_raw = event.get("text", "") or ""
    attachments = event.get("attachments", []) or []
    attach_text = " ".join(
        (a.get("text", "") or "") + " " + (a.get("fallback", "") or "")
        for a in attachments
    )
    full_text = (text_raw + " " + attach_text).strip()

    # Log para debug de emails entrantes
    if event.get("bot_id"):
        print(f"[email_handler] bot_id={event.get('bot_id')} subtype={event.get('subtype')} text={text_raw[:200]} attachments={attachments[:2]}")

    if event.get("bot_id") and (
        "endpoint eliminado" in full_text.lower() or
        "a device is removed" in full_text.lower() or
        "jumpcloud notification" in full_text.lower()
    ):
        import re
        match = re.search(r"SYSTEM[:\s]+([A-Za-z0-9_\-\.]+)", full_text, re.IGNORECASE)
        if match:
            hostname = match.group(1).strip()
            say(f"📧 Email de JumpCloud detectado: endpoint eliminado `{hostname}`. Eliminando de Trend Vision One...")
            def _run_delete():
                ok, msg = _eliminar_endpoint_trend(hostname)
                say(msg)
            threading.Thread(target=_run_delete, daemon=True).start()
        return

    if event.get("bot_id"):
        return
    text = event.get("text", "").strip()
    if not text:
        return
    if event.get("user") not in ALLOWED_USERS:
        say("🔒 No tenés acceso a este bot.")
        return

    channel_id = event["channel"]

    # Correr en thread con timeout de 3 minutos
    result = [None]
    def _run():
        result[0] = _handle_message_inner(event, say, channel_id)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=180)
    if t.is_alive():
        say("⏱️ La operación tardó demasiado y fue cancelada. Intentá con menos máquinas o una consulta más específica.")


def _handle_message_inner(event, say, channel_id):
    text = event.get("text", "").strip()
    # Recuperar historial del canal
    history = conversation_history.setdefault(channel_id, [])
    history.append({"role": "user", "content": text})

    try:
        # Sanear historial: eliminar pares tool_use/tool_result incompletos o huérfanos
        def _clean_history(h):
            clean = []
            for msg in h:
                role = msg.get("role")
                content = msg.get("content")

                # Mensaje assistant con tool_use: solo agregar si el siguiente mensaje tiene los tool_results
                if role == "assistant" and isinstance(content, list):
                    tool_use_ids = {b.get("id") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"}
                    if tool_use_ids:
                        # Verificar que el mensaje siguiente (ya procesado) tenga los results — lo validamos al procesar el user
                        clean.append(msg)
                        continue

                # Mensaje user con tool_results: validar que todos tengan su tool_use en el anterior
                if role == "user" and isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    prev = clean[-1] if clean else None
                    if not prev or prev.get("role") != "assistant":
                        # No hay assistant previo — descartar este user y el anterior si existe
                        if clean and clean[-1].get("role") == "assistant":
                            clean.pop()
                        continue
                    prev_ids = {b.get("id") for b in (prev.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use"}
                    filtered = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result") or b.get("tool_use_id") in prev_ids]
                    if not filtered:
                        clean.pop()  # quitar assistant sin results
                        continue
                    clean.append({**msg, "content": filtered})
                    continue

                clean.append(msg)

            # Caso final: si el último mensaje es assistant con tool_use sin results → remover
            if clean and clean[-1].get("role") == "assistant":
                last_content = clean[-1].get("content") or []
                if isinstance(last_content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_use" for b in last_content
                ):
                    clean.pop()

            return clean

        history[:] = _clean_history(history)

        def _claude_call(msgs):
            return claude.messages.create(
                model=os.environ.get("AGENT_MODEL", "claude-sonnet-4-6"),
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=msgs,
                timeout=120,
            )

        response = _claude_call(history)

        # Loop hasta que Claude deje de pedir tools
        for _ in range(10):  # máximo 10 rondas
            if response.stop_reason != "tool_use":
                break

            tool_results = []
            has_direct = False
            for block in response.content:
                if block.type != "tool_use":
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                if not handler:
                    continue
                if block.name in TOOL_MESSAGES:
                    say(TOOL_MESSAGES[block.name])
                print(f"[TOOL] ejecutando {block.name} con {block.input}", flush=True)
                tool_result = handler(block.input, say, channel_id)
                print(f"[TOOL] {block.name} completado: {str(tool_result)[:100]}", flush=True)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result,
                })
                if block.name in DIRECT_OUTPUT_TOOLS:
                    say(tool_result)
                    has_direct = True

            if not tool_results:
                break

            history.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
            history.append({"role": "user", "content": tool_results})

            if has_direct:
                break

            print(f"[DEBUG] ronda siguiente con {len(tool_results)} tool_results", flush=True)
            response = _claude_call(history)
            print(f"[DEBUG] stop_reason={response.stop_reason}", flush=True)

        # Enviar respuesta final de texto
        if response.stop_reason != "tool_use":
            assistant_text = ""
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    assistant_text += block.text
            if assistant_text:
                say(assistant_text)
            history.append({"role": "assistant", "content": assistant_text})

        # Limitar historial a los últimos MAX_HISTORY mensajes
        if len(history) > MAX_HISTORY:
            conversation_history[channel_id] = history[-MAX_HISTORY:]

    except Exception as e:
        import traceback
        print(f"[ERROR handle_message] {e}", flush=True)
        traceback.print_exc()
        try:
            say(f"❌ Error interno: {e}")
        except Exception as say_err:
            print(f"[ERROR say] {say_err}", flush=True)


def _jumpcloud_email_poller():
    """Cada 2 minutos revisa el canal buscando emails nuevos de JumpCloud 'Endpoint Eliminado'
    y elimina automáticamente el endpoint de Trend Vision One."""
    import re, time as _time
    from slack_sdk import WebClient

    channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    if not channel_id:
        print("[jc_poller] SLACK_CHANNEL_ID no configurado", flush=True)
        return

    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

    # Persistir el último ts procesado para no perder emails si el bot se reinicia
    _ts_file = os.path.join(os.path.dirname(__file__), "data", "poller_last_ts.txt")
    os.makedirs(os.path.dirname(_ts_file), exist_ok=True)
    try:
        with open(_ts_file) as _f:
            last_ts = _f.read().strip()
        print(f"[jc_poller] Retomando desde ts={last_ts}", flush=True)
    except FileNotFoundError:
        # Primera vez: mirar las últimas 24 horas para no perder nada
        last_ts = str(time.time() - 86400)
        print(f"[jc_poller] Sin estado previo, arrancando desde hace 24h", flush=True)

    while True:
        _time.sleep(120)
        try:
            resp = client.conversations_history(
                channel=channel_id,
                oldest=last_ts,
                limit=20,
            )
            messages = resp.get("messages", [])
            if not messages:
                continue

            for msg in reversed(messages):  # del más viejo al más nuevo
                ts = msg.get("ts", "0")
                if float(ts) <= float(last_ts):
                    continue

                # Los emails llegan con text vacío y contenido en files[].filetype=email
                files = msg.get("files", []) or []
                email_files = [f for f in files if f.get("filetype") == "email"]
                if not email_files:
                    continue

                for ef in email_files:
                    title = ef.get("title", "") or ef.get("name", "")
                    if "endpoint eliminado" not in title.lower() and "device is removed" not in title.lower():
                        continue

                    # Leer contenido via files.info
                    file_id = ef.get("id", "")
                    try:
                        finfo = client.files_info(file=file_id)
                        plain = finfo["file"].get("plain_text", "") or finfo["file"].get("preview", "") or ""
                    except Exception as fe:
                        print(f"[jc_poller] error files.info: {fe}", flush=True)
                        plain = title

                    match = re.search(r"SYSTEM[:\s]+([A-Za-z0-9_\-\.]+)", plain, re.IGNORECASE)
                    if match:
                        hostname = match.group(1).strip()
                        print(f"[jc_poller] Detectado: {hostname}", flush=True)
                        client.chat_postMessage(
                            channel=channel_id,
                            text=f"📧 JumpCloud eliminó `{hostname}`. Eliminando de Trend Vision One..."
                        )
                        def _run_delete(hn=hostname):
                            ok, result_msg = _eliminar_endpoint_trend(hn)
                            client.chat_postMessage(channel=channel_id, text=result_msg)
                        threading.Thread(target=_run_delete, daemon=True).start()
                    else:
                        print(f"[jc_poller] Sin hostname en: {plain[:200]}", flush=True)

            # Actualizar cursor al mensaje más reciente
            if messages:
                last_ts = messages[0].get("ts", last_ts)
                try:
                    with open(_ts_file, "w") as _f:
                        _f.write(last_ts)
                except Exception:
                    pass

        except Exception as e:
            import traceback
            print(f"[jc_poller] error: {e}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    print("🤖 Endpoint Security Agent iniciando...")
    # Cache de Trend: carga inicial + refresh cada 5 min en background
    threading.Thread(target=_trend_cache_loop, daemon=True).start()
    # Hilo para el resumen diario
    threading.Thread(target=_daily_summary_loop, daemon=True).start()
    print("📅 Scheduler de resumen diario activo (09:00 GMT-3)")
    # Poller de emails JumpCloud "Endpoint Eliminado" → eliminar de Trend
    threading.Thread(target=_jumpcloud_email_poller, daemon=True).start()
    print("📬 Poller de emails JumpCloud activo (cada 2 min)", flush=True)
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
