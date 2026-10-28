import io
import pytest
import bot
from config import Config
from data import DataError
from paper import Ledger

LIMITS = {"max_contracts_per_order": 1, "max_open_exposure_usd": 5, "max_daily_loss_usd": 2, "max_orders_per_minute": 2}
MKT = {"orderPriceMinTickSize": 0.001, "minimumTradeQty": 1, "feeCoefficient": 0.0695, "status": "MARKET_STATUS_OPEN"}


def book(bid, ask, state="MARKET_STATE_OPEN", sp=None):
    return {"bids": [(bid, 100)] if bid else [], "offers": [(ask, 100)] if ask else [], "state": state, "settlement_px": sp}


class FakeData:
    def __init__(self, books, status=None):
        self.books, self.status = books, status or {}
    def market(self, slug, fresh=False):
        return {**MKT, "status": self.status.get(slug, "MARKET_STATUS_OPEN")}
    def book(self, slug):
        b = self.books.get(slug)
        if b is None:
            raise DataError("HTTP 503")
        return b


@pytest.fixture(autouse=True)
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_KILL", raising=False)


def test_live_gate_refuses_non_tty():
    assert bot.live_gate(stdin=io.StringIO(""))[0] is False

def test_live_gate_needs_phrase():
    class T(io.StringIO):
        def isatty(self): return True
    assert bot.live_gate(stdin=T(), input_fn=lambda _: "yes")[0] is False
    assert bot.live_gate(stdin=T(), input_fn=lambda _: "I accept the risk")[0] is True

def test_buys_once(tmp_path):
    b = bot.Bot(Config(["a"], 1, 0.3, LIMITS), "paper", data=FakeData({"a": book(0.19, 0.20)}), ledger=Ledger(tmp_path / "l.json"))
    b.loop_once(); b.loop_once()
    assert b.ledger.positions["a"]["yes"] == 1

def test_missing_held_book_blocks_orders(tmp_path):
    data = FakeData({"a": book(0.19, 0.20), "b": book(0.19, 0.20)})
    b = bot.Bot(Config(["a", "b"], 1, 0.3, LIMITS), "paper", data=data, ledger=Ledger(tmp_path / "l.json"))
    b.loop_once()
    data.books = {"a": book(0.19, 0.20)}
    b.ledger.positions["a"]["yes"] = 0
    b.loop_once()
    assert b.ledger.positions["a"]["yes"] == 0

def test_daily_loss_formula():
    assert bot.compute_daily_loss(100, 99.5) == 0.5
    assert bot.compute_daily_loss(100, 101) == 0

def test_restart_keeps_daily_loss(tmp_path):
    p = tmp_path / "l.json"
    data = FakeData({"a": book(0.19, 0.20)})
    b1 = bot.Bot(Config(["a"], 1, 0.3, LIMITS), "paper", data=data, ledger=Ledger(p))
    b1.loop_once()
    data.books["a"] = book(0.05, 0.06)  # price drops
    b2 = bot.Bot(Config(["a"], 1, 0.3, LIMITS), "paper", data=data, ledger=Ledger(p))  # restart
    b2.loop_once()
    eq, _ = b2.ledger.equity(data.books)
    assert b2.day_start_equity == pytest.approx(100.0)
    assert bot.compute_daily_loss(b2.day_start_equity, eq) == pytest.approx(0.16)  # 0.20 cost + 0.01 fee, marked at 0.05

def test_restart_keeps_per_minute_count(tmp_path):
    p = tmp_path / "l.json"
    data = FakeData({"a": book(0.19, 0.20), "b": book(0.19, 0.20), "c": book(0.19, 0.20)})
    t = [1000.0]
    b1 = bot.Bot(Config(["a", "b", "c"], 1, 0.3, LIMITS), "paper", data=data, ledger=Ledger(p), clock=lambda: t[0])
    b1.loop_once()
    assert "c" not in b1.ledger.positions  # 2/min cap
    t[0] += 8
    b2 = bot.Bot(Config(["a", "b", "c"], 1, 0.3, LIMITS), "paper", data=data, ledger=Ledger(p), clock=lambda: t[0])
    b2.loop_once()
    assert "c" not in b2.ledger.positions
    t[0] += 60
    b2.loop_once()
    assert b2.ledger.positions["c"]["yes"] == 1

def test_resolved_market_settles_not_marked_zero(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.positions["r"] = {"yes": 1.0, "yes_cost": 0.6, "no": 0.0, "no_cost": 0.0}
    led.cash = 99.4
    data = FakeData({"a": book(0.19, 0.25), "r": book(None, None, "MARKET_STATE_EXPIRED", 1.0)},
                    status={"r": "MARKET_STATUS_RESOLVED"})
    b = bot.Bot(Config(["a"], 1, 0.2, LIMITS), "paper", data=data, ledger=led)
    b.loop_once()
    assert "r" not in led.positions and led.cash == pytest.approx(100.4)
    assert led.realized_pnl == pytest.approx(0.4)

def test_expired_but_unresolved_blocks_orders(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.positions["r"] = {"yes": 1.0, "yes_cost": 0.6, "no": 0.0, "no_cost": 0.0}
    data = FakeData({"a": book(0.19, 0.20), "r": book(None, None, "MARKET_STATE_EXPIRED", 1.0)},
                    status={"r": "MARKET_STATUS_RESOLVING"})
    b = bot.Bot(Config(["a"], 1, 0.3, LIMITS), "paper", data=data, ledger=led)
    b.loop_once()
    assert "a" not in led.positions and "r" in led.positions
