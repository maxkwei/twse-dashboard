import json
import time
import requests
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TWChipDashboard/1.0)"}

def get_tw_time():
    return datetime.utcnow() + timedelta(hours=8)

def get_target_date():
    now = get_tw_time()
    weekday = now.weekday()
    hour = now.hour
    if weekday == 6:
        target = now - timedelta(days=2)
    elif weekday == 5:
        target = now - timedelta(days=1)
    elif hour < 17:
        target = now - timedelta(days=1)
        while target.weekday() >= 5:
            target -= timedelta(days=1)
    else:
        target = now
    return target.strftime("%Y%m%d")

def fetch_json(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            d = r.json()
            if d.get("stat") == "OK" and "data" in d and d["data"]:
                return d
            return None
        except Exception:
            time.sl
