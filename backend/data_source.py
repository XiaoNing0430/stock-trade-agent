from __future__ import annotations

import re
import threading
import time
from typing import Any

import requests

QUOTE_URL = "https://qt.gtimg.cn/q"
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 AtlasStockDesk/1.0",
    "Referer": "https://gu.qq.com/",
}
CACHE_TTL = 8
REAL_UNIVERSE = [
    "600519", "300750", "601318", "600036", "000858", "002594", "300760", "688981",
    "000333", "600900", "000001", "601012", "601899", "600276", "603259", "601888",
    "000651", "000725", "300059", "600030", "601166", "600031", "002415", "300124",
    "002371", "300308", "688008", "603501", "600809", "600309", "601668", "601398",
    "601939", "601288", "000538", "300015", "600887", "600585", "601857", "600028",
    "601088", "600406", "002230", "002475", "000063", "300142", "688256", "688012",
    "300782", "002714",
]

cache: dict[str, tuple[float, Any]] = {}
cache_lock = threading.Lock()


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


def numeric(value: Any) -> float | None:
    if value in (None, "", "-", "—"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tencent_symbol(code: str) -> str:
    code = code.strip()
    if code == "000001":
        return "sh000001"
    if code == "399001":
        return "sz399001"
    if code == "399006":
        return "sz399006"
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


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_text(url: str, params: dict[str, Any]) -> str:
    response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
    response.raise_for_status()
    return response.content.decode("gbk", errors="replace")


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
        "volumeRatio": numeric(values[49]) if len(values) > 49 else None,
        "pe": numeric(values[52]) if len(values) > 52 else None,
        "updatedAt": int(time.time() * 1000),
    }


def load_quote_symbols(symbols: list[str]) -> list[dict[str, Any]]:
    unique_symbols = list(dict.fromkeys(symbol.strip() for symbol in symbols if symbol.strip()))
    if not unique_symbols:
        return []
    text = cached(
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
    payload = cached(
        f"history:{symbol}:{limit}",
        lambda: fetch_json(KLINE_URL, {"param": f"{symbol},day,,,{limit},qfq"}),
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
    index_quotes = load_quotes(index_codes)
    index_names = {
        "000001": ("上证指数", "沪市"),
        "399001": ("深证成指", "深市"),
        "399006": ("创业板指", "创业板"),
    }
    indices = []
    for quote in index_quotes:
        if quote["code"] in index_names:
            name, market = index_names[quote["code"]]
            quote["name"] = name
            quote["market"] = market
            indices.append(quote)
    order = {code: index for index, code in enumerate(dict.fromkeys(quote_codes))}
    stock_quotes.sort(key=lambda quote: order.get(quote["code"], 999))
    indices.sort(key=lambda quote: ["000001", "399001", "399006"].index(quote["code"]))
    return {
        "provider": "Tencent public quote API",
        "fetchedAt": int(time.time() * 1000),
        "quotes": stock_quotes,
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
