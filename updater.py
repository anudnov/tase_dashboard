import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta

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

def fetch_tase_eod(security_id):
    """Получение официальной истории торгов напрямую с биржи TASE."""
    today = datetime.now()
    one_year_ago = today - timedelta(days=380)

    url = "https://market.tase.co.il/api-weight/security/history"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": f"https://market.tase.co.il/he/market_data/security/{security_id}/historical_data"
    }

    payload = {
        "SecurityId": str(security_id).zfill(8),
        "DateFrom": one_year_ago.strftime("%Y-%m-%d"),
        "DateTo": today.strftime("%Y-%m-%d"),
        "Language": "he"
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            rows = data.get("HistoryData", [])
            if not rows:
                return []

            # Сортируем от старых дат к новым
            rows.sort(key=lambda x: x.get("TradeDate", ""))

            daily = []
            for r in rows:
                close_price = r.get("CloseRate") or r.get("ClosingPrice") or r.get("Price")
                date_str = r.get("TradeDate", "")[:10]
                if close_price and date_str:
                    # TASE передает котировки в агорот -> делим на 100 для шекелей ₪
                    ils_price = round(float(close_price) / 100.0, 2)
                    daily.append({"date": date_str, "price": ils_price})
            return daily
    except Exception as e:
        print(f"Error fetching TASE {security_id}: {e}")
        return []

def fetch_us_stock(symbol):
    """Для американских ETF (MAGS) через Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
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
                    daily.append({"date": d, "price": round(float(close), 2)})
            return daily
    except Exception as e:
        print(f"Error fetching US stock {symbol}: {e}")
        return []

def main():
    result = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "securities": []
    }

    for sec in SECURITIES:
        print(f"Syncing {sec['name']} ({sec['id']})...")
        if sec["isUSD"]:
            daily = fetch_us_stock(sec["id"])
        else:
            daily = fetch_tase_eod(sec["id"])

        if not daily:
            print(f"Warning: No live data returned for {sec['id']}, skipping...")
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

        result["securities"].append({
            "id": sec["id"],
            "name": sec["name"],
            "isUSD": sec["isUSD"],
            "price": latest_price,
            "daily": daily[-260:],
            "intraday": intraday
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Successfully processed {len(result['securities'])} securities into data.json")

if __name__ == "__main__":
    main()
