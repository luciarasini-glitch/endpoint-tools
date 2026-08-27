"""AI agent: uses Claude to analyse endpoint security data and answer questions."""
from __future__ import annotations

import json
import logging
from typing import Any

from agent.core.config import Settings
from agent.models.domain import AgentEvent, AlertRecord, EndpointRecord

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an endpoint security analyst assistant for Cashea.
You have access to real-time data from Trend Micro Vision One (XDR) and JumpCloud.
Your job is to:
- Summarise security alerts and explain their risk in plain language.
- Identify patterns across endpoints and users.
- Recommend concrete, prioritised remediation actions.
- Answer ad-hoc questions about the current security posture.

Be concise and direct. When severity is high or critical, say so clearly first.\
"""


class SecurityAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = self._build_client()

    def _build_client(self) -> Any:
        try:
            import anthropic  # type: ignore[import-untyped]
            return anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        except ImportError:
            log.warning("anthropic package not installed — AI features disabled. Run: pip install anthropic")
            return None

    # ── Public ────────────────────────────────────────────────────────────────

    def ask(self, question: str, context: dict | None = None) -> str:
        """Send a question to Claude with optional security context."""
        if not self._client:
            return "[AI agent unavailable — anthropic package not installed]"
        if not self._settings.has_anthropic_key:
            return "[AI agent unavailable — ANTHROPIC_API_KEY not set]"

        messages = [{"role": "user", "content": self._build_user_message(question, context)}]
        response = self._client.messages.create(
            model=self._settings.agent_model,
            max_tokens=self._settings.agent_max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text

    def summarise_alerts(self, alerts: list[AlertRecord]) -> str:
        if not alerts:
            return "No alerts to summarise."
        context = {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "id": a.id,
                    "title": a.title,
                    "severity": a.severity,
                    "source": a.source,
                    "device": a.device_name,
                }
                for a in alerts[:20]
            ],
        }
        return self.ask("Summarise these security alerts and identify the top priorities.", context)

    def analyse_endpoint(self, endpoint: EndpointRecord, alerts: list[AlertRecord]) -> str:
        context = {
            "endpoint": {
                "hostname": endpoint.hostname,
                "platform": endpoint.platform,
                "os_version": endpoint.os_version,
                "last_seen": endpoint.last_seen.isoformat() if endpoint.last_seen else None,
                "risk_level": endpoint.risk_level,
            },
            "alert_count": len(alerts),
            "recent_alerts": [{"title": a.title, "severity": a.severity} for a in alerts[:5]],
        }
        return self.ask(f"Analyse the security posture of endpoint {endpoint.hostname}.", context)

    def triage_event(self, event: AgentEvent) -> str:
        return self.ask(
            f"Triage this security event and suggest an immediate action: {event.summary}",
            {"event": event.payload},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_user_message(question: str, context: dict | None) -> str:
        if not context:
            return question
        ctx_str = json.dumps(context, default=str, indent=2)
        return f"{question}\n\nContext:\n```json\n{ctx_str}\n```"
