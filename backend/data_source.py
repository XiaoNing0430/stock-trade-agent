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
STALE_MAX_AGE = 1800  # 30 分钟硬顶：超龄缓存不再降级
_cache_ttl: int = CACHE_TTL
_timeout_seconds: int = 10
_retry_count: int = 1
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
stale_marker: dict[str, float] = {"at": 0.0, "age": 0.0}


def mark_stale(age: float) -> None:
    with cache_lock:
        stale_marker["at"] = time.time()
        stale_marker["age"] = age


def recent_stale(window: float = 2.0) -> dict[str, float] | None:
    """窗口内是否发生过降级服务；返回 {age: 秒} 或 None。"""
    with cache_lock:
        if time.time() - stale_marker["at"] <= window:
            return {"age": stale_marker["age"]}
    return None


def apply_runtime_config(timeout_seconds: int | None = None, retry_count: int | None = None, cache_seconds: int | None = None) -> None:
    """Apply workspace settings to the quote adapter without persisting anything."""
    global _cache_ttl, _timeout_seconds, _retry_count
    if timeout_seconds is not None:
        _timeout_seconds = max(2, int(timeout_seconds))
    if retry_count is not None:
        _retry_count = max(0, int(retry_count))
    if cache_seconds is not None:
        _cache_ttl = max(0, int(cache_seconds))


def cached(key: str, loader):
    now = time.time()
    with cache_lock:
        item = cache.get(key)
        if item and now - item[0] < _cache_ttl:
            return item[1]
    try:
        value = loader()
    except Exception:
        with cache_lock:
            item = cache.get(key)
        if item and now - item[0] <= STALE_MAX_AGE:
            mark_stale(now - item[0])
            return item[1]
        raise
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


INDEX_SYMBOLS = {
    "000001": "sh000001",  # 上证指数
    "399001": "sz399001",  # 深证成指
    "399006": "sz399006",  # 创业板指
}


def tencent_symbol(code: str) -> str:
    code = code.strip()
    exchange = classify_code(code)["exchange"]
    prefix = {"上交所": "sh", "深交所": "sz", "北交所": "bj"}.get(exchange, "sz")
    return f"{prefix}{code}"


def index_symbol(code: str) -> str:
    return INDEX_SYMBOLS.get(code.strip(), tencent_symbol(code))


def classify_code(code: str) -> dict[str, str]:
    code = code.strip()
    if code.startswith(("4", "8")):
        return {
            "exchange": "北交所",
            "board": "北交所",
            "securityType": "股票",
            "market": "北交所",
        }
    if code.startswith("68"):
        return {
            "exchange": "上交所",
            "board": "科创板",
            "securityType": "股票",
            "market": "科创板",
        }
    if code.startswith("30"):
        return {
            "exchange": "深交所",
            "board": "创业板",
            "securityType": "股票",
            "market": "创业板",
        }
    if code.startswith("5"):
        board = "科创板ETF" if code.startswith("588") else "沪市ETF"
        return {
            "exchange": "上交所",
            "board": board,
            "securityType": "ETF",
            "market": board,
        }
    if code.startswith(("15", "16", "18")):
        return {
            "exchange": "深交所",
            "board": "深市ETF",
            "securityType": "ETF",
            "market": "深市ETF",
        }
    if code.startswith("6"):
        return {
            "exchange": "上交所",
            "board": "沪深主板",
            "securityType": "股票",
            "market": "沪深主板",
        }
    if code.startswith(("0", "1", "2", "3")):
        return {
            "exchange": "深交所",
            "board": "沪深主板",
            "securityType": "股票",
            "market": "沪深主板",
        }
    return {
        "exchange": "未知",
        "board": "未知",
        "securityType": "未知",
        "market": "未知",
    }


def market_for_code(code: str) -> str:
    return classify_code(code)["market"]


def price_limit_ratio(code: str) -> float:
    profile = classify_code(code)
    if profile["exchange"] == "北交所":
        return 0.30
    if profile["board"] in {"创业板", "科创板"}:
        return 0.20
    return 0.10


def _http_get(url: str, params: dict[str, Any]):
    last_exc: Exception | None = None
    for attempt in range(_retry_count + 1):
        try:
            response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=_timeout_seconds)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < _retry_count:
                time.sleep(0.5 * (2 ** attempt))
    raise last_exc


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    return _http_get(url, params).json()


def fetch_text(url: str, params: dict[str, Any]) -> str:
    return _http_get(url, params).content.decode("gbk", errors="replace")


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
        **classify_code(code),
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


def load_history(code: str, limit: int = 40, is_index: bool = False) -> list[dict[str, Any]]:
    symbol = index_symbol(code) if is_index else tencent_symbol(code)
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
    # `codes` are always treated as individual stocks (e.g. 000001 = 平安银行).
    # Indices are fetched separately via INDEX_SYMBOLS to avoid the code clash.
    quote_codes = [code for code in codes if code]
    stock_quotes = load_quotes(quote_codes)
    index_quotes = load_quote_symbols([index_symbol(code) for code in index_codes])
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
            quote["exchange"] = "上交所" if quote["code"] == "000001" else "深交所"
            quote["board"] = "指数"
            quote["securityType"] = "指数"
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
    rows.sort(key=lambda row: (row["change"] is not None, row["change"] if row["change"] is not None else -999), reverse=True)
    return {
        "total": len(rows),
        "rows": rows,
        "universeSize": len(codes),
    }


SCREENER_V2_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"

# 前端排序字段 → 腾讯 rank 接口 sort_type（腾讯支持 price/turnover 排序）
_SCREENER_SORT_MAP = {
    "changePct": "price",
    "amount": "turnover",
    "turnoverRate": "turnover",
    "price": "price",
    "totalMarketCap": "price",
    "peTtm": "price",
}


def _normalize_rank_item(item: dict[str, Any]) -> dict[str, Any]:
    def n(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "code": str(item.get("code") or ""),
        "name": str(item.get("name") or ""),
        "price": n(item.get("zxj")),
        "change": n(item.get("zd")),
        "changePct": n(item.get("zdf")),
        "turnoverRate": n(item.get("hsl")),
        "amount": n(item.get("turnover")),
        "volume": n(item.get("volume")),
        "totalMarketCap": n(item.get("zsz")),
        "circulatingMarketCap": n(item.get("ltsz")),
        "peTtm": n(item.get("pe_ttm")),
        "pb": n(item.get("pn")),
        "amplitude": n(item.get("zf")),
        "volumeRatio": n(item.get("lb")),
        "speed": n(item.get("speed")),
        "netMoneyFlow": n(item.get("zljlr")),
    }


def _map_sort_field(sort_by: str) -> str:
    return _SCREENER_SORT_MAP.get(sort_by, "price")


def load_screener_v2(page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc") -> dict[str, Any]:
    """腾讯全市场排名接口，分页返回（约 4596 只沪深 A 股）。"""
    params = {
        "board_code": "aStock",
        "sort_type": _map_sort_field(sort_by),
        "direct": "down" if sort_dir == "desc" else "up",
        "offset": str((page - 1) * page_size),
        "count": str(page_size),
    }
    try:
        resp = requests.get(SCREENER_V2_URL, params=params, timeout=10)
        data = resp.json()["data"]
        rows = [_normalize_rank_item(item) for item in data.get("rank_list", [])]
        return {
            "total": data.get("total", 0),
            "page": page,
            "pageSize": page_size,
            "rows": rows,
            "provider": "Tencent rank API",
        }
    except Exception as exc:
        raise RuntimeError(f"全市场选股器请求失败: {exc}") from exc
