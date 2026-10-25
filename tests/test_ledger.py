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
