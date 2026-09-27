import json
import urllib.request
from datetime import datetime, timedelta

SECURITIES = [
    {"id": "1159250", "name": "iShares Core S&P 500", "isUSD": False, "base_price": 2522.00, "p1d": -0.20, "p1w": 1.21, "p1m": 2.11, "p6m": 13.66, "p1y": 26.40},
    {"id": "1146505", "name": "KSM ETF NASDAQ 100", "isUSD": False, "base_price": 851.60, "p1d": -0.15, "p1w": 1.21, "p1m": 2.40, "p6m": 15.69, "p1y": 31.50},
    {"id": "1183441", "name": "Invesco S&P 500 UCITS", "isUSD": False, "base_price": 46.59, "p1d": -0.20, "p1w": 1.22, "p1m": 2.10, "p6m": 13.55, "p1y": 26.09},
    {"id": "5122957", "name": "Kessem S&P 500 Hedged", "isUSD": False, "base_price": 14.20, "p1d": 0.10, "p1w": 1.21, "p1m": 1.50, "p6m": 8.40, "p1y": 13.78},
    {"id": "5133574", "name": "Harel Nasdaq Hedged", "isUSD": False, "base_price": 16.80, "p1d": 0.15, "p1w": 1.20, "p1m": 1.82, "p6m": 9.88, "p1y": 16.99},
    {"id": "5140165", "name": "MTF MSCI World Hedged", "isUSD": False, "base_price": 13.10, "p1d": 0.05, "p1w": 1.24, "p1m": 1.24, "p6m": 8.26, "p1y": 14.11},
    {"id": "5117759", "name": "Ayalon S&P 500 x3", "isUSD": False, "base_price": 21.90, "p1d": -0.60, "p1w": 1.20, "p1m": 5.49, "p6m": 18.89, "p1y": 34.52},
    {"id": "5117684", "name": "Ayalon TA-125 x3", "isUSD": False, "base_price": 19.80, "p1d": 0.40, "p1w": 1.23, "p1m": 3.99, "p6m": 20.36, "p1y": 42.04},
    {"id": "MAGS", "name": "Roundhill Mag 7 ETF", "isUSD": True, "base_price": 72.64, "p1d": 0.18, "p1w": 3.09, "p1m": 7.44, "p6m": 24.45, "p1y": 12.71}
]

def fetch_mags():
    """Загрузка живой истории MAGS с Yahoo Finance."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/MAGS?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            res = data["chart"]["result"][0]
            timestamps = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            daily = []
            for ts, close in zip(timestamps, closes):
                if close is not None:
                    daily.append({
                        "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                        "price": round(float(close), 2)
                    })
            if daily:
                latest = daily[-1]["price"]
                p1d = round(((latest - daily[-2]["price"]) / daily[-2]["price"]) * 100, 2) if len(daily) > 1 else 0.18
                p1w = round(((latest - daily[-6]["price"]) / daily[-6]["price"]) * 100, 2) if len(daily) > 5 else 3.09
                p1m = round(((latest - daily[-23]["price"]) / daily[-23]["price"]) * 100, 2) if len(daily) > 22 else 7.44
                p6m = round(((latest - daily[-131]["price"]) / daily[-131]["price"]) * 100, 2) if len(daily) > 130 else 24.45
                p1y = round(((latest - daily[0]["price"]) / daily[0]["price"]) * 100, 2)
                return latest, p1d, p1w, p1m, p6m, p1y, daily
    except Exception as e:
        print(f"Error fetching MAGS: {e}")
    return None

def generate_curve(price, p1y_pct, p1m_pct):
    """Генерация полной математической кривой за 260 торговых дней."""
    daily = []
    count = 260
    now = datetime.now()
    p_start = price / (1 + p1y_pct / 100.0)
    p_m_start = price / (1 + p1m_pct / 100.0)

    for i in range(count, -1, -1):
        d = (now - timedelta(days=int(i * 1.4))).strftime("%Y-%m-%d")
        if i > 22:
            prog = (count - i) / (count - 22)
            p = p_start + (p_m_start - p_start) * prog
        else:
            prog = (22 - i) / 22.0
            p = p_m_start + (price - p_m_start) * prog
        daily.append({"date": d, "price": round(float(p), 2)})
    daily[-1]["price"] = price
    return daily

def main():
    payload = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "securities": []
    }

    hours = ['10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:15']

    for s in SECURITIES:
        cur_price = s["base_price"]
        p1d = s["p1d"]
        p1w = s["p1w"]
        p1m = s["p1m"]
        p6m = s["p6m"]
        p1y = s["p1y"]
        daily = []

        if s["id"] == "MAGS":
            mags_res = fetch_mags()
            if mags_res:
                cur_price, p1d, p1w, p1m, p6m, p1y, daily = mags_res

        if not daily:
            daily = generate_curve(cur_price, p1y, p1m)

        # Сетка интрадей
        intraday = []
        p_day_start = cur_price / (1 + p1d / 100.0)
        for idx, h in enumerate(hours):
            prog = idx / (len(hours) - 1)
            val = p_day_start + (cur_price - p_day_start) * prog
            intraday.append({"time": h, "price": round(val, 2)})

        payload["securities"].append({
            "id": s["id"],
            "name": s["name"],
            "isUSD": s["isUSD"],
            "price": cur_price,
            "p1d": p1d,
            "p1w": p1w,
            "p1m": p1m,
            "p6m": p6m,
            "p1y": p1y,
            "daily": daily,
            "intraday": intraday
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Successfully generated data.json with ALL {len(payload['securities'])} securities.")

if __name__ == "__main__":
    main()
