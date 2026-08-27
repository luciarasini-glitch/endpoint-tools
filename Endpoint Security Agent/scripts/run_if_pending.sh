#!/bin/bash
# Wrapper para todos los crons del Endpoint Security Agent.
# Corre el script indicado si no se ejecutó en la semana actual (lunes a domingo).
# Uso: run_if_pending.sh <report_key> <script_path>
#
# Si la Mac estaba apagada el lunes, este wrapper detecta la tarea pendiente
# y la ejecuta en cuanto la máquina enciende.

REPORT_KEY="$1"
SCRIPT_PATH="$2"

if [ -z "$REPORT_KEY" ] || [ -z "$SCRIPT_PATH" ]; then
    echo "Uso: run_if_pending.sh <report_key> <script_path>"
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
META_FILE="$ROOT/reports/.meta.json"
PYTHON="$ROOT/.venv/bin/python"

# Calcular el lunes de la semana actual en hora local (YYYY-MM-DD)
MONDAY=$(python3 -c "
from datetime import date, timedelta
today = date.today()
monday = today - timedelta(days=today.weekday())
print(monday.isoformat())
")

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verificando $REPORT_KEY — semana del $MONDAY"

# Leer la fecha de última generación del meta.json, convirtiendo a hora local
if [ -f "$META_FILE" ]; then
    LAST_RUN=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    meta = json.load(open('$META_FILE'))
    ts = meta.get('$REPORT_KEY', {}).get('generated_at', '')
    if ts:
        # Parsear timestamp con o sin timezone y convertir a fecha local
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            print(dt.date().isoformat())
        except Exception:
            print(ts[:10])
    else:
        print('')
except:
    print('')
")
else
    LAST_RUN=""
fi

# Calcular si last_run es >= lunes de esta semana
ALREADY_RAN=$(python3 -c "
from datetime import date
last = '$LAST_RUN'
monday = '$MONDAY'
if last and last >= monday:
    print('yes')
else:
    print('no')
")

if [ "$ALREADY_RAN" = "yes" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $REPORT_KEY ya corrió esta semana ($LAST_RUN). Saltando."
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] $REPORT_KEY pendiente — ejecutando..."
cd "$ROOT"
"$PYTHON" "$SCRIPT_PATH"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] $REPORT_KEY finalizado."
