from __future__ import annotations

from typing import Any

from backend.sources.cn_impl import CNAssetMetadata, CNDataNormalizer, CNMarketCalendar
from backend.sources.eastmoney import EastMoneySource, _secid


def _make_fake_json(payload: dict[str, Any]) -> Any:
    """返回一个模拟 requests.Response 的工厂。"""

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return payload

        @staticmethod
        def raise_for_status() -> None:
            pass

    return FakeResponse()


def test_em_source_basic_attributes() -> None:
    source = EastMoneySource()
    assert source.id == "eastmoney"
    assert source.name == "东方财富行情"
    assert source.available is True
    assert source.provider_label == "东方财富实时行情"


def test_em_source_capabilities_fundamental() -> None:
    source = EastMoneySource()
    assert source.capabilities == frozenset({"realtime", "history", "screener", "fundamental"})
    assert "realtime" in source.capabilities
    assert "history" in source.capabilities
    assert "screener" in source.capabilities
    assert "fundamental" in source.capabilities


def test_em_source_cn_components() -> None:
    source = EastMoneySource()
    assert isinstance(source.calendar, CNMarketCalendar)
    assert isinstance(source.normalizer, CNDataNormalizer)
    assert isinstance(source.metadata, CNAssetMetadata)


def test_parse_em_quote(monkeypatch: Any) -> None:
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "diff": [
                        {
                            "f2": 1297.5,
                            "f3": -0.16,
                            "f4": -2.06,
                            "f12": "600519",
                            "f14": "贵州茅台",
                        }
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_quotes(["600519"])
    assert len(result) == 1
    assert result[0]["code"] == "600519"
    assert result[0]["name"] == "贵州茅台"
    assert result[0]["price"] == 1297.5
    assert result[0]["change"] == -0.16
    assert result[0]["changeAmount"] == -2.06
    assert result[0]["prevClose"] == 1297.5 - (-2.06)  # = 1299.56
    assert result[0]["updatedAt"] is not None


def test_parse_em_quote_field_completeness(monkeypatch: Any) -> None:
    """验证返回的 quote dict 包含所有必需字段（含缺失字段为 None）。"""
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "diff": [
                        {
                            "f2": 1297.5,
                            "f3": -0.16,
                            # f4 缺失 → changeAmount/prevClose 为 None
                            "f12": "600519",
                            "f14": "贵州茅台",
                        }
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_quotes(["600519"])
    assert len(result) == 1
    quote = result[0]

    # 必含字段
    required_keys = {
        "code",
        "name",
        "exchange",
        "board",
        "securityType",
        "market",
        "price",
        "change",
        "changeAmount",
        "prevClose",
        "open",
        "high",
        "low",
        "volume",
        "amount",
        "turnoverRate",
        "pb",
        "pe",
        "volumeRatio",
        "updatedAt",
    }
    assert required_keys.issubset(quote.keys()), f"Missing keys: {required_keys - set(quote.keys())}"

    # 缺失 f4 → changeAmount/prevClose 为 None
    assert quote["changeAmount"] is None
    assert quote["prevClose"] is None


def test_parse_em_kline(monkeypatch: Any) -> None:
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "klines": [
                        "2026-09-02,1302.80,1297.50,1303.00,1291.20,20308,2634084231.00",
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_history("600519", limit=1)
    assert len(result) == 1
    assert result[0]["date"] == "2026-09-02"
    assert result[0]["open"] == 1302.80
    assert result[0]["close"] == 1297.50
    assert result[0]["high"] == 1303.00
    assert result[0]["low"] == 1291.20
    assert result[0]["volume"] == 20308
    assert result[0]["amount"] == 2634084231.00


def test_parse_em_screener(monkeypatch: Any) -> None:
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "total": 100,
                    "diff": [
                        {
                            "f2": 53.82,
                            "f3": 104.41,
                            "f5": 202103,
                            "f6": 1205493198.97,
                            "f8": 77.78,
                            "f9": 36.42,
                            "f10": "-",
                            "f12": "301688",
                            "f14": "N格林",
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_screener("全部", page_size=5)
    assert result["total"] == 100
    assert len(result["rows"]) == 1
    assert result["rows"][0]["code"] == "301688"
    assert result["rows"][0]["price"] == 53.82
    # f10 = "-" → pb 应为 None
    assert result["rows"][0]["pb"] is None


def test_em_secid_sh() -> None:
    assert _secid("600519") == "1.600519"  # 上交所
    assert _secid("000001") == "0.000001"  # 深交所
    assert _secid("300750") == "0.300750"  # 创业板
    assert _secid("688981") == "1.688981"  # 科创板（上交所）
    assert _secid("830799") == "0.830799"  # 北交所


def test_em_load_market_indices(monkeypatch: Any) -> None:
    """验证 load_market 包含指数并从 _INDEX_SECID 获取。"""
    source = EastMoneySource()
    call_count = 0

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # load_quotes → 个股空
            return _make_fake_json({"rc": 0, "data": {"diff": []}})
        # load_market → 指数请求（包含 _INDEX_SECID 的三个指数）
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "diff": [
                        {"f12": "000001", "f14": "上证指数", "f2": 3200.0, "f3": 1.2, "f4": 38.0},
                        {"f12": "399001", "f14": "深证成指", "f2": 10500.0, "f3": -0.5, "f4": -52.0},
                        {"f12": "399006", "f14": "创业板指", "f2": 2100.0, "f3": 2.1, "f4": 44.0},
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_market(["600519"])
    assert result["provider"] == "东方财富实时行情"
    assert len(result["indices"]) == 3
    assert result["indices"][0]["code"] == "000001"
    assert result["indices"][0]["name"] == "上证指数"
    assert result["indices"][0]["market"] == "沪市"
    assert result["indices"][0]["exchange"] == "上交所"
    assert result["indices"][0]["board"] == "指数"
    assert result["indices"][0]["securityType"] == "指数"
    assert result["indices"][1]["code"] == "399001"
    assert result["indices"][1]["name"] == "深证成指"
    assert result["indices"][1]["market"] == "深市"
    assert result["indices"][2]["code"] == "399006"
    assert result["indices"][2]["name"] == "创业板指"
    assert result["indices"][2]["market"] == "创业板"
    assert result["indices"][2]["exchange"] == "深交所"


def test_parse_em_fundamentals(monkeypatch: Any) -> None:
    """验证 load_fundamentals 按真实 stock/get 字段映射解析。"""
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        assert params["fields"] == "f43,f44,f45,f46,f47,f57,f58,f162,f164,f167,f168,f169,f170,f171,f173,f177,f178"
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "f43": 1297.5,
                    "f44": 1305.0,
                    "f45": 1290.0,
                    "f46": 1300.0,
                    "f47": 20308,
                    "f57": "600519",
                    "f58": "贵州茅台",
                    "f162": 25.3,
                    "f164": 6.8,
                    "f167": 0.15,
                    "f168": 1256197800,
                    "f169": 1256197800,
                    "f170": 1620000000000,
                    "f171": 1625000000000,
                    "f173": 0.78,
                    "f177": 22.1,
                    "f178": 12300000,
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_fundamentals("600519")
    assert result["code"] == "600519"
    assert result["name"] == "贵州茅台"
    assert result["price"] == 1297.5
    assert result["pe"] == 25.3
    assert result["pb"] == 6.8
    assert result["turnoverRate"] == 0.78
    assert result["mainForceFlow"] == 12300000


def test_em_empty_codes_returns_empty() -> None:
    source = EastMoneySource()
    assert source.load_quotes([]) == []


def test_em_history_with_extra_parts(monkeypatch: Any) -> None:
    """验证 klines 行含超过 7 个逗号字段时仍正确解析。"""
    source = EastMoneySource()

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, Any], timeout: int) -> Any:
        return _make_fake_json(
            {
                "rc": 0,
                "data": {
                    "klines": [
                        "2026-09-01,1300.00,1295.00,1301.00,1290.00,15000,1950000000.00,0.50,0.30,extra",
                        "2026-09-02,1302.80,1297.50,1303.00,1291.20,20308,2634084231.00",
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_history("600519", limit=2)
    assert len(result) == 2
    assert result[0]["date"] == "2026-09-01"
    assert result[0]["amount"] == 1950000000.00
    assert result[1]["date"] == "2026-09-02"
