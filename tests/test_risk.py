import pytest
import risk

LIMITS = {"max_contracts_per_order": 2, "max_open_exposure_usd": 5,
          "max_daily_loss_usd": 2, "max_orders_per_minute": 3}
MARKET = {"orderPriceMinTickSize": 0.001, "minimumTradeQty": 1}


def order(px="0.25", qty=1, intent="ORDER_INTENT_BUY_LONG", slug="m"):
    return {"marketSlug": slug, "price": {"value": px, "currency": "USD"}, "quantity": qty, "intent": intent}


def check(o, **kw):
    args = dict(open_exposure_usd=0.0, daily_loss_usd=0.0, rate=risk.RateCounter(), positions={})
    args.update(kw)
    return risk.check_order(o, MARKET, LIMITS, **args)


@pytest.fixture(autouse=True)
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_KILL", raising=False)


def test_ok():
    assert check(order()) == (True, "ok")

def test_kill_file(tmp_path):
    (tmp_path / "KILL").touch()
    assert check(order())[1] == "kill switch on"

def test_kill_env(monkeypatch):
    monkeypatch.setenv("BOT_KILL", "1")
    assert not check(order())[0]

@pytest.mark.parametrize("px", ["0.005", "0.995", "0", "1"])
def test_price_bounds(px):
    ok, why = check(order(px=px))
    assert not ok and "outside" in why

def test_tick():
    ok, why = risk.check_order(order(px="0.255"), {"orderPriceMinTickSize": 0.01, "minimumTradeQty": 1}, LIMITS,
                               open_exposure_usd=0, daily_loss_usd=0, rate=risk.RateCounter(), positions={})
    assert not ok and "tick" in why

def test_min_qty_multiple():
    ok, why = check(order(qty=1.5))
    assert not ok and "minimumTradeQty" in why

def test_max_contracts():
    ok, why = check(order(qty=3))
    assert not ok and "max_contracts" in why

def test_exposure():
    ok, why = check(order(px="0.5", qty=2), open_exposure_usd=4.5)
    assert not ok and "exposure" in why

def test_exposure_no_side_uses_inverse():
    # buying NO with YES price 0.10 costs 0.90 each
    ok, why = check(order(px="0.1", qty=2, intent="ORDER_INTENT_BUY_SHORT"), open_exposure_usd=3.5)
    assert not ok and "exposure" in why

def test_daily_loss():
    ok, why = check(order(), daily_loss_usd=2.0)
    assert not ok and "daily loss" in why

def test_rate():
    t = [1000.0]
    rc = risk.RateCounter(clock=lambda: t[0])
    for _ in range(3):
        rc.record()
    assert "rate" in check(order(), rate=rc)[1]
    t[0] += 61
    assert check(order(), rate=rc)[0]

def test_self_match():
    ok, why = check(order(intent="ORDER_INTENT_BUY_SHORT"), positions={"m": {"yes": 1, "no": 0}})
    assert not ok and "self-match" in why
