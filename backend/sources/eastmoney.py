from __future__ import annotations

import time
from typing import Any

import requests

from backend.data_source import classify_code, numeric
from backend.sources.base import Capability, DataSource
from backend.sources.cn_impl import CNAssetMetadata, CNDataNormalizer, CNMarketCalendar

# 报价字段：f2=price f3=changePct f4=changeAmount f5=volume f6=amount f8=turnoverRate
#           f9=pe f10=pb f12=code f14=name f15=high f16=low f17=open f18=prevClose
_QUOTE_FIELDS = "f2,f3,f4,f5,f6,f8,f9,f10,f12,f14,f15,f16,f17,f18"
# 排行字段（screener）
_CLIST_FIELDS = "f2,f3,f5,f6,f8,f9,f10,f12,f14"
# 前端排序字段 → clist fid（f2 现价 f3 涨跌幅 f6 成交额 f8 换手率 f9 PE f20 总市值）
_EM_SORT_MAP = {
    "changePct": "f3",
    "amount": "f6",
    "turnoverRate": "f8",
    "price": "f2",
    "peTtm": "f9",
    "totalMarketCap": "f20",
}
# 财务字段（fundamental，stock/get 实测返回字段）
_STOCK_FIELDS = "f43,f44,f45,f46,f47,f57,f58,f162,f164,f167,f168,f169,f170,f171,f173,f177,f178"

# 东财 secid 前缀：1. = 上交所, 0. = 深交所/北交所
_SECID_MAP = {"上交所": "1.", "深交所": "0.", "北交所": "0."}
# 指数 secid 与腾讯不同前缀，直接硬编码
_INDEX_SECID = {"000001": "1.000001", "399001": "0.399001", "399006": "0.399006"}
_INDEX_META: dict[str, dict[str, str]] = {
    "000001": {"name": "上证指数", "market": "沪市", "exchange": "上交所"},
    "399001": {"name": "深证成指", "market": "深市", "exchange": "深交所"},
    "399006": {"name": "创业板指", "market": "创业板", "exchange": "深交所"},
}


def _secid(code: str) -> str:
    """转换代码为东财 secid：1.上交所 0.深交所/北交所。"""
    prefix = _SECID_MAP.get(classify_code(code)["exchange"], "0.")
    return f"{prefix}{code}"


class EastMoneySource(DataSource):
    id = "eastmoney"
    name = "东方财富行情"
    capabilities = frozenset[Capability]({"realtime", "history", "screener", "paged_screener", "fundamental"})
    available = True
    provider_label = "东方财富实时行情"

    QUOTE_URL = "http://push2.eastmoney.com/api/qt/ulist.np/get"
    KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    CLIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"
    STOCK_URL = "http://push2.eastmoney.com/api/qt/stock/get"
    REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}

    def __init__(self) -> None:
        self._calendar = CNMarketCalendar()
        self._normalizer = CNDataNormalizer()
        self._metadata = CNAssetMetadata()

    @property
    def calendar(self) -> CNMarketCalendar:
        return self._calendar

    @property
    def normalizer(self) -> CNDataNormalizer:
        return self._normalizer

    @property
    def metadata(self) -> CNAssetMetadata:
        return self._metadata

    def _http_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """内部 HTTP 请求封装：调用东财接口并解析 JSON。"""
        resp = requests.get(url, params=params, headers=self.REQUEST_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _parse_quote(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """把东财 diff 条目标准化为前端 quote dict；缺失字段一律 None，绝不模拟。"""
        code = raw.get("f12", "")
        if not code:
            return None
        price = numeric(raw.get("f2"))
        change_amount = numeric(raw.get("f4"))
        prev_close: float | None = None
        if price is not None and change_amount is not None:
            prev_close = price - change_amount
        return {
            "code": code,
            "name": raw.get("f14", "") or code,
            **classify_code(code),
            "price": price,
            "change": numeric(raw.get("f3")),
            "changeAmount": change_amount,
            "prevClose": prev_close,
            "open": numeric(raw.get("f17")),
            "high": numeric(raw.get("f15")),
            "low": numeric(raw.get("f16")),
            "volume": numeric(raw.get("f5")),
            "amount": numeric(raw.get("f6")),
            "turnoverRate": numeric(raw.get("f8")),
            "pb": numeric(raw.get("f10")),
            "pe": numeric(raw.get("f9")),
            "volumeRatio": None,
            "updatedAt": int(time.time() * 1000),
        }

    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        unique_codes = list(dict.fromkeys(code.strip() for code in codes if code.strip()))
        if not unique_codes:
            return []
        params: dict[str, Any] = {
            "fltt": 2,
            "invt": 2,
            "fields": _QUOTE_FIELDS,
            "secids": ",".join(_secid(code) for code in unique_codes),
        }
        data = self._http_get(self.QUOTE_URL, params)
        raw_list = (data.get("data") or {}).get("diff", [])
        quotes = [self._parse_quote(item) for item in raw_list]
        return [quote for quote in quotes if quote is not None]

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict[str, Any]]:
        secid = _INDEX_SECID.get(code, _secid(code)) if is_index else _secid(code)
        params: dict[str, Any] = {
            "secid": secid,
            "klt": 101,  # 日线
            "fqt": 1,  # 前复权
            "end": "20500101",
            "lmt": limit,
        }
        data = self._http_get(self.KLINE_URL, params)
        klines = (data.get("data") or {}).get("klines", [])
        history: list[dict[str, Any]] = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            history.append(
                {
                    "date": parts[0],
                    "open": numeric(parts[1]),
                    "close": numeric(parts[2]),
                    "high": numeric(parts[3]),
                    "low": numeric(parts[4]),
                    "volume": numeric(parts[5]),
                    "amount": numeric(parts[6]),
                    "change": None,
                }
            )
        return history

    def load_market(self, codes: list[str]) -> dict[str, Any]:
        quote_codes = [code for code in codes if code]
        stock_quotes = self.load_quotes(quote_codes)
        params: dict[str, Any] = {
            "fltt": 2,
            "invt": 2,
            "fields": _QUOTE_FIELDS,
            "secids": ",".join(_INDEX_SECID.values()),
        }
        data = self._http_get(self.QUOTE_URL, params)
        raw_indices = (data.get("data") or {}).get("diff", [])
        indices = []
        for raw in raw_indices:
            code = raw.get("f12", "")
            meta = _INDEX_META.get(code)
            if meta is None:
                continue
            quote = self._parse_quote(raw)
            if quote is None:
                continue
            quote["name"] = meta["name"]
            quote["market"] = meta["market"]
            quote["exchange"] = meta["exchange"]
            quote["board"] = "指数"
            quote["securityType"] = "指数"
            indices.append(quote)
        indices.sort(key=lambda quote: ["000001", "399001", "399006"].index(quote["code"]))
        order = {code: index for index, code in enumerate(dict.fromkeys(quote_codes))}
        stock_quotes.sort(key=lambda quote: order.get(quote["code"], 999))
        return {
            "provider": self.provider_label,
            "fetchedAt": int(time.time() * 1000),
            "quotes": stock_quotes,
            "indices": indices,
            "errors": [],
        }

    def load_screener(self, market: str, page_size: int = 300) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "po": 1,
            "np": 1,
            "pn": 1,
            "pz": page_size,
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": _CLIST_FIELDS,
        }
        data = self._http_get(self.CLIST_URL, params)
        payload = data.get("data") or {}
        total = int(payload.get("total", 0))
        raw_list = payload.get("diff", [])
        rows = []
        for raw in raw_list:
            quote = self._parse_quote(raw)
            if quote is not None:
                rows.append(quote)
        if market != "全部":
            rows = [row for row in rows if row["market"] == market]
        rows.sort(
            key=lambda row: (row["change"] is not None, row["change"] if row["change"] is not None else -999),
            reverse=True,
        )
        return {
            "total": total,
            "rows": rows,
            "universeSize": len(rows),
        }

    def load_screener_paged(
        self, page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc"
    ) -> dict[str, Any]:
        """全市场分页排序选股（clist 原生 pn/pz/fid/po），返回 shape 与腾讯 v2 一致。"""
        params: dict[str, Any] = {
            "fltt": 2,
            "invt": 2,
            "fid": _EM_SORT_MAP.get(sort_by, "f3"),
            "po": 1 if sort_dir == "desc" else 0,
            "np": 1,
            "pn": page,
            "pz": page_size,
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": _CLIST_FIELDS,
        }
        data = self._http_get(self.CLIST_URL, params)
        payload = data.get("data") or {}
        rows = []
        for raw in payload.get("diff", []):
            quote = self._parse_quote(raw)
            if quote is not None:
                rows.append(quote)
        return {
            "total": int(payload.get("total", 0)),
            "page": page,
            "pageSize": page_size,
            "rows": rows,
            "provider": self.provider_label,
        }

    def load_fundamentals(self, code: str) -> dict[str, Any]:
        """拉取个股财务字段（唯一 fundamental 提供方）。"""
        params: dict[str, Any] = {
            "secid": _secid(code),
            "fields": _STOCK_FIELDS,
        }
        data = self._http_get(self.STOCK_URL, params)
        raw = data.get("data") or {}
        return {
            "code": raw.get("f57"),
            "name": raw.get("f58"),
            "price": numeric(raw.get("f43")),
            "open": numeric(raw.get("f46")),
            "high": numeric(raw.get("f44")),
            "low": numeric(raw.get("f45")),
            "volume": numeric(raw.get("f47")),
            "pe": numeric(raw.get("f162")),
            "pb": numeric(raw.get("f164")),
            "roe": numeric(raw.get("f167")),
            "totalShares": numeric(raw.get("f168")),
            "floatShares": numeric(raw.get("f169")),
            "floatMarketCap": numeric(raw.get("f170")),
            "totalMarketCap": numeric(raw.get("f171")),
            "turnoverRate": numeric(raw.get("f173")),
            "peg": numeric(raw.get("f177")),
            "mainForceFlow": numeric(raw.get("f178")),
        }
