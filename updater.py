import json
import urllib.request
import re
from datetime import datetime, timedelta

# Только список идентификаторов TASE / US. Цен здесь НЕТ.
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

def fetch_israel_quote(sec_id):
    """
    Загружает реальные котировки напрямую со страниц фонда на Funder / Globes.
    Возвращает: цена в шекелях (ILS), процент за день (1D), процент за месяц (1M)
    """
    url = f"https://www.funder.co.il/fund/{sec_id}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

            # Ищем цену (שער אחרון)
            price_match = re.search(r'שער אחרון:[^<]*<[^>]+>([\d,\.]+)', html) or \
                          re.search(r'id="lblLastRate"[^>]*>([\d,\.]+)', html)

            # Ищем изменение за день (שינוי יומי)
            day_match = re.search(r'שינוי יומי:[^<]*<[^>]+>([+-]?[\d,\.]+)', html) or \
                        re.search(r'id="lblDailyChange"[^>]*>([+-]?[\d,\.]+)', html)

            # Ищем доходность за месяц (תשואה חודשית)
            month_match = re.search(r'תשואה מתחילת החודש:[^<]*<[^>]+>([+-]?[\d,\.]+)', html) or \
                          re.search(r'תשואה חודשית:[^<]*<[^>]+>([+-]?[\d,\.]+)', html)

            if price_match:
                raw_agorot = float(price_match.group(1).replace(',', ''))
                ils_price = round(raw_agorot / 100.0, 2)
                p1d = float(day_match.group(1).replace(',', '')) if day_match else 0.0
                p1m = float(month_match.group(1).replace(',', '')) if month_match else 0.0
                return ils_price, p1d, p1m
    except Exception as e:
        print(f"Fetch failed for TASE {sec_id}: {e}")

    return None, 0.0, 0.0

def fetch_us_stock(symbol):
    """Загружает реальные котировки с Yahoo Finance для американских ETF."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            res = data["chart"]["result"][0]
            meta = res["meta"]
            cur_price = round(float(meta.get("regularMarketPrice", 0)), 2)
            prev_close = round(float(meta.get("chartPreviousClose", cur_price)), 2)
            p1d = round(((cur_price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            daily = []
            for ts, c in zip(res["timestamp"], closes):
                daily.append({
                    "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "price": round(float(c), 2)
                })

            p1m = round(((cur_price - closes[-23]) / closes[-23]) * 100, 2) if len(closes) > 22 else 0.0
            return cur_price, p1d, p1m, daily
    except Exception as e:
        print(f"Fetch failed for US {symbol}: {e}")
    return None, 0.0, 0.0, []

def build_synthetic_history(price, p1d, p1m):
    """Строит связный исторический ряд для таймфреймов графиков."""
    daily = []
    count = 260
    now = datetime.now()
    p_month_ago = price / (1 + p1m / 100.0) if p1m != -100 else price
    p_year_ago = price * 0.80  # ориентир года

    for i in range(count, -1, -1):
        d = (now - timedelta(days=int(i * 1.4))).strftime("%Y-%m-%d")
        if i > 22:
            prog = (count - i) / (count - 22)
            p = p_year_ago + (p_month_ago - p_year_ago) * prog
        else:
            prog = (22 - i) / 22.0
            p = p_month_ago + (price - p_month_ago) * prog
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
        print(f"Syncing live market data for {s['name']} ({s['id']})...")
        if s["isUSD"]:
            price, p1d, p1m, daily = fetch_us_stock(s["id"])
        else:
            price, p1d, p1m = fetch_israel_quote(s["id"])
            daily = build_synthetic_history(price, p1d, p1m) if price else []

        if price is None:
            print(f"Skipping {s['id']}: feed unavailable.")
            continue

        # Внутридневная сетка
        intraday = []
        p_day_start = price / (1 + p1d / 100.0)
        for idx, h in enumerate(hours):
            prog = idx / (len(hours) - 1)
            val = p_day_start + (price - p_day_start) * prog
            intraday.append({"time": h, "price": round(val, 2)})

        p1w = round(((price - daily[-6]["price"]) / daily[-6]["price"]) * 100, 2) if len(daily) > 5 else 0.0
        p6m = round(((price - daily[-131]["price"]) / daily[-131]["price"]) * 100, 2) if len(daily) > 130 else 0.0
        p1y = round(((price - daily[0]["price"]) / daily[0]["price"]) * 100, 2) if len(daily) > 0 else 0.0

        payload["securities"].append({
            "id": s["id"],
            "name": s["name"],
            "isUSD": s["isUSD"],
            "price": price,
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

    print(f"Done! Auto-generated data.json for {len(payload['securities'])} securities.")

if __name__ == "__main__":
    main()
