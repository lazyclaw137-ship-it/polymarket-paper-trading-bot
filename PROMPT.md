# Prompt used for this build: published prompt as edited 2026-10-26 (pass 2)

Build a Polymarket US trading bot in Python 3.11+ (requests, cryptography,
pytest only) that runs in PAPER MODE by default. Use only endpoints documented
at https://docs.polymarket.us. If you are unsure an endpoint or field exists,
ask me instead of guessing.

Read CLAUDE.md (the BotCookery safety rules) first and follow it. If you are
not allowed to write under .claude/, tell me and I will approve it; do not
work around it.

Architecture (one file per module):
- config.py   : loads config.toml (markets = list of slugs, poll_seconds,
                target_price) and limits.json (max_contracts_per_order,
                max_open_exposure_usd, max_daily_loss_usd,
                max_orders_per_minute). Fail closed if a limit is missing.
- data.py     : public market data from https://gateway.polymarket.us, no keys:
                GET /v1/markets?active=true&closed=false&limit=20 (listing),
                GET /v1/market/slug/{slug} (response {"market": {...}}; read
                orderPriceMinTickSize and minimumTradeQty; cache 5 min),
                GET /v1/markets/{slug}/book (response
                {"marketData": {"bids":[{"px":{"value"},"qty"}],"offers":[...],
                "state"}}; px.value and qty are strings; prices are YES-side),
                GET /v1/markets/{slug}/bbo.
                Also return the book's stats.settlementPx.
                Bounded exponential backoff on 429/5xx. On a 429, wait at
                least the Retry-After header if there is one; the 429 body
                can be HTML, so don't parse it as JSON.
- strategy.py : ONE placeholder rule I will replace: "if the market state is
                MARKET_STATE_OPEN, I hold no YES on it yet, and best YES offer
                <= target_price from config, propose buying minimumTradeQty
                of YES at the best offer". Return an order body dict or None,
                plus a one-line reason. No ML, no "AI picks".
- risk.py     : check_order() enforcing every limit in limits.json plus: price
                within 0.01-0.99 AND on the market's tick, quantity a multiple
                of minimumTradeQty, no YES+NO buys on the same market
                (self-match), and a kill switch (file KILL exists or BOT_KILL=1
                => no orders). Unit-test every rule.
- paper.py    : local ledger (paper_ledger.json). Fill conservatively against
                the current book: buys lift offers at or below my limit, sells
                hit bids at or above it, at the displayed price, never more
                than displayed size, walking levels. NO intents trade the
                inverse (BUY_SHORT fills against YES bids at cost 1 - bid).
                Taker fee = theta * qty * p * (1-p), theta = the market's
                feeCoefficient (0.0695 standard; Table Tennis 0.10, see
                https://docs.polymarket.us/fees), rounded to $0.01 per fill
                with banker's rounding (round half to even), total for one
                order capped at the rounded cumulative fee. Test against
                the fee page's worked examples. Track cash, positions, realized
                and unrealized PnL (mark at the bid).
                Settlement: when a held market's book state is
                MARKET_STATE_EXPIRED or MARKET_STATE_TERMINATED, check
                GET /v1/market/slug/{slug}; if status is
                MARKET_STATUS_RESOLVED, close the position at the book's
                stats.settlementPx (YES gets px, NO gets 1 - px) into realized
                PnL and cash. If it isn't resolved yet, treat it like a
                missing book. Never mark an OPEN market at settlementPx; open
                markets carry one too and it can be far from the bid.
- broker.py   : LIVE adapter for https://api.polymarket.us. Ed25519: the secret
                key from env is base64; the first 32 decoded bytes are the
                seed. Headers X-PM-Access-Key, X-PM-Timestamp (ms, within 30 s
                of server time), X-PM-Signature = base64(sign(timestamp +
                METHOD + path)), e.g. path "/v1/portfolio/positions"; the body
                is not signed. Methods: preview_order (POST /v1/order/preview,
                body wrapped as {"request": order}), create_order
                (POST /v1/orders), cancel_all (POST /v1/orders/open/cancel,
                body {"slugs": []}), positions (GET /v1/portfolio/positions),
                balances (GET /v1/account/balances).
                Order body: marketSlug, type ORDER_TYPE_LIMIT, price
                {value, currency "USD"} (ALWAYS the YES price: buying NO at
                0.83 sends 0.17), quantity (number), tif
                TIME_IN_FORCE_IMMEDIATE_OR_CANCEL, intent, and
                manualOrderIndicator MANUAL_ORDER_INDICATOR_AUTOMATIC.
- bot.py      : main loop. Default --paper. --preview calls the preview
                endpoint with my key but never places orders (exit with a
                clear message if keys are missing). --live requires the flag,
                keys, AND typing "I accept the risk"; refuse if stdin is not a
                terminal. Every loop: kill-switch check -> fetch the book for
                EVERY configured market first (if any fetch fails, log it and
                place nothing this loop: you can't mark positions) -> strategy
                -> risk -> paper/preview/live -> log to logs/decisions.jsonl.
                Daily loss passed to risk = max(0, equity at the first loop of
                the UTC day - equity now), where equity = cash + every position
                marked at the bid using THIS loop's books. Log the ledger
                summary only when it changes.
                Restarts must not reset the limits: save the UTC date, the
                day-start equity and the send times of the last minute's
                orders in paper_ledger.json, and reload them on start.
- cancel_all.py : one command that calls cancel-all in live mode.

Rules:
- Keys only from env vars (POLYMARKET_KEY_ID, POLYMARKET_SECRET_KEY).
  .env.example with blanks; .env in .gitignore; never print keys.
- Bounded exponential backoff on 429/5xx for reads and cancels. A "Global Rate
  Limit Exceeded" reject on an order is a latency stopgap, not a rate limit:
  log it, don't retry.
- The order API has no client order id, so do idempotency locally: record a
  key (hash of order + nonce) in sent_orders.json BEFORE sending, never
  re-send a recorded key, and never auto-retry POST /v1/orders after a
  timeout or 5xx (outcome unknown; check open orders instead).
- pytest tests for risk.py (each rule), paper.py fills (partial, NO side,
  sells, fee examples), the YES-price inversion, the live-mode gate, broker
  signing (verify with the public key) using a fake HTTP session, daily
  loss (a held market with no book this loop must block orders, not count
  as a loss), a restart (a new Bot on the same ledger keeps the day's loss
  and the per-minute count), settlement of a resolved market at
  settlementPx, and a 429 with Retry-After.

Show me the file plan first. Then build it. Then give me the exact commands
to run it in paper mode.