from decimal import Decimal
import pytest
from paper import Ledger, fees_for_fills, round_cent, taker_fee_exact, simulate_fills

BOOK = {"bids": [(0.40, 3), (0.38, 10)], "offers": [(0.42, 2), (0.45, 5)], "state": "MARKET_STATE_OPEN"}


@pytest.mark.parametrize("qty,p,theta,expected", [
    (1000, 0.10, 0.0695, "6.26"), (1000, 0.65, 0.0695, "15.81"), (1000, 0.30, 0.0695, "14.60"),
    (1000, 0.90, 0.0695, "6.26"), (1000, 0.50, 0.0695, "17.38"), (1000, 0.50, 0.10, "25.00")])
def test_fee_examples(qty, p, theta, expected):
    assert round_cent(taker_fee_exact(theta, qty, p)) == Decimal(expected)

def test_bankers_rounding():
    assert round_cent(Decimal("0.025")) == Decimal("0.02")
    assert round_cent(Decimal("0.035")) == Decimal("0.04")

def test_fee_cap_across_fills():
    # each fill rounds up to 0.01 but cumulative exact fee is tiny
    fills = [(0.5, 0.3), (0.5, 0.3)]  # exact 0.0052 each -> 0.01 each; cumulative 0.0104 -> 0.01
    assert sum(fees_for_fills(0.0695, fills)) == Decimal("0.01")

def test_partial_fill_walks_levels():
    o = {"marketSlug": "m", "intent": "ORDER_INTENT_BUY_LONG", "price": {"value": "0.45"}, "quantity": 10}
    assert simulate_fills(o, BOOK) == [(0.42, 2), (0.45, 5)]

def test_buy_respects_limit():
    o = {"marketSlug": "m", "intent": "ORDER_INTENT_BUY_LONG", "price": {"value": "0.41"}, "quantity": 1}
    assert simulate_fills(o, BOOK) == []

def test_no_side_trades_against_bids(tmp_path):
    led = Ledger(tmp_path / "l.json")
    o = {"marketSlug": "m", "intent": "ORDER_INTENT_BUY_SHORT", "price": {"value": "0.40"}, "quantity": 2}
    fills, fee = led.apply(o, BOOK, 0.0695)
    assert fills == [(0.40, 2)]
    assert led.positions["m"]["no"] == 2
    assert led.positions["m"]["no_cost"] == pytest.approx(1.2)  # 2 * (1 - 0.40)

def test_sell_hits_bids(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.apply({"marketSlug": "m", "intent": "ORDER_INTENT_BUY_LONG", "price": {"value": "0.42"}, "quantity": 2}, BOOK, 0.0695)
    fills, _ = led.apply({"marketSlug": "m", "intent": "ORDER_INTENT_SELL_LONG", "price": {"value": "0.40"}, "quantity": 2}, BOOK, 0.0695)
    assert fills == [(0.40, 2)]
    assert led.realized_pnl == pytest.approx(-0.04)

def test_mark_at_bid(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.apply({"marketSlug": "m", "intent": "ORDER_INTENT_BUY_LONG", "price": {"value": "0.42"}, "quantity": 1}, BOOK, 0.0695)
    _, unreal, _ = led.mark({"m": BOOK})
    assert unreal == pytest.approx(-0.02)

def test_ledger_persists(tmp_path):
    p = tmp_path / "l.json"
    led = Ledger(p)
    led.apply({"marketSlug": "m", "intent": "ORDER_INTENT_BUY_LONG", "price": {"value": "0.42"}, "quantity": 1}, BOOK, 0.0695)
    assert Ledger(p).positions["m"]["yes"] == 1


def test_settle_yes_winner(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.positions["m"] = {"yes": 1.0, "yes_cost": 0.6, "no": 0.0, "no_cost": 0.0}
    led.cash = 99.4
    assert led.settle("m", 1.0) == pytest.approx(0.4)
    assert led.cash == pytest.approx(100.4) and "m" not in led.positions and led.open_exposure() == 0

def test_settle_no_side(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.positions["m"] = {"yes": 0.0, "yes_cost": 0.0, "no": 2.0, "no_cost": 1.6}
    assert led.settle("m", 1.0) == pytest.approx(-1.6)

def test_open_market_marked_at_bid_not_settlement(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.positions["m"] = {"yes": 1.0, "yes_cost": 0.168, "no": 0.0, "no_cost": 0.0}
    book = {"bids": [(0.167, 10)], "offers": [(0.168, 10)], "state": "MARKET_STATE_OPEN", "settlement_px": 0.09}
    assert led.mark({"m": book})[0] == pytest.approx(0.167)
