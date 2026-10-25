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


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

from backend import app as app_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(factory, monkeypatch):
    monkeypatch.setattr(storage, "SessionLocal", factory)
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


def _post(client, **kw):
    payload = {
        "code": "600519",
        "direction": "buy",
        "price": 10.0,
        "qty": 100,
        "fee": 5.0,
        "tradedAtMs": 1_760_000_000_000,
        "clientRequestId": "req_x",
    }
    payload.update(kw)
    return client.post("/api/fills", json=payload)


def test_create_fill_returns_row(client):
    res = _post(client)
    assert res.status_code == 201
    body = res.json()
    assert body["fill"]["code"] == "600519" and body["fill"]["qty"] == 100
    assert body["warnings"] == []
    assert body["planMissing"] is False


def test_duplicate_request_id_is_idempotent(client):
    first = _post(client).json()["fill"]
    second = _post(client).json()["fill"]
    assert second["id"] == first["id"]
    assert len(client.get("/api/fills").json()["items"]) == 1


def test_request_id_payload_mismatch_rejected(client):
    _post(client)
    res = _post(client, qty=200)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "IDEMPOTENCY_MISMATCH"


def test_board_lot_violation_is_chinese_422(client):
    res = _post(client, qty=150)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "QTY_NOT_LOT" and "100 股" in detail["error"]


def test_sell_without_position_rejected(client):
    res = _post(client, direction="sell", qty=100)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "SELL_EXCEEDS_POSITION"


def test_update_and_void_flow(client):
    fill = _post(client).json()["fill"]
    updated = client.put(f"/api/fills/{fill['id']}", json={"price": 11.0, "note": "改价"})
    assert updated.status_code == 200 and updated.json()["fill"]["price"] == 11.0
    voided = client.post(f"/api/fills/{fill['id']}/void", json={"reason": "录错"})
    assert voided.status_code == 200 and voided.json()["fill"]["voidReason"] == "录错"
    again = client.put(f"/api/fills/{fill['id']}", json={"price": 12.0})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "FILL_VOIDED"
    assert client.get("/api/fills").json()["items"] == []
    assert len(client.get("/api/fills?includeVoided=true").json()["items"]) == 1


def test_unknown_fill_is_404(client):
    res = client.put("/api/fills/nope", json={"price": 1.0})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "FILL_NOT_FOUND"


def test_positions_derived_with_quote(client, monkeypatch):
    _post(client)
    monkeypatch.setattr(
        app_module,
        "_load_quotes_for_codes",
        lambda codes: ({"600519": {"code": "600519", "name": "贵州茅台", "price": 12.0}}, []),
    )
    body = client.get("/api/positions").json()
    pos = body["positions"][0]
    assert pos["code"] == "600519" and pos["qty"] == 100
    assert pos["avgCost"] == pytest.approx(10.05)
    assert pos["lastPrice"] == 12.0 and pos["marketValue"] == pytest.approx(1200.0)
    assert pos["unrealizedPnl"] == pytest.approx(195.0)
    assert body["totals"]["marketValue"] == pytest.approx(1200.0)
    assert any("不复权" in text for text in body["disclosures"])


def test_positions_without_quote_are_blank(client, monkeypatch):
    _post(client)
    monkeypatch.setattr(app_module, "_load_quotes_for_codes", lambda codes: ({}, ["600519"]))
    body = client.get("/api/positions").json()
    pos = body["positions"][0]
    assert pos["lastPrice"] is None and pos["marketValue"] is None and pos["unrealizedPnl"] is None
    assert body["totals"]["marketValue"] is None
    assert any("600519" in text for text in body["disclosures"])
