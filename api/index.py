import json
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

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
            r = requests.get(url, headers=HEADERS, timeout=8)
            r.raise_for_status()
            d = r.json()
            if d.get("stat") == "OK":
                return d
            return None

def to_num(v):
    try:
        return float(str(v).replace(",", ""))
    except:
        return 0.0

def fetch_institutional(date_str):
    url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
           f"?response=json&date={date_str}&selectType=ALL")
    d = fetch_json(url)
    if d is None:
        return []
    results = []
    for row in d["data"]:
        try:
            results.append({
                "code":    str(row[0]).strip(),
                "name":    str(row[1]).strip(),
                "foreign": round(to_num(row[4])  / 1000) if len(row) > 4  else 0,
                "trust":   round(to_num(row[7])  / 1000) if len(row) > 7  else 0,
                "dealer":  round(to_num(row[10]) / 1000) if len(row) > 10 else 0,
            })
        except Exception:
            continue
    return results

def fetch_margin(date_str):
    url = (f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
           f"?response=json&date={date_str}&selectType=ALL")
    d = fetch_json(url)
    if d is None:
        return {}
    # API 回傳兩個 table，第二個（index 1）才是個股融資融券彙總
    tables = d.get("tables", [])
    if len(tables) < 2:
        return {}
    table2 = tables[1]
    rows = table2.get("data", [])
    if not rows:
        return {}
    margin = {}
    for row in rows:
        try:
            if len(row) < 13:
                continue
            code = str(row[0]).strip().lstrip("0") or str(row[0]).strip()
            code_orig = str(row[0]).strip()
            margin[code] = {
                "loan_buy":   to_num(row[2])  if len(row) > 2  else 0,
                "loan_sell":  to_num(row[3])  if len(row) > 3  else 0,
                "loan_bal":   to_num(row[6])  if len(row) > 6  else 0,
                "short_sell": to_num(row[9])  if len(row) > 9  else 0,
                "short_buy":  to_num(row[8])  if len(row) > 8  else 0,
                "short_bal":  to_num(row[12]) if len(row) > 12 else 0,
            }
        except Exception:
            continue
    return margin

def fetch_history(stock_id, months=2):
    today = datetime.today()
    frames = []
    for i in range(months - 1, -1, -1):
        dt = today - timedelta(days=30 * i)
        url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
               f"?response=json&date={dt.strftime('%Y%m%d')}&stockNo={stock_id}")
        d = fetch_json(url)
        if d:
            for row in d["data"]:
                try:
                    p = row[0].split("/")
                    date = f"{int(p[0])+1911}/{p[1]}/{p[2]}"
                    frames.append({
                        "date":  date,
                        "open":  to_num(row[3]),
                        "high":  to_num(row[4]),
                        "low":   to_num(row[5]),
                        "close": to_num(row[6]),
                        "vol":   round(to_num(row[1]) / 1000),
                    })
                except Exception:
                    continue
        time.sleep(0.3)
    seen = set()
    result = []
    for r in frames:
        if r["date"] not in seen:
            seen.add(r["date"])
            result.append(r)
    return sorted(result, key=lambda x: x["date"])


app = Flask(__name__)

@app.route("/api/chips")
def chips():
    stock_id = request.args.get("stock", "2330").strip()
    date_str = get_target_date()
    now_tw   = get_tw_time()

    inst_all   = fetch_institutional(date_str)
    margin_all = fetch_margin(date_str)
    history    = fetch_history(stock_id, months=2)

    stock_inst   = next((r for r in inst_all if r["code"] == stock_id), None)
    stock_margin = margin_all.get(stock_id, {})
    if not stock_margin:
        # 嘗試補零比對
        for k in margin_all:
            if k.strip() == stock_id.strip():
                stock_margin = margin_all[k]
                break

    if stock_inst:
        total = stock_inst["foreign"] + stock_inst["trust"] + stock_inst["dealer"]
        stock_inst["total"] = total
        fb    = stock_margin.get("loan_bal", 0)
        sb    = stock_margin.get("short_bal", 0)
        ratio = round(sb / fb * 100, 1) if fb > 0 else 0
        f, t, d = stock_inst["foreign"], stock_inst["trust"], stock_inst["dealer"]
        signals = []
        if f > 1000:    signals.append({"text": "外資大買超(>1000張)", "type": "bull"})
        elif f < -1000: signals.append({"text": "外資大賣超(>1000張)", "type": "bear"})
        elif f > 0:     signals.append({"text": "外資買超", "type": "bull"})
        elif f < 0:     signals.append({"text": "外資賣超", "type": "bear"})
        if t > 200:     signals.append({"text": "投信積極布局(>200張)", "type": "bull"})
        elif t > 0:     signals.append({"text": "投信買超", "type": "bull"})
        elif t < 0:     signals.append({"text": "投信賣超", "type": "warn"})
        if f > 0 and t > 0 and d > 0:
            signals.append({"text": "三大法人同步買超", "type": "bull"})
        elif f < 0 and t < 0 and d < 0:
            signals.append({"text": "三大法人同步賣超", "type": "bear"})
        if ratio > 25:
            signals.append({"text": f"券資比{ratio}%，留意軋空", "type": "warn"})
    else:
        total = ratio = 0
        signals = [{"text": "查無法人資料", "type": "warn"}]

    response = {
        "stock_id":    stock_id,
        "name":        stock_inst["name"] if stock_inst else stock_id,
        "date":        date_str,
        "update_time": now_tw.strftime("%Y/%m/%d %H:%M") + " CST",
        "inst": {
            "foreign": stock_inst["foreign"] if stock_inst else 0,
            "trust":   stock_inst["trust"]   if stock_inst else 0,
            "dealer":  stock_inst["dealer"]  if stock_inst else 0,
            "total":   total,
        },
        "margin": {
            "loan_bal":   stock_margin.get("loan_bal",   0),
            "short_bal":  stock_margin.get("short_bal",  0),
            "short_sell": stock_margin.get("short_sell", 0),
            "ratio":      ratio,
        },
        "signals": signals,
        "history": history,
    }

    resp = jsonify(response)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


if __name__ == "__main__":
    app.run(debug=True)
