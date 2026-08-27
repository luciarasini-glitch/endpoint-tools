from __future__ import annotations

import csv
import sys
from typing import Dict, List

from app.clients.jumpcloud import JumpCloudClient
from app.core.config import get_settings


EMAILS: List[str] = [
    "alejandromarquitti@cashea.app",
    "alejandronavarini@cashea.app",
    "alma@cashea.app",
    "bruno@cashea.app",
    "camilocamargo@cashea.app",
    "davidkruger@cashea.app",
    "dorihamrusso@cashea.app",
    "edwinrojas@cashea.app",
    "eng-marketplace@cashea.app",
    "eng-users@cashea.app",
    "erickortega@cashea.app",
    "federicoferreyra@cashea.app",
    "francisco@cashea.app",
    "francod@cashea.app",
    "frontend-team@cashea.app",
    "gabrielab@cashea.app",
    "germantellez@cashea.app",
    "javiersolis@cashea.app",
    "johnmartinez@cashea.app",
    "jorgedure@cashea.app",
    "josearmas@cashea.app",
    "joseortigoza@cashea.app",
    "jrmartinez@cashea.app",
    "juanaguirre@cashea.app",
    "juandonato@cashea.app",
    "juanrodriguez@cashea.app",
    "julianperez@cashea.app",
    "kennymeyer@cashea.app",
    "manuelmartinez@cashea.app",
    "marcosgonzalez@cashea.app",
    "mariasamudio@cashea.app",
    "martinpellicer@cashea.app",
    "miguelbelotto@cashea.app",
    "nicolasaraujo@cashea.app",
    "nicolaslopez@cashea.app",
    "npadros@cashea.app",
    "patriciorocca@cashea.app",
    "patriciorodriguez@cashea.app",
    "pedrocamargo@cashea.app",
    "rodrigosantaeulalia@cashea.app",
    "tomasvillamor@cashea.app",
    "victorrequena@cashea.app",
]


def build_user_email_index(users: List[dict]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for u in users:
        email = str(u.get("email") or "").strip().lower()
        user_id = str(u.get("id") or "").strip()
        if email and user_id:
            index[email] = user_id
    return index


def build_systems_by_user(systems: List[dict]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for s in systems:
        primary = s.get("primarySystemUser")
        if not isinstance(primary, dict):
            continue
        user_id = str(primary.get("id") or "").strip()
        if not user_id:
            continue
        hostname = str(s.get("displayName") or s.get("hostname") or "").strip()
        if not hostname:
            continue
        mapping.setdefault(user_id, []).append(hostname)
    return mapping


def main() -> int:
    settings = get_settings()
    client = JumpCloudClient(settings)

    try:
        users = client.list_all_users()
        systems = client.list_all_systems()
    except Exception as exc:
        print(f"Error consultando JumpCloud: {exc}", file=sys.stderr)
        return 2

    email_to_id = build_user_email_index(users)
    systems_by_user = build_systems_by_user(systems)

    writer = csv.writer(sys.stdout)
    writer.writerow(["email", "maquina"])

    for email in EMAILS:
        key = email.strip().lower()
        user_id = email_to_id.get(key)
        machines = []
        if user_id:
            machines = systems_by_user.get(user_id, [])
        writer.writerow([email, ";".join(machines)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
