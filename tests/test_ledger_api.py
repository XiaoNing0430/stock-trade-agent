"""成交台账存储层 + API：CRUD / 幂等 / 作废 / 持仓派生。"""

from __future__ import annotations

import pytest
from backend import storage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    storage.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(storage, "SessionLocal", factory)
    return factory


def _fill(**kw):
    data = {
        "id": "fill_a1",
        "clientRequestId": "req_a1",
        "code": "600519",
        "direction": "buy",
        "price": 10.0,
        "qty": 100,
        "fee": 5.0,
        "tradedAtMs": 1_760_000_000_000,
        "planId": None,
        "note": "",
    }
    data.update(kw)
    return data


def test_create_and_list_fill(factory):
    row = storage.create_trade_fill(_fill())
    assert row["id"] == "fill_a1" and row["tradedAtMs"] == 1_760_000_000_000
    assert row["voidedAtMs"] is None and row["planId"] is None
    rows = storage.list_trade_fills()
    assert [r["id"] for r in rows] == ["fill_a1"]
    assert storage.find_trade_fill_by_request("req_a1")["id"] == "fill_a1"
    assert storage.get_trade_fill("fill_a1")["code"] == "600519"


def test_list_orders_by_traded_at_desc(factory):
    storage.create_trade_fill(_fill(id="fill_old", clientRequestId="r1", tradedAtMs=1_700_000_000_000))
    storage.create_trade_fill(_fill(id="fill_new", clientRequestId="r2", tradedAtMs=1_760_000_000_000))
    assert [r["id"] for r in storage.list_trade_fills()] == ["fill_new", "fill_old"]
    assert [r["id"] for r in storage.list_trade_fills(code="510300")] == []


def test_update_fill_fields(factory):
    storage.create_trade_fill(_fill())
    updated = storage.update_trade_fill("fill_a1", {"price": 10.5, "qty": 200, "note": "改"}, 1_760_000_100_000)
    assert updated["price"] == 10.5 and updated["qty"] == 200 and updated["note"] == "改"


def test_void_fill_is_idempotent_and_hidden_by_default(factory):
    storage.create_trade_fill(_fill())
    first = storage.void_trade_fill("fill_a1", "录错", 1_760_000_200_000)
    second = storage.void_trade_fill("fill_a1", "再点一次", 1_760_000_300_000)
    assert first["voidedAtMs"] == second["voidedAtMs"] == 1_760_000_200_000
    assert first["voidReason"] == "录错"
    assert storage.list_trade_fills() == []
    assert [r["id"] for r in storage.list_trade_fills(include_voided=True)] == ["fill_a1"]


def test_missing_fill_returns_none(factory):
    assert storage.update_trade_fill("nope", {"price": 1.0}, 1) is None
    assert storage.void_trade_fill("nope", "", 1) is None
