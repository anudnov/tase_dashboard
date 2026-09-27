import json
import urllib.request
from datetime import datetime

SECURITIES = [
    {"id": "1159250", "name": "iShares Core S&P 500", "isUSD": False},
    {"id": "1146505", "name": "KSM ETF NASDAQ 100", "isUSD": False},
    {"id": "1183441", "name": "Invesco S&P 500 UCITS", "isUSD": False},
    {"id": "5122957", "name": "Kessem S&P 500 Hedged", "isUSD": False},
    {"id": "5133574", "name": "Harel Nasdaq Hedged", "isUSD": False},
    {"id": "5140165", "name": "MTF MSCI World Hedged", "isUSD": False},
    {"id": "5117759", "name": "Ayalon S&P 500 x3", "isUSD": False},
    {"id": "5117684", "name": "Ayalon TA-125 x3", "isUSD": False},
    {"id": "MAGS", "name": "Roundhill Mag 7 ETF", "isUSD": True},
]

def fetch_ticker_data(symbol):
    ticker = symbol if symbol == "MAGS" else f"{symbol}.TA"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
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
                    d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    daily.append({"date": d, "price": round(float(close), 2)})
            return daily
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []

def main():
    payload = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "securities": []
    }

    for sec in SECURITIES:
        print(f"Processing {sec['id']}...")
        daily = fetch_ticker_data(sec["id"])
        if not daily:
            continue

        latest = daily[-1]["price"]
        prev_1d = daily[-2]["price"] if len(daily) > 1 else latest
        prev_1w = daily[-6]["price"] if len(daily) > 5 else latest
        prev_1m = daily[-22]["price"] if len(daily) > 21 else latest
        prev_6m = daily[-130]["price"] if len(daily) > 129 else latest
        prev_1y = daily[0]["price"]

        def calc_pct(cur, base):
            return round(((cur - base) / base) * 100, 2)

        sec_data = {
            "id": sec["id"],
            "name": sec["name"],
            "isUSD": sec["isUSD"],
            "price": latest,
            "p1d": calc_pct(latest, prev_1d),
            "p1w": calc_pct(latest, prev_1w),
            "p1m": calc_pct(latest, prev_1m),
            "p6m": calc_pct(latest, prev_6m),
            "p1y": calc_pct(latest, prev_1y),
            "daily": daily[-260:]  # последние 260 торговых сессий (~1 год)
        }
        payload["securities"].append(sec_data)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("data.json successfully written.")

if __name__ == "__main__":
    main()
