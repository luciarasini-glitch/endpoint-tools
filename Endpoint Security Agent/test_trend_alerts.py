import httpx
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

token = os.environ.get("TREND_VISION_ONE_API_TOKEN", "").strip()
headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

start = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
r = httpx.get(
    "https://api.xdr.trendmicro.com/v3.0/workbench/alerts",
    headers=headers,
    params={"startDateTime": start, "orderBy": "createdDateTime desc", "top": 10},
    timeout=30,
)
print("Status:", r.status_code)
print("Response:", r.text[:2000])
