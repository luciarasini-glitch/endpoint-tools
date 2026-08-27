"""
Polling de resultados de comandos JumpCloud.
Modo --all: monitorea TODOS los comandos automáticamente.
Modo por IDs: monitorea command IDs específicos.

Uso:
    python scripts/poll_command_results.py --all [--interval 30]
    python scripts/poll_command_results.py <id1> <id2> ... [--interval 30]

Guarda los IDs ya notificados en /tmp/jc_cmd_all.json para no repetir.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agent.core.config import get_settings


def fetch_results_since(api_key: str, since_iso: str) -> list[dict]:
    """Trae todos los resultados con responseTime >= since_iso, paginando hasta agotar.

    Filtra por responseTime (cuándo llegó el resultado) en vez de requestTime
    (cuándo se envió el comando), para no perder resultados de comandos enviados
    antes de que arrancara el polling pero que respondieron después.
    """
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    results = []
    skip = 0
    while True:
        r = httpx.get(
            "https://console.jumpcloud.com/api/commandresults",
            headers=headers,
            params={"limit": 100, "skip": skip, "sort": "-responseTime"},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("results", [])
        if not items:
            break
        found_older = False
        for item in items:
            if item.get("responseTime", "") >= since_iso:
                results.append(item)
            else:
                found_older = True
        if found_older or len(items) < 100:
            break
        skip += 100
    return results


def fetch_results_by_id(api_key: str, command_id: str) -> list[dict]:
    """Trae todos los resultados de un command_id específico."""
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    matched = []
    skip = 0
    while True:
        r = httpx.get(
            "https://console.jumpcloud.com/api/commandresults",
            headers=headers,
            params={"limit": 100, "skip": skip, "sort": "-requestTime"},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("results", [])
        if not items:
            break
        matched.extend([i for i in items if i.get("workflowId") == command_id])
        if len(items) < 100:
            break
        skip += 100
    return matched


def fetch_full_result(api_key: str, result_id: str) -> dict:
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    r = httpx.get(
        f"https://console.jumpcloud.com/api/commandresults/{result_id}",
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def send_slack(webhook_url: str, bot_token: str, channel_id: str, result: dict) -> None:
    resp_data   = result.get("response", {}).get("data", {}) or {}
    exit_code   = result.get("exitCode") if result.get("exitCode") is not None else resp_data.get("exitCode", -1)
    system      = result.get("system", result.get("systemId", "—"))
    name        = result.get("name", "—")
    resp_time   = result.get("responseTime", "")[:16].replace("T", " ")
    output      = (resp_data.get("output") or "").strip()
    error       = (result.get("response", {}).get("error") or "").strip()

    status_icon = "✅" if exit_code == 0 else "❌"
    summary = f"{status_icon} *{name}* — `{system}`\n🕐 {resp_time}   |   Exit code: `{exit_code}`"

    # Combinar output + error en el archivo adjunto para tener el log completo
    parts = []
    if output:
        parts.append(output)
    if error:
        parts.append(error)
    full_log = "\n".join(parts) if parts else "(sin output)"

    if bot_token and channel_id:
        try:
            filename = f"{system}_{resp_time[:10]}_exit{exit_code}.txt"
            content  = full_log.encode("utf-8")
            r1 = httpx.post(
                "https://slack.com/api/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {bot_token}"},
                data={"filename": filename, "length": len(content)},
                timeout=15,
            )
            d1 = r1.json()
            if d1.get("ok"):
                httpx.post(d1["upload_url"], content=content, timeout=30)
                r3 = httpx.post(
                    "https://slack.com/api/files.completeUploadExternal",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    json={"files": [{"id": d1["file_id"]}], "channel_id": channel_id, "initial_comment": summary},
                    timeout=15,
                )
                if r3.json().get("ok"):
                    return
        except Exception:
            pass

    if webhook_url:
        try:
            httpx.post(webhook_url, json={"text": summary + "\n```" + full_log[-3000:] + "```"}, timeout=10)
        except Exception:
            pass


def load_seen(state_file: Path) -> set[str]:
    if state_file.exists():
        try:
            return set(json.loads(state_file.read_text()))
        except Exception:
            pass
    return set()


def save_seen(state_file: Path, seen: set[str]) -> None:
    state_file.write_text(json.dumps(list(seen)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command_ids", nargs="*", help="IDs específicos (omitir con --all)")
    parser.add_argument("--all", action="store_true", help="Monitorear todos los comandos")
    parser.add_argument("--interval", type=int, default=30, help="Segundos entre polls (default: 30)")
    args = parser.parse_args()

    settings    = get_settings()
    api_key     = settings.jumpcloud_api_key.strip() if hasattr(settings, "jumpcloud_api_key") else ""
    webhook_url = settings.slack_webhook_url.strip()
    bot_token   = settings.slack_bot_token.strip()
    channel_id  = settings.slack_channel_id.strip()

    if not api_key:
        print("ERROR: JUMPCLOUD_API_KEY no configurado en .env")
        sys.exit(1)

    if not args.all and not args.command_ids:
        print("ERROR: pasá al menos un command_id o usá --all")
        sys.exit(1)

    watch_all  = args.all
    state_file = Path("/tmp/jc_cmd_all.json") if watch_all else None

    # State file para --all guarda {"seen": [...], "since": "ISO timestamp"}
    if watch_all:
        raw_state = {}
        if state_file.exists():
            try:
                raw_state = json.loads(state_file.read_text())
            except Exception:
                pass
        seen = set(raw_state.get("seen", []))
        since_iso = raw_state.get("since", "")

        if not since_iso:
            print("Primera ejecución en modo --all: marcando timestamp de inicio...")
            since_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            state_file.write_text(json.dumps({"seen": list(seen), "since": since_iso}))
            print(f"  Solo se notificarán resultados desde {since_iso} UTC en adelante")
        else:
            print(f"Modo --all | desde {since_iso} UTC | {len(seen)} ya vistos | polling cada {args.interval}s")
    else:
        print(f"Polling {len(args.command_ids)} comando(s) cada {args.interval}s")
        for cid in args.command_ids:
            s = load_seen(Path(f"/tmp/jc_cmd_{cid}.json"))
            print(f"  {cid} — {len(s)} ya vistos")

    print("Ctrl+C para detener\n")

    try:
        while True:
            total_new = 0
            try:
                if watch_all:
                    raw_state = json.loads(state_file.read_text()) if state_file.exists() else {}
                    seen      = set(raw_state.get("seen", []))
                    since_iso = raw_state.get("since", "")
                    results   = fetch_results_since(api_key, since_iso)
                    new_results = [r for r in results if r["_id"] not in seen]
                    for result in new_results:
                        rid    = result["_id"]
                        system = result.get("system", "?")
                        name   = result.get("name", "?")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Nuevo: {name} — {system}")
                        try:
                            full = fetch_full_result(api_key, rid)
                        except Exception:
                            full = result
                        send_slack(webhook_url, bot_token, channel_id, full)
                        seen.add(rid)
                        total_new += 1
                    if new_results:
                        state_file.write_text(json.dumps({"seen": list(seen), "since": since_iso}))
                else:
                    for cid in args.command_ids:
                        sf   = Path(f"/tmp/jc_cmd_{cid}.json")
                        seen = load_seen(sf)
                        for result in fetch_results_by_id(api_key, cid):
                            rid = result["_id"]
                            if rid in seen:
                                continue
                            system = result.get("system", "?")
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{cid[:8]}] Nuevo: {system}")
                            try:
                                full = fetch_full_result(api_key, rid)
                            except Exception:
                                full = result
                            send_slack(webhook_url, bot_token, channel_id, full)
                            seen.add(rid)
                            save_seen(sf, seen)
                            total_new += 1

            except Exception as exc:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {exc}")

            if total_new == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sin nuevos resultados")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    main()
