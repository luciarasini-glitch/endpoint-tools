"""CLI entry point for the Endpoint Security Agent.

Usage examples:
  python -m agent.cli.main status
  python -m agent.cli.main alerts
  python -m agent.cli.main endpoints
  python -m agent.cli.main ask "What are the critical alerts?"
  python -m agent.cli.main monitor
"""
from __future__ import annotations

import argparse
import json
import sys

from agent.core.config import get_settings
from agent.core.logging import configure_logging


def cmd_status(args: argparse.Namespace) -> None:
    s = get_settings()
    print("\n=== Endpoint Security Agent — Status ===\n")
    print(f"  Region          : {s.app_region}")
    print(f"  Base URL        : {s.resolved_base_url}")
    print(f"  Trend token     : {'✓ set' if s.has_trend_token else '✗ missing'}")
    print(f"  JumpCloud token : {'✓ set' if s.has_jumpcloud_token else '✗ missing'}")
    print(f"  Anthropic key   : {'✓ set' if s.has_anthropic_key else '✗ missing'}")
    print(f"  Agent model     : {s.agent_model}")
    print(f"  Monitor interval: {s.monitor_poll_interval_seconds}s")
    print()


def cmd_alerts(args: argparse.Namespace) -> None:
    s = get_settings()
    if not s.has_trend_token:
        print("ERROR: TREND_VISION_ONE_API_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)

    from agent.clients.trend_vision_one import TrendVisionOneClient
    path = s.trend_vision_one_workbench_alerts_path or "/v3.0/workbench/alerts"
    print(f"\nFetching workbench alerts from {path} ...\n")

    with TrendVisionOneClient(s) as client:
        items = list(client.fetch_collection(path, {"top": str(args.limit)}))

    if not items:
        print("No alerts found.")
        return

    for item in items:
        alert_id = item.get("id") or item.get("workbenchId", "?")
        title = item.get("description") or item.get("title", "—")
        severity = item.get("severity", "?")
        print(f"  [{severity.upper():8}] {alert_id[:8]}  {title}")
    print(f"\n{len(items)} alert(s) returned.\n")


def cmd_endpoints(args: argparse.Namespace) -> None:
    s = get_settings()
    if not s.has_trend_token:
        print("ERROR: TREND_VISION_ONE_API_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)

    from agent.clients.trend_vision_one import TrendVisionOneClient
    path = s.trend_vision_one_endpoints_path or "/v3.0/endpointSecurity/endpoints"
    print(f"\nFetching endpoint inventory from {path} ...\n")

    with TrendVisionOneClient(s) as client:
        items = list(client.fetch_collection(path, {"top": str(args.limit)}))

    if not items:
        print("No endpoints found.")
        return

    for item in items:
        hostname = item.get("endpointName") or item.get("displayName") or item.get("id", "?")
        platform = item.get("osName") or item.get("platform", "?")
        last_seen = item.get("lastConnectedDateTime") or item.get("lastSeen", "?")
        print(f"  {hostname:30} {platform:15} last: {last_seen}")
    print(f"\n{len(items)} endpoint(s) returned.\n")


def cmd_ask(args: argparse.Namespace) -> None:
    s = get_settings()
    if not s.has_anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    from agent.services.ai_agent import SecurityAgent
    agent = SecurityAgent(s)
    print(f"\nAsking: {args.question}\n")
    answer = agent.ask(args.question)
    print(answer)
    print()


def cmd_monitor(args: argparse.Namespace) -> None:
    s = get_settings()
    if not s.has_trend_token:
        print("ERROR: TREND_VISION_ONE_API_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)

    from agent.services.monitor import MonitorService
    monitor = MonitorService(s)

    if args.once:
        events = monitor.run_once()
        print(f"\n{len(events)} new event(s) detected.\n")
        for e in events:
            print(f"  [{e.severity.upper():8}] {e.summary}")
        print()
    else:
        print(f"\nStarting monitor (interval={s.monitor_poll_interval_seconds}s). Ctrl+C to stop.\n")
        monitor.run_loop()


def main() -> None:
    configure_logging(get_settings().app_log_level)

    parser = argparse.ArgumentParser(
        prog="endpoint-security-agent",
        description="Endpoint Security Agent — CLI for Trend Vision One + JumpCloud",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show current config and connectivity status")

    p_alerts = sub.add_parser("alerts", help="Fetch recent workbench alerts")
    p_alerts.add_argument("--limit", type=int, default=20, help="Max alerts to fetch (default 20)")

    p_ep = sub.add_parser("endpoints", help="List endpoint inventory")
    p_ep.add_argument("--limit", type=int, default=50, help="Max endpoints to fetch (default 50)")

    p_ask = sub.add_parser("ask", help="Ask the AI agent a security question")
    p_ask.add_argument("question", help="Question to ask")

    p_mon = sub.add_parser("monitor", help="Run the background monitor")
    p_mon.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")

    args = parser.parse_args()

    dispatch = {
        "status": cmd_status,
        "alerts": cmd_alerts,
        "endpoints": cmd_endpoints,
        "ask": cmd_ask,
        "monitor": cmd_monitor,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
