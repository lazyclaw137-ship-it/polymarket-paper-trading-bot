"""Hard limits + kill switch. check_order() runs before EVERY order: paper, preview or live."""
import os
import time
from decimal import Decimal
from pathlib import Path

KILL_FILE = Path("KILL")
BUY_INTENTS = {"ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT"}


def kill_switch_on():
    return KILL_FILE.exists() or os.environ.get("BOT_KILL") == "1"


def order_cost(order):
    """Dollars at risk for a buy. NO buys cost 1 - YES price (price.value is always YES)."""
    px = float(order["price"]["value"])
    qty = float(order["quantity"])
    if order["intent"] == "ORDER_INTENT_BUY_SHORT":
        return qty * (1 - px)
    if order["intent"] == "ORDER_INTENT_BUY_LONG":
        return qty * px
    return 0.0


def _on_grid(value, step):
    v, s = Decimal(str(value)), Decimal(str(step))
    return s > 0 and (v / s) == (v / s).to_integral_value()


class RateCounter:
    """Orders sent in the last 60 seconds. `times` can be a list saved in the ledger,
    so a restart keeps the count; `on_record` persists it."""
    def __init__(self, clock=time.time, times=None, on_record=None):
        self.clock = clock
        self.times = times if times is not None else []
        self.on_record = on_record

    def count(self):
        now = self.clock()
        self.times[:] = [t for t in self.times if now - t < 60]
        return len(self.times)

    def record(self):
        self.times.append(self.clock())
        if self.on_record:
            self.on_record()


def check_order(order, market, limits, *, open_exposure_usd, daily_loss_usd,
                rate: RateCounter, positions):
    """Return (ok, reason). Never raises for a bad order; it just says no."""
    if kill_switch_on():
        return False, "kill switch on"
    try:
        px = float(order["price"]["value"])
        qty = float(order["quantity"])
    except (KeyError, TypeError, ValueError):
        return False, "malformed order"

    if not (0.01 <= px <= 0.99):
        return False, f"price {px} outside 0.01-0.99"
    tick = market.get("orderPriceMinTickSize")
    if not tick or not _on_grid(px, tick):
        return False, f"price {px} not on tick {tick}"
    min_qty = market.get("minimumTradeQty")
    if not min_qty or qty <= 0 or not _on_grid(qty, min_qty):
        return False, f"quantity {qty} not a multiple of minimumTradeQty {min_qty}"
    if qty > limits["max_contracts_per_order"]:
        return False, f"quantity {qty} > max_contracts_per_order {limits['max_contracts_per_order']}"

    # self-match: never buy YES and NO on the same market
    pos = positions.get(order["marketSlug"], {})
    if order["intent"] == "ORDER_INTENT_BUY_LONG" and pos.get("no", 0) > 0:
        return False, "self-match: already hold NO on this market"
    if order["intent"] == "ORDER_INTENT_BUY_SHORT" and pos.get("yes", 0) > 0:
        return False, "self-match: already hold YES on this market"

    if order["intent"] in BUY_INTENTS:
        new_exp = open_exposure_usd + order_cost(order)
        if new_exp > limits["max_open_exposure_usd"] + 1e-9:
            return False, f"exposure {new_exp:.2f} > max_open_exposure_usd {limits['max_open_exposure_usd']}"
    if daily_loss_usd >= limits["max_daily_loss_usd"]:
        return False, f"daily loss {daily_loss_usd:.2f} >= max_daily_loss_usd {limits['max_daily_loss_usd']}"
    if rate.count() >= limits["max_orders_per_minute"]:
        return False, f"rate limit: {limits['max_orders_per_minute']} orders/minute"
    return True, "ok"
