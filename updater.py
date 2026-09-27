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

def fetch_history(symbol, is_usd):
    ticker = symbol if is_usd else f"{symbol}.TA"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            res = data["chart"]["result"][0]
            timestamps = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]

            daily = []
            for ts, close in zip(timestamps, closes):
                if close is not None:
                    d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    # Перевод агорот TASE в шекели ₪
                    final_price = round(float(close) / 100.0, 2) if not is_usd else round(float(close), 2)
                    daily.append({"date": d, "price": final_price})
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
        print(f"Syncing {sec['id']}...")
        daily = fetch_history(sec["id"], sec["isUSD"])
        if not daily:
            continue

        latest_price = daily[-1]["price"]
        prev_price = daily[-2]["price"] if len(daily) > 1 else latest_price

        # Внутридневная сетка для графика 1D
        hours = ['10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:15']
        intraday = []
        for i, h in enumerate(hours):
            prog = i / (len(hours) - 1)
            val = prev_price + (latest_price - prev_price) * prog
            intraday.append({"time": h, "price": round(val, 2)})

        sec_entry = {
            "id": sec["id"],
            "name": sec["name"],
            "isUSD": sec["isUSD"],
            "price": latest_price,
            "daily": daily[-260:],
            "intraday": intraday
        }
        payload["securities"].append(sec_entry)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("data.json successfully generated.")

if __name__ == "__main__":
    main()
