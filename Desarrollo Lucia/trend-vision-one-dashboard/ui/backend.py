from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

if ENV_FILE.exists():
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean_key = key.strip()
        clean_value = value.strip()
        if clean_value:
            os.environ.setdefault(clean_key, clean_value)

app_backend_port = os.getenv("APP_BACKEND_PORT", "").strip()
backend_url = ""
if app_backend_port:
    backend_url = f"http://127.0.0.1:{app_backend_port}"
else:
    backend_url = os.getenv("BACKEND_URL", "").strip()
    if not backend_url:
        backend_url = "http://127.0.0.1:8000"

BACKEND_URL = backend_url.rstrip("/")
