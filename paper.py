"""Local paper ledger. Conservative fills against the live public book.
Also stores the day-start equity and recent order times so restarts don't reset limits."""
import json
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

START_CASH = 100.0
SETTLED_STATES = {"MARKET_STATE_EXPIRED", "MARKET_STATE_TERMINATED"}


def taker_fee_exact(theta, qty, p):
    return Decimal(str(theta)) * Decimal(str(qty)) * Decimal(str(p)) * (1 - Decimal(str(p)))


def round_cent(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def fees_for_fills(theta, fills):
    """Per-fill banker's-rounded fee; order total capped at the rounded cumulative exact fee."""
    exact = [taker_fee_exact(theta, q, p) for p, q in fills]
    per = [round_cent(e) for e in exact]
    excess = sum(per, Decimal(0)) - round_cent(sum(exact, Decimal(0)))
    i = len(per) - 1
    while excess > 0 and i >= 0:
        cut = min(per[i], excess)
        per[i] -= cut
        excess -= cut
        i -= 1
    return per


def simulate_fills(order, book):
    """BUY_LONG / SELL_SHORT lift YES offers <= limit; SELL_LONG / BUY_SHORT hit YES bids >= limit."""
    limit = float(order["price"]["value"])
    remaining = float(order["quantity"])
    if order["intent"] in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_SHORT"):
        levels = [(p, q) for p, q in book["offers"] if p <= limit + 1e-12]
    else:
        levels = [(p, q) for p, q in book["bids"] if p >= limit - 1e-12]
    fills = []
    for p, q in levels:
        if remaining <= 0:
            break
        take = min(q, remaining)
        fills.append((p, take))
        remaining -= take
    return fills


class Ledger:
    def __init__(self, path="paper_ledger.json"):
        self.path = Path(path)
        d = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.cash = d.get("cash", START_CASH)
        self.positions = d.get("positions", {})
        self.realized_pnl = d.get("realized_pnl", 0.0)
        self.fees_paid = d.get("fees_paid", 0.0)
        self.day = d.get("day")
        self.day_start_equity = d.get("day_start_equity")
        self.order_times = d.get("order_times", [])

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "cash": self.cash, "positions": self.positions, "realized_pnl": self.realized_pnl,
            "fees_paid": self.fees_paid, "day": self.day, "day_start_equity": self.day_start_equity,
            "order_times": self.order_times}, indent=2))
        tmp.replace(self.path)

    def held(self, slug):
        p = self.positions.get(slug)
        return bool(p) and (p["yes"] > 0 or p["no"] > 0)

    def apply(self, order, book, theta):
        fills = simulate_fills(order, book)
        if not fills:
            return [], 0.0
        fees = fees_for_fills(theta, fills)
        pos = self.positions.setdefault(order["marketSlug"], {"yes": 0.0, "yes_cost": 0.0, "no": 0.0, "no_cost": 0.0})
        intent = order["intent"]
        for (p, q), fee in zip(fills, fees):
            self.cash -= float(fee)
            self.fees_paid += float(fee)
            if intent == "ORDER_INTENT_BUY_LONG":
                self.cash -= p * q; pos["yes"] += q; pos["yes_cost"] += p * q
            elif intent == "ORDER_INTENT_BUY_SHORT":
                self.cash -= (1 - p) * q; pos["no"] += q; pos["no_cost"] += (1 - p) * q
            elif intent == "ORDER_INTENT_SELL_LONG":
                q = min(q, pos["yes"]); avg = pos["yes_cost"] / pos["yes"] if pos["yes"] else 0
                self.cash += p * q; self.realized_pnl += (p - avg) * q
                pos["yes"] -= q; pos["yes_cost"] -= avg * q
            elif intent == "ORDER_INTENT_SELL_SHORT":
                q = min(q, pos["no"]); avg = pos["no_cost"] / pos["no"] if pos["no"] else 0
                self.cash += (1 - p) * q; self.realized_pnl += ((1 - p) - avg) * q
                pos["no"] -= q; pos["no_cost"] -= avg * q
        self.save()
        return fills, float(sum(fees))

    def settle(self, slug, settlement_px):
        """Close a resolved market: YES pays settlement_px, NO pays 1 - settlement_px.
        Returns realized PnL from the settlement."""
        pos = self.positions.pop(slug)
        proceeds = pos["yes"] * settlement_px + pos["no"] * (1 - settlement_px)
        pnl = proceeds - pos["yes_cost"] - pos["no_cost"]
        self.cash += proceeds
        self.realized_pnl += pnl
        self.save()
        return pnl

    def open_exposure(self):
        return sum(p["yes_cost"] + p["no_cost"] for p in self.positions.values())

    def mark(self, books):
        """Mark at the bid (YES at YES bid, NO at 1 - best YES offer). Never at settlementPx."""
        value, unreal, missing = 0.0, 0.0, []
        for slug, pos in self.positions.items():
            if pos["yes"] <= 0 and pos["no"] <= 0:
                continue
            book = books.get(slug)
            if book is None:
                missing.append(slug)
                continue
            yes_bid = book["bids"][0][0] if book["bids"] else 0.0
            no_bid = 1 - book["offers"][0][0] if book["offers"] else 0.0
            v = pos["yes"] * yes_bid + pos["no"] * no_bid
            value += v
            unreal += v - pos["yes_cost"] - pos["no_cost"]
        return value, unreal, missing

    def equity(self, books):
        value, _, missing = self.mark(books)
        return self.cash + value, missing
