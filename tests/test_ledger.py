"""成交台账纯函数：A 股申报规则、数量校验、成交重放。"""

from __future__ import annotations

import pytest
from backend import ledger
from backend.ledger import LedgerError, check_buy_quantity, check_sell_quantity, lot_rule


@pytest.mark.parametrize(
    ("code", "qty"),
    [
        ("600519", 100),
        ("600519", 1200),
        ("300750", 300),
        ("688111", 200),
        ("688111", 201),
        ("830799", 101),
    ],
)
def test_buy_quantity_accepts_board_rules(code: str, qty: int) -> None:
    assert check_buy_quantity(code, qty) == []


@pytest.mark.parametrize(
    ("code", "qty"),
    [
        ("600519", 150),
        ("600519", 0),
        ("600519", -100),
        ("300750", 250),
        ("688111", 199),
        ("830799", 99),
    ],
)
def test_buy_quantity_rejects_board_rules(code: str, qty: int) -> None:
    with pytest.raises(LedgerError) as exc:
        check_buy_quantity(code, qty)
    assert exc.value.code == "QTY_NOT_LOT"
    assert "股" in exc.value.message


def test_etf_lot_is_soft_warning() -> None:
    assert check_buy_quantity("510300", 100) == []
    warnings = check_buy_quantity("510300", 150)
    assert [w["code"] for w in warnings] == ["LOT_WARNING"]
    assert lot_rule("510300").t1 is False


def test_convertible_bond_and_unknown_code_rejected() -> None:
    for code in ("113001", "123456", "999999"):
        with pytest.raises(LedgerError) as exc:
            lot_rule(code)
        assert exc.value.code == "CODE_UNSUPPORTED"


def test_sell_cannot_exceed_available() -> None:
    with pytest.raises(LedgerError) as exc:
        check_sell_quantity("600519", 200, 100)
    assert exc.value.code == "SELL_EXCEEDS_POSITION"
    assert "100" in exc.value.message


def test_odd_lot_must_be_sold_in_one_order() -> None:
    # 北交所持仓 50（不足 100）→ 只能一次卖完
    with pytest.raises(LedgerError) as exc:
        check_sell_quantity("830799", 40, 50)
    assert exc.value.code == "QTY_NOT_LOT"
    assert check_sell_quantity("830799", 50, 50) == []
    # 持仓 150 属正常余额，可取整卖出
    assert check_sell_quantity("830799", 100, 150) == []


def test_ledger_module_exposes_eps() -> None:
    assert ledger.EPS == pytest.approx(1e-9)


# ---------------------------------------------------------------------------
# 成交重放
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from backend.ledger import Fill, replay_fills  # noqa: E402

CST = timezone(timedelta(hours=8))


def cst_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=CST).timestamp() * 1000)


def mk(
    code: str = "600519",
    direction: str = "buy",
    price: float = 10.0,
    qty: int = 100,
    fee: float = 0.0,
    ms: int | None = None,
    **kw: object,
) -> Fill:
    stamp = cst_ms("2026-10-23 10:00") if ms is None else ms
    return Fill(
        id=str(kw.pop("id", f"{code}-{direction}-{stamp}-{qty}")),
        code=code,
        direction=direction,
        price=price,
        qty=qty,
        fee=fee,
        traded_at_ms=stamp,
        created_at_ms=int(kw.pop("created_at_ms", stamp)),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def test_weighted_cost_includes_buy_fee() -> None:
    state = replay_fills([mk(price=10.0, fee=5.0)])
    pos = state.positions["600519"]
    assert pos.qty == 100
    assert pos.cost_basis == pytest.approx(1005.0)
    assert pos.avg_cost == pytest.approx(10.05)


def test_partial_sell_realizes_pnl_with_sell_fee() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    state = replay_fills(
        [
            mk(price=10.0, qty=100, fee=5.0, ms=day1),
            mk(price=12.0, qty=100, fee=5.0, ms=day1, id="b2"),
            mk(direction="sell", price=13.0, qty=150, fee=7.0, ms=day2),
        ]
    )
    pos = state.positions["600519"]
    assert pos.qty == 50
    assert pos.realized_pnl == pytest.approx(150 * (13.0 - 11.05) - 7.0)
    assert pos.cost_basis == pytest.approx(2210.0 - 150 * 11.05)


def test_full_close_zeroes_position() -> None:
    state = replay_fills([mk(price=10.0), mk(direction="sell", price=9.0, ms=cst_ms("2026-10-26 10:00"))])
    pos = state.positions["600519"]
    assert pos.qty == 0 and pos.cost_basis == pytest.approx(0.0)
    assert pos.realized_pnl == pytest.approx(-100.0)


def test_sell_exceeding_position_rejected() -> None:
    with pytest.raises(LedgerError) as exc:
        replay_fills([mk(price=10.0, qty=100), mk(direction="sell", qty=200, ms=cst_ms("2026-10-26 10:00"))])
    assert exc.value.code == "SELL_EXCEEDS_POSITION"


def test_t1_blocks_same_day_sell_for_stock() -> None:
    day = cst_ms("2026-10-23 10:00")
    with pytest.raises(LedgerError) as exc:
        replay_fills([mk(price=10.0, ms=day), mk(direction="sell", price=11.0, ms=day + 3_600_000)])
    assert exc.value.code == "T1_VIOLATION"
    assert "次日" in exc.value.message


def test_etf_allows_same_day_round_trip() -> None:
    day = cst_ms("2026-10-23 10:00")
    state = replay_fills(
        [
            mk(code="510300", price=4.0, qty=100, ms=day),
            mk(code="510300", direction="sell", price=4.1, qty=100, ms=day + 3_600_000),
        ]
    )
    assert state.positions["510300"].qty == 0


def test_voided_fill_not_replayed() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    state = replay_fills([mk(price=10.0, ms=day1), mk(direction="sell", qty=100, ms=day2, voided_at_ms=day2 + 1)])
    assert state.positions["600519"].qty == 100


def test_odd_lot_rules_apply_on_replay() -> None:
    day1, day2, day3 = (
        cst_ms("2026-10-23 10:00"),
        cst_ms("2026-10-26 10:00"),
        cst_ms("2026-10-27 10:00"),
    )
    base = [mk(code="830799", price=10.0, qty=150, ms=day1), mk(code="830799", direction="sell", qty=100, ms=day2)]
    with pytest.raises(LedgerError) as exc:
        replay_fills([*base, mk(code="830799", direction="sell", qty=40, ms=day3)])
    assert exc.value.code == "QTY_NOT_LOT"
    state = replay_fills([*base, mk(code="830799", direction="sell", qty=50, ms=day3)])
    assert state.positions["830799"].qty == 0


def test_replay_orders_by_traded_at_then_created_at() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    # 输入乱序：卖出在前，仍应按时间重放成功
    state = replay_fills([mk(direction="sell", qty=100, ms=day2), mk(price=10.0, ms=day1)])
    assert state.positions["600519"].qty == 0
