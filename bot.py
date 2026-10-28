"""Main loop. Paper mode by default.
  python bot.py --paper      (default) simulate fills locally against the live public book
  python bot.py --preview    validate orders with POST /v1/order/preview (needs keys, places nothing)
  python bot.py --live       real orders: needs keys + typed confirmation in a terminal"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config as config_mod
import risk
import strategy
from data import DataError, MarketData
from paper import Ledger, SETTLED_STATES

LOG = Path("logs/decisions.jsonl")
CONFIRM = "I accept the risk"


def log(**fields):
    LOG.parent.mkdir(exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
    line = json.dumps(rec)
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def live_gate(stdin=sys.stdin, input_fn=input):
    if not stdin.isatty():
        return False, "refusing --live: stdin is not a terminal"
    typed = input_fn(f'Type "{CONFIRM}" to trade real money: ')
    if typed.strip() != CONFIRM:
        return False, "confirmation not typed; exiting"
    return True, "confirmed"


def compute_daily_loss(day_start_equity, equity_now):
    return max(0.0, day_start_equity - equity_now)


class Bot:
    def __init__(self, cfg, mode, data=None, ledger=None, broker=None, clock=time.time):
        self.cfg = cfg
        self.mode = mode
        self.data = data or MarketData()
        self.ledger = ledger or Ledger()
        self.broker = broker
        self.rate = risk.RateCounter(clock, times=self.ledger.order_times, on_record=self.ledger.save)
        self.last_summary = None

    @property
    def day_start_equity(self):
        return self.ledger.day_start_equity

    def loop_once(self):
        if risk.kill_switch_on():
            log(event="kill switch on: no orders this loop")
            return
        books, metas, failed = {}, {}, []
        for slug in self.cfg.markets:
            try:
                metas[slug] = self.data.market(slug)
                books[slug] = self.data.book(slug)
            except DataError as e:
                failed.append(slug)
                log(slug=slug, event="data error", error=str(e))
        # held markets not in config still need a mark
        for slug in list(self.ledger.positions):
            if slug not in books and slug not in failed and self.ledger.held(slug):
                try:
                    books[slug] = self.data.book(slug)
                except DataError as e:
                    failed.append(slug)
                    log(slug=slug, event="data error", error=str(e))
        # settle held markets that have resolved; an expired-but-unresolved one counts as missing
        for slug, book in list(books.items()):
            if not self.ledger.held(slug) or book["state"] not in SETTLED_STATES:
                continue
            try:
                status = self.data.market(slug, fresh=True).get("status")
            except DataError as e:
                failed.append(slug)
                log(slug=slug, event="data error", error=str(e))
                continue
            if status == "MARKET_STATUS_RESOLVED" and book["settlement_px"] is not None:
                pnl = self.ledger.settle(slug, book["settlement_px"])
                log(slug=slug, event="settled", settlement_px=book["settlement_px"], realized_pnl=round(pnl, 3))
            else:
                log(slug=slug, event="held market closed but not resolved yet", state=book["state"], status=status)
                del books[slug]
        if failed:
            log(event="no orders this loop: book fetch failed", failed=failed)
            return

        equity, missing = self.ledger.equity(books)
        if missing:
            log(event="no orders this loop: held market has no book", missing=missing)
            return
        today = datetime.now(timezone.utc).date().isoformat()
        if self.ledger.day != today or self.ledger.day_start_equity is None:
            self.ledger.day, self.ledger.day_start_equity = today, equity
            self.ledger.save()
            log(event="new UTC day: daily-loss baseline set", day=today, day_start_equity=round(equity, 3))
        daily_loss = compute_daily_loss(self.day_start_equity, equity)

        for slug in self.cfg.markets:
            book, market = books[slug], metas[slug]
            seen = {"best_bid": book["bids"][0][0] if book["bids"] else None,
                    "best_ask": book["offers"][0][0] if book["offers"] else None,
                    "state": book["state"]}
            order, reason = strategy.decide(slug, market, book, self.ledger.positions, self.cfg.target_price)
            if order is None:
                log(slug=slug, seen=seen, rule=reason, event="no order")
                continue
            ok, why = risk.check_order(order, market, self.cfg.limits,
                                       open_exposure_usd=self.ledger.open_exposure(),
                                       daily_loss_usd=daily_loss, rate=self.rate,
                                       positions=self.ledger.positions)
            if not ok:
                log(slug=slug, seen=seen, rule=reason, risk=why, event="rejected")
                continue
            self.rate.record()
            self.execute(order, book, market, seen, reason)

        self.log_summary(books)

    def execute(self, order, book, market, seen, reason):
        slug = order["marketSlug"]
        if self.mode == "paper":
            theta = float(market.get("feeCoefficient") or 0.0695)
            fills, fee = self.ledger.apply(order, book, theta)
            log(slug=slug, seen=seen, rule=reason, risk="ok", event="paper fill" if fills else "paper no fill",
                fills=fills, fees=round(fee, 2))
        elif self.mode == "preview":
            from broker import BrokerError
            try:
                resp = self.broker.preview_order(order)
                log(slug=slug, seen=seen, rule=reason, risk="ok", event="preview", response=resp)
            except BrokerError as e:
                log(slug=slug, seen=seen, rule=reason, risk="ok", event="preview error", error=str(e))
        else:
            from broker import BrokerError
            try:
                resp = self.broker.create_order(order)
                log(slug=slug, seen=seen, rule=reason, risk="ok", event="live order sent", id=resp.get("id"))
            except BrokerError as e:
                msg = str(e)
                if "Global Rate Limit Exceeded" in msg:
                    log(slug=slug, event="latency stopgap reject (not a rate limit); not retried", error=msg)
                else:
                    log(slug=slug, event="live order error; not retried", error=msg)

    def log_summary(self, books):
        _, unreal, _ = self.ledger.mark(books)
        equity, _ = self.ledger.equity(books)
        s = {"cash": round(self.ledger.cash, 3), "unrealized_pnl": round(unreal, 3),
             "realized_pnl": round(self.ledger.realized_pnl, 3), "fees_paid": round(self.ledger.fees_paid, 2),
             "open_exposure_usd": round(self.ledger.open_exposure(), 3),
             "daily_loss_usd": round(compute_daily_loss(self.day_start_equity, equity), 3)}
        if s != self.last_summary:
            log(event="ledger", **s)
            self.last_summary = s


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--paper", action="store_true", help="default")
    g.add_argument("--preview", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--loops", type=int, default=0, help="stop after N loops (0 = forever)")
    args = ap.parse_args(argv)
    mode = "live" if args.live else "preview" if args.preview else "paper"

    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as e:
        print(f"config error (failing closed): {e}")
        return 2

    broker = None
    if mode in ("preview", "live"):
        from broker import Broker, MissingKeys, load_keys_from_env
        try:
            key_id, secret = load_keys_from_env()
        except MissingKeys as e:
            print(f"--{mode} {e}")
            return 2
        if mode == "live":
            ok, why = live_gate()
            if not ok:
                print(why)
                return 2
        broker = Broker(key_id, secret)

    bot = Bot(cfg, mode, broker=broker)
    log(event="start", mode=mode, markets=cfg.markets, limits=cfg.limits)
    n = 0
    try:
        while True:
            bot.loop_once()
            n += 1
            if args.loops and n >= args.loops:
                break
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        log(event="stopped by user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
