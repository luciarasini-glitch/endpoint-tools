#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python3" "$ROOT/scripts/poll_command_results.py" --all --interval 30
