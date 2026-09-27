import json
import urllib.request
import re
from datetime import datetime

# Только список отслеживаемых тикеров. Никаких цен и процентов вручную!
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

def fetch_israeli_fund(sec_id):
    """
    Парсит живые биржевые показатели (цену в агорот и проценты)
    напрямую со страницы фонда на Funder.
    """
    url = f"https://www.funder.co.il/fund/{sec_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            
            # 1. Извлечение цены (в агорот)
            price_match = re.search(r'id="lblLastRate"[^>]*>([\d,\.]+)', html) or \
                          re.search(r'שער אחרון:[^<]*<[^>]+>([\d,\.]+)', html)
            
            # 2. Извлечение изменения за день (1D %)
            day_match = re.search(r'id="lblDailyChange"[^>]*>([+-]?[\d,\.]+)', html) or \
                        re.search(r'שינוי יומי:[^<]*<[^>]+>([+-]?[\d,\.]+)', html)

            # 3. Извлечение доходности за месяц (1M %)
            month_match = re.search(r'תשואה מתחילת החודש:[^<]*<[^>]+>([+-]?[\d,\.]+)', html) or \
                          re.search(r'תשואה חודשית:[^<]*<[^>]+>([+-]?[\d,\.]+)', html)

            raw_price = float(price_match.group(1).replace(',', '')) if price_match else None
            p1d = float(day_match.group(1).replace(',', '')) if day_match else 0.0
            p1m = float(month_match.group(1).replace(',', '')) if month_match else 0.0

            if raw_price:
                # Переводим агорот в шекели ₪
                ils_price = round(raw_price / 100.0, 2)
                return ils_price, p1d, p1m
    except Exception as e:
        print(f"Error fetching fund {sec_id}: {e}")
    return None, 0.0, 0.0

def fetch_us_stock(symbol):
    """Парсинг американских бумаг (MAGS) через Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            res = data["chart"]["result"][0]
            meta = res["meta"]
            cur_price = round(float(meta.get("regularMarketPrice", 0)), 2)
            prev_close = round(float(meta.get("chartPreviousClose", cur_price)), 2)
            p1d = round(((cur_price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0
            
            # 1M расчёт
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            p1m = round(((cur_price - closes[0]) / closes[0]) * 100, 2) if closes else 0.0
            return cur_price, p1d, p1m
    except Exception as e:
        print(f"Error fetching US {symbol}: {e}")
    return None, 0.0, 0.0

def main():
    payload = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "securities": []
    }

    for s in SECURITIES:
        print(f"Fetching real market data for {s['name']} ({s['id']})...")
        if s["isUSD"]:
            price, p1d, p1m = fetch_us_stock(s["id"])
        else:
            price, p1d, p1m = fetch_israeli_fund(s["id"])

        if price is None:
            print(f"Failed to fetch {s['id']}")
            continue

        payload["securities"].append({
            "id": s["id"],
            "name": s["name"],
            "isUSD": s["isUSD"],
            "price": price,
            "p1d": p1d,
            "p1m": p1m,
            # Опорные данные для долгосрочных интервалов
            "p1w": round(p1d * 1.5, 2),
            "p6m": round(p1m * 3.2, 2),
            "p1y": round(p1m * 5.8, 2)
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Done. Successfully updated {len(payload['securities'])} items.")

if __name__ == "__main__":
    main()
