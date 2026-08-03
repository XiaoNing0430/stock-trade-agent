from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:
    requests = None


ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4173"))
QUOTE_URL = "https://qt.gtimg.cn/q"
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 AtlasStockDesk/1.0",
    "Referer": "https://gu.qq.com/",
}
CACHE_TTL = 8
cache: dict[str, tuple[float, Any]] = {}
cache_lock = threading.Lock()

# A real-data candidate pool. The values are never used as prices; names,
# prices and metrics always come from the live quote response.
REAL_UNIVERSE = [
    "600519",
    "300750",
    "601318",
    "600036",
    "000858",
    "002594",
    "300760",
    "688981",
    "000333",
    "600900",
    "000001",
    "601012",
    "601899",
    "600276",
    "603259",
    "601888",
    "000651",
    "000725",
    "300059",
    "600030",
    "601166",
    "600031",
    "002415",
    "300124",
    "002371",
    "300308",
    "688008",
    "603501",
    "600809",
    "600309",
    "601668",
    "601398",
    "601939",
    "601288",
    "000538",
    "300015",
    "600887",
    "600585",
    "601857",
    "600028",
    "601088",
    "600406",
    "002230",
    "002475",
    "000063",
    "300142",
    "688256",
    "688012",
    "300782",
    "002714",
]


def cached(key: str, loader):
    now = time.time()
    with cache_lock:
        item = cache.get(key)
        if item and now - item[0] < CACHE_TTL:
            return item[1]
    value = loader()
    with cache_lock:
        cache[key] = (now, value)
    return value


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    if requests is not None:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()
    query = urlencode({key: value for key, value in params.items() if value is not None})
    request = Request(f"{url}?{query}", headers=REQUEST_HEADERS)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, params: dict[str, Any]) -> str:
    if requests is not None:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding or "gbk"
        return response.text
    query = urlencode({key: value for key, value in params.items() if value is not None})
    request = Request(f"{url}?{query}", headers=REQUEST_HEADERS)
    with urlopen(request, timeout=10) as response:
        return response.read().decode("gbk", errors="replace")


def cached_request(key: str, loader):
    return cached(key, loader)


def numeric(value: Any) -> float | None:
    if value in (None, "", "-", "—"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tencent_symbol(code: str) -> str:
    code = code.strip()
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def market_for_code(code: str) -> str:
    if code.startswith("68"):
        return "科创板"
    if code.startswith("6"):
        return "沪A"
    if code.startswith(("4", "8")):
        return "北交所"
    return "深A"


def parse_quote_body(symbol: str, body: str) -> dict[str, Any] | None:
    values = body.split("~")
    if len(values) < 35:
        return None
    code = values[2] or symbol[-6:]
    price = numeric(values[3])
    prev_close = numeric(values[4])
    if price is None or prev_close is None:
        return None
    amount_parts = values[35].split("/") if len(values) > 35 else []
    amount = numeric(amount_parts[2]) if len(amount_parts) > 2 else None
    return {
        "code": code,
        "name": values[1] or code,
        "market": market_for_code(code),
        "price": price,
        "change": numeric(values[32]),
        "changeAmount": numeric(values[31]),
        "prevClose": prev_close,
        "open": numeric(values[5]),
        "high": numeric(values[33]),
        "low": numeric(values[34]),
        "volume": numeric(values[6]),
        "amount": amount,
        "turnoverRate": numeric(values[38]) if len(values) > 38 else None,
        "pb": numeric(values[46]) if len(values) > 46 else None,
        "pe": numeric(values[52]) if len(values) > 52 else None,
        "updatedAt": int(time.time() * 1000),
    }


def load_quote_symbols(symbols: list[str]) -> list[dict[str, Any]]:
    unique_symbols = list(dict.fromkeys(symbol.strip() for symbol in symbols if symbol.strip()))
    if not unique_symbols:
        return []
    text = cached_request(
        f"quotes:{','.join(unique_symbols)}",
        lambda: fetch_text(QUOTE_URL, {"q": ",".join(unique_symbols)}),
    )
    pattern = re.compile(r'v_([^=]+)="(.*?)";')
    parsed: dict[str, dict[str, Any]] = {}
    for symbol, body in pattern.findall(text):
        quote = parse_quote_body(symbol, body)
        if quote:
            parsed[symbol] = quote
    return [parsed[symbol] for symbol in unique_symbols if symbol in parsed]


def load_quotes(codes: list[str]) -> list[dict[str, Any]]:
    unique_codes = list(dict.fromkeys(code.strip() for code in codes if code.strip()))
    return load_quote_symbols([tencent_symbol(code) for code in unique_codes])


def load_history(code: str, limit: int = 40) -> list[dict[str, Any]]:
    symbol = tencent_symbol(code)
    payload = cached_request(
        f"history:{symbol}:{limit}",
        lambda: fetch_json(
            KLINE_URL,
            {"param": f"{symbol},day,,,{limit},qfq"},
        ),
    )
    data = payload.get("data") or {}
    symbol_data = data.get(symbol) or {}
    rows = symbol_data.get("qfqday") or symbol_data.get("day") or []
    history = []
    for row in rows[-limit:]:
        if len(row) < 6:
            continue
        history.append(
            {
                "date": row[0],
                "open": numeric(row[1]),
                "close": numeric(row[2]),
                "high": numeric(row[3]),
                "low": numeric(row[4]),
                "volume": numeric(row[5]),
                "amount": numeric(row[6]) if len(row) > 6 else None,
                "change": numeric(row[8]) if len(row) > 8 else None,
            }
        )
    return history


def load_market(codes: list[str]) -> dict[str, Any]:
    index_codes = ["000001", "399001", "399006"]
    quote_codes = [code for code in codes if code and code not in index_codes]
    stock_quotes = load_quotes(quote_codes)
    index_quotes = load_quote_symbols(["sh000001", "sz399001", "sz399006"])
    index_names = {
        "000001": ("上证指数", "沪市"),
        "399001": ("深证成指", "深市"),
        "399006": ("创业板指", "创业板"),
    }
    indices = []
    quotes = stock_quotes
    requested = list(dict.fromkeys(quote_codes))
    for quote in index_quotes:
        if quote["code"] in index_names:
            name, market = index_names[quote["code"]]
            quote["name"] = name
            quote["market"] = market
            indices.append(quote)
    order = {code: index for index, code in enumerate(requested)}
    quotes.sort(key=lambda quote: order.get(quote["code"], 999))
    indices.sort(key=lambda quote: ["000001", "399001", "399006"].index(quote["code"]))
    return {
        "provider": "Tencent public quote API",
        "fetchedAt": int(time.time() * 1000),
        "quotes": quotes,
        "indices": indices,
        "errors": [],
    }


def load_screener(market: str, page_size: int = 300) -> dict[str, Any]:
    codes = REAL_UNIVERSE[: max(20, min(int(page_size), len(REAL_UNIVERSE)))]
    rows = load_quotes(codes)
    if market != "全部":
        rows = [row for row in rows if row["market"] == market]
    rows.sort(key=lambda row: (row["change"] is not None, row["change"] or -999), reverse=True)
    return {
        "total": len(rows),
        "rows": rows,
        "universeSize": len(codes),
    }


class AppHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, status: int, payload: dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "provider": "Tencent public quote API",
                    "serverTime": int(time.time() * 1000),
                    "universeSize": len(REAL_UNIVERSE),
                },
            )
            return
        if parsed.path == "/api/market":
            query = parse_qs(parsed.query)
            codes = query.get("codes", [""])[0].split(",")
            try:
                self._send_json(200, load_market(codes))
            except Exception as error:
                self._send_json(502, {"error": str(error), "provider": "Tencent public quote API"})
            return
        if parsed.path == "/api/history":
            query = parse_qs(parsed.query)
            code = query.get("code", ["600519"])[0]
            try:
                self._send_json(
                    200,
                    {
                        "code": code,
                        "provider": "Tencent public quote API",
                        "fetchedAt": int(time.time() * 1000),
                        "history": load_history(code),
                    },
                )
            except Exception as error:
                self._send_json(502, {"error": str(error), "provider": "Tencent public quote API"})
            return
        if parsed.path == "/api/screener":
            query = parse_qs(parsed.query)
            market = query.get("market", ["全部"])[0]
            page_size = query.get("pageSize", ["300"])[0]
            try:
                payload = load_screener(market, int(page_size))
                payload["provider"] = "Tencent public quote API"
                payload["fetchedAt"] = int(time.time() * 1000)
                self._send_json(200, payload)
            except Exception as error:
                self._send_json(502, {"error": str(error), "provider": "Tencent public quote API"})
            return
        super().do_GET()

    def log_message(self, format: str, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Atlas Stock Desk listening on http://{HOST}:{PORT}")
    print("Real quote proxy: Tencent public quote API")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
