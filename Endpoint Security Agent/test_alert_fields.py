import httpx, json, os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
token = os.environ.get("TREND_VISION_ONE_API_TOKEN", "").strip()
headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

start = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
r = httpx.get("https://api.xdr.trendmicro.com/v3.0/workbench/alerts",
    headers=headers,
    params={"startDateTime": start, "orderBy": "createdDateTime desc", "top": 3},
    timeout=30)

data = r.json()
alerts = data.get("items", [])
print(f"Total: {len(alerts)} alertas\n")
for a in alerts:
    print("=== ALERT ===")
    print(json.dumps(a, indent=2))
    print()
