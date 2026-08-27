from __future__ import annotations

import html
from typing import Any


def sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True).strip()

