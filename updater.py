"""
TASE dashboard updater.

Берёт РЕАЛЬНЫЕ исторические цены закрытия:
  * израильские бумаги (קרנות נאמנות / קרנות סל / קרנות חוץ) — по очереди из
    Bizportal (JSON-график), официального API TASE (только торгуемые бумаги) и Funder;
  * американские тикеры — с Yahoo Finance.

Ничего не "досчитывает" и не рисует синтетику: если данных нет — поле будет null,
а на сайте покажется «—».

История накапливается в data.json между запусками (новые точки добавляются,
старые сохраняются), поэтому со временем становится доступно больше года.
"""
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

SCHEMA_VERSION = 2
DATA_FILE = "data.json"
CONFIG_FILE = "securities.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Периоды доходности: ключ -> (дней назад, допуск в днях, если история чуть короче)
PERIODS = {
    "1w": (7, 0),
    "1m": (30, 3),
    "6m": (182, 7),
    "1y": (365, 7),
}

MAX_HISTORY_DAYS = 365 * 5  # сколько истории хранить в data.json


# ---------------------------------------------------------------- HTTP

try:
    # curl_cffi повторяет TLS-отпечаток настоящего Chrome — Cloudflare реже блокирует.
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None


class HTTPStatusError(Exception):
    def __init__(self, url, code, server, body):
        super().__init__(f"{url}: HTTP {code}; server={server}; body={body[:120]!r}")
        self.code = code


def http_get(url, timeout=20, headers=None, json_body=None):
    """GET (или POST, если передан json_body). Возвращает (final_url, text)."""
    hdrs = {"Accept-Language": "he-IL,he;q=0.9,en;q=0.8"}
    hdrs.update(headers or {})
    data = json.dumps(json_body).encode() if json_body is not None else None
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if cffi_requests is not None:
        if data is None:
            r = cffi_requests.get(url, impersonate="chrome", timeout=timeout, headers=hdrs)
        else:
            r = cffi_requests.post(url, impersonate="chrome", timeout=timeout, headers=hdrs, data=data)
        if r.status_code >= 400:
            raise HTTPStatusError(url, r.status_code, r.headers.get("server"), r.text)
        return str(r.url), r.text
    hdrs.setdefault("User-Agent", UA)
    hdrs.setdefault("Accept", "text/html,application/json;q=0.9,*/*;q=0.8")
    req = urllib.request.Request(url, headers=hdrs, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl(), resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        raise HTTPStatusError(url, e.code, e.headers.get("Server"), e.read().decode("utf-8", "ignore"))


# ---------------------------------------------------------------- Funder

_decoder = json.JSONDecoder()


def extract_js_var(html, name):
    """Достаёт JSON-значение `var <name> = {...};` из HTML. На странице переменная может
    встречаться несколько раз (иногда сначала как пустая строка) — берём первую непустую."""
    for m in re.finditer(r"var\s+" + re.escape(name) + r"\s*=\s*", html):
        pos = m.end()
        if pos >= len(html) or html[pos] not in "{[":
            continue  # например  var fundGraphData = "";
        try:
            value, _ = _decoder.raw_decode(html, pos)
            return value
        except ValueError:
            continue
    return None


def parse_funder_page(html):
    """Разбирает страницу funder.co.il. Цены на Funder — в агорот, переводим в шекели."""
    graph = extract_js_var(html, "fundGraphData")
    info = extract_js_var(html, "fundData")
    info = (info or {}).get("x", [{}])[0] if isinstance(info, dict) else {}

    points = []
    if isinstance(graph, dict):
        for p in graph.get("x", []):
            try:
                d = str(p["c"])[:10]
                price = float(p["p"]) / 100.0
            except (KeyError, TypeError, ValueError):
                continue
            if price > 0:
                points.append({"date": d, "price": round(price, 4)})

    # Доходности, которые считает сам Funder — только для сверки в логе/на сайте.
    # Страницы קרנות נאמנות и קרנות סל используют разные ключи.
    keymap_fund = {"1d": "1day", "1w": "7days", "1m": "30days", "6m": "180days", "1y": "1year"}
    keymap_etf = {"1d": "y1d", "1w": "y7d", "1m": "y1m", "6m": "y6m", "1y": "y1y"}
    keymap = keymap_etf if "y1d" in info else keymap_fund
    ref = {k: info.get(v) for k, v in keymap.items()}

    name = info.get("fundLongName") or info.get("fundName")
    return points, ref, name


def fetch_funder(sec_id, attempts=3):
    """Funder: пробует /fund/<id> (קרנות נאמנות), потом /etf/<id> (קרנות סל / חוץ).
    Funder иногда отдаёт страницу с пустым графиком — поэтому повторяем."""
    last_err = "not found"
    for kind in ("fund", "etf"):
        url = f"https://www.funder.co.il/{kind}/{sec_id}"
        for i in range(attempts):
            try:
                final_url, html = http_get(url)
            except HTTPStatusError as e:
                last_err = str(e)
                if e.code in (401, 403, 429):
                    raise RuntimeError(last_err)  # блокировка — повторять бессмысленно
                time.sleep(2 + 2 * i)
                continue
            except Exception as e:  # сеть / таймаут
                last_err = f"{url}: {type(e).__name__}: {e}"
                time.sleep(2 + 2 * i)
                continue
            if "page404" in final_url:
                last_err = f"{url}: 404"
                break  # такого типа нет — пробуем следующий
            points, ref, name = parse_funder_page(html)
            if len(points) >= 2:
                return {"points": points, "ref": ref, "source_name": name, "url": url, "source": "funder"}
            last_err = f"{url}: empty price graph (attempt {i + 1})"
            time.sleep(2 + 2 * i)
    raise RuntimeError(last_err)


def _dmy(d):
    """'24/09/2026' -> '2026-09-24'"""
    dd, mm, yy = d.split("/")
    return f"{yy}-{mm}-{dd}"


def fetch_bizportal(sec_id):
    """Bizportal: один JSON-запрос, ~5 лет дневных закрытий. Цены в агорот.
    Работает и для קרנות נאמנות, и для קרנות סל / חוץ."""
    url = ("https://www.bizportal.co.il/ajax/biz_papers_helper.ashx"
           f"?action=get_paper_yearly_graph&request_type=1&paper_id={sec_id}")
    _, text = http_get(url, headers={
        "Referer": f"https://www.bizportal.co.il/mutualfunds/quote/generalview/{sec_id}",
        "X-Requested-With": "XMLHttpRequest",
    })
    text = text.strip().lstrip("~")
    rows = json.loads(text) if text.startswith("[") else []
    points = []
    for r in rows:
        try:
            price = float(r["C_p"]) / 100.0
            if price > 0:
                points.append({"date": _dmy(r["D_p"]), "price": round(price, 4)})
        except (KeyError, TypeError, ValueError):
            continue
    if len(points) < 2:
        raise RuntimeError(f"bizportal {sec_id}: no data (got {len(rows)} rows)")
    return {"points": points, "ref": {}, "source": "bizportal",
            "url": f"https://www.bizportal.co.il/mutualfunds/quote/generalview/{sec_id}"}


def fetch_tase_api(sec_id, days=400):
    """Официальный API биржи (тот же, что использует market.tase.co.il).
    Отдаёт историю только для бумаг, которые торгуются на бирже (קרנות סל / חוץ, акции),
    для קרנות נאמנות возвращает пусто. 30 строк на страницу."""
    today = datetime.now(timezone.utc).date()
    body = {"dFrom": (today - timedelta(days=days)).isoformat(), "dTo": today.isoformat(),
            "oId": sec_id.zfill(8), "pType": 8, "TotalRec": 1, "lang": "0", "pageNum": 1}
    hdrs = {"Referer": "https://market.tase.co.il/", "Origin": "https://market.tase.co.il",
            "Accept": "application/json"}
    points, page, total = [], 1, None
    while page <= 20:
        body["pageNum"] = page
        _, text = http_get("https://api.tase.co.il/api/security/historyeod", headers=hdrs, json_body=body)
        j = json.loads(text)
        items = j.get("Items") or []
        total = j.get("TotalRec") or 0
        for it in items:
            try:
                price = float(it["CloseRate"]) / 100.0
                if price > 0:
                    points.append({"date": _dmy(it["TradeDate"]), "price": round(price, 4)})
            except (KeyError, TypeError, ValueError):
                continue
        if not items or len(points) >= total:
            break
        page += 1
        time.sleep(0.5)
    if len(points) < 2:
        raise RuntimeError(f"tase api {sec_id}: no data (TotalRec={total})")
    return {"points": points, "ref": {}, "source": "tase",
            "url": f"https://market.tase.co.il/he/market_data/security/{sec_id}/major_data"}


def fetch_tase(sec_id):
    """Пробует источники по очереди, пока один не сработает."""
    errors = []
    for name, fn in (("bizportal", fetch_bizportal), ("tase", fetch_tase_api), ("funder", fetch_funder)):
        try:
            res = fn(sec_id)
            res.setdefault("source", name)
            return res
        except Exception as e:
            msg = str(e)[:160]
            print(f"   - {name}: {msg}")
            errors.append(f"{name}: {msg}")
    raise RuntimeError(" | ".join(errors))


# ---------------------------------------------------------------- Yahoo (US)

def fetch_us(symbol, attempts=3):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range=2y&interval=1d&includePrePost=false")
    last_err = None
    for i in range(attempts):
        try:
            _, body = http_get(url)
            res = json.loads(body)["chart"]["result"][0]
            offset = int(res["meta"].get("gmtoffset", 0))
            closes = res["indicators"]["quote"][0]["close"]
            points = []
            # Пары (время, цена) фильтруем ВМЕСТЕ, чтобы даты не съезжали при пропусках.
            for ts, c in zip(res.get("timestamp", []), closes):
                if c is None:
                    continue
                d = datetime.fromtimestamp(ts + offset, tz=timezone.utc).strftime("%Y-%m-%d")
                points.append({"date": d, "price": round(float(c), 4)})
            if len(points) >= 2:
                return {"points": points, "ref": {}, "source": "yahoo",
                        "url": f"https://finance.yahoo.com/quote/{symbol}"}
            last_err = "no data"
        except Exception as e:
            last_err = str(e)
        time.sleep(3 + 3 * i)
    raise RuntimeError(f"Yahoo {symbol}: {last_err}")


# ---------------------------------------------------------------- обработка рядов

def dedupe_sort(points):
    by_date = {}
    for p in points:
        by_date[p["date"]] = p["price"]
    return [{"date": d, "price": by_date[d]} for d in sorted(by_date)]


def adjust_splits(points):
    """Если цена за один день меняется в ≥5 раз — это сплит/смена единиц (как у 1183441
    в декабре 2025: 4393 ₪ -> 43.76 ₪). Пересчитываем всё, что до скачка, в новых единицах."""
    notes = []
    pts = [dict(p) for p in points]
    for i in range(len(pts) - 1, 0, -1):
        prev, cur = pts[i - 1]["price"], pts[i]["price"]
        if prev <= 0 or cur <= 0:
            continue
        ratio = prev / cur
        if ratio >= 5 or ratio <= 0.2:
            # округляем до "красивого" коэффициента (10, 100, 1/10 ...), если близко
            nice = 10 ** round(math.log10(ratio))
            factor = nice if abs(ratio / nice - 1) < 0.1 else ratio
            for j in range(i):
                pts[j]["price"] = round(pts[j]["price"] / factor, 4)
            notes.append(f"{pts[i]['date']}: split/units ×{factor:g} adjusted")
    return pts, notes


def base_point(points, days, tolerance):
    """Последняя точка с датой <= (последняя дата − days). Если истории чуть не хватает,
    берём первую точку, если она не дальше `tolerance` дней от нужной даты."""
    last = date.fromisoformat(points[-1]["date"])
    target = last - timedelta(days=days)
    base = None
    for p in points:
        if date.fromisoformat(p["date"]) <= target:
            base = p
        else:
            break
    if base is None and points:
        first = date.fromisoformat(points[0]["date"])
        if (first - target).days <= tolerance:
            base = points[0]
    # Защита от дыр в истории: база не должна быть сильно раньше нужной даты
    if base is not None:
        gap = (target - date.fromisoformat(base["date"])).days
        if gap > max(5, days // 10):
            return None
    return base


def pct(cur, base):
    return round((cur / base - 1) * 100, 2) if base else None


def compute_periods(points):
    last = points[-1]
    out = {}
    prev = points[-2] if len(points) >= 2 else None
    out["1d"] = {"pct": pct(last["price"], prev["price"]) if prev else None,
                 "from": prev["date"] if prev else None}
    for key, (days, tol) in PERIODS.items():
        b = base_point(points, days, tol)
        out[key] = {"pct": pct(last["price"], b["price"]) if b else None,
                    "from": b["date"] if b else None}
    return out


# ---------------------------------------------------------------- main

def load_previous():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        return {}
    # Старый формат (v1) содержал СИНТЕТИЧЕСКУЮ историю — её не переносим.
    if old.get("schema_version") != SCHEMA_VERSION:
        print("Previous data.json is old format (synthetic history) — discarding it.")
        return {}
    return {s["id"]: s for s in old.get("securities", [])}


def main():
    print("HTTP client:", "curl_cffi (Chrome impersonation)" if cffi_requests else "urllib")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)

    previous = load_previous()
    now = datetime.now(timezone.utc)
    cutoff = (now.date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
    result, failures, errors = [], [], {}

    for s in config:
        sid, source = s["id"], s.get("source", "tase")
        print(f"→ {sid} {s['name']}")
        old = previous.get(sid)
        try:
            fetched = fetch_us(sid) if source == "us" else fetch_tase(sid)
            fetch_ok = True
        except Exception as e:
            print(f"   ! fetch failed: {e}")
            failures.append(sid)
            errors[sid] = str(e)[:600]
            if not old:
                continue
            fetched = {"points": [], "ref": old.get("source_returns", {}),
                       "url": old.get("source_url")}
            fetch_ok = False

        # история = старая (уже скорректированная) + свежая; свежие точки важнее
        merged = (old.get("daily", []) if old else []) + fetched["points"]
        merged = [p for p in dedupe_sort(merged) if p["date"] >= cutoff]
        merged, split_notes = adjust_splits(merged)
        if len(merged) < 2:
            print("   ! not enough data points")
            continue

        periods = compute_periods(merged)
        last = merged[-1]

        # Сверка с цифрами самого Funder (разница >1 п.п. — повод посмотреть глазами)
        ref = fetched.get("ref") or {}
        for k in ("1d", "1w", "1m", "6m", "1y"):
            mine, theirs = periods[k]["pct"], ref.get(k)
            if mine is not None and isinstance(theirs, (int, float)) and abs(mine - theirs) > 1.0:
                print(f"   ~ {k}: ours {mine:+.2f}% vs funder {theirs:+.2f}%")

        print(f"   price {last['price']} on {last['date']}, "
              f"1d {periods['1d']['pct']}, 1m {periods['1m']['pct']}, 1y {periods['1y']['pct']}"
              + f" [{fetched.get('source', '?')}]"
              + ("" if fetch_ok else "  [STALE: kept previous data]"))

        result.append({
            "id": sid,
            "name": s["name"],
            "source": source,
            "currency": "USD" if source == "us" else "ILS",
            "source_url": fetched.get("url"),
            "data_source": fetched.get("source") or (old or {}).get("data_source"),
            "fetch_ok": fetch_ok,
            "as_of": last["date"],
            "price": last["price"],
            "periods": periods,
            "source_returns": ref,
            "split_notes": split_notes,
            "daily": merged,
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "failures": failures,
        "errors": errors,
        "securities": result,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"Done: {len(result)} securities written, {len(failures)} fetch failures.")
    # Если не удалось вообще ничего — пусть Action покраснеет, чтобы это было видно.
    if not result or len(failures) == len(config):
        sys.exit(1)


if __name__ == "__main__":
    main()
