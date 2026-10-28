# Polymarket US paper-trading bot (built with Claude Code)

Starter code for the BotCookery recipe **[polymarket-bot-claude-code-paper-mode](https://botcookery.com/recipes/polymarket-bot-claude-code-paper-mode/)**. The recipe page has the step-by-step guide, the prompt, the findings and the safety notes; this repo is the code that came out of it.

## What it is

A paper-mode Python bot for **Polymarket US** markets, built from the recipe's Claude Code prompt (`PROMPT.md`). It reads live public order books, applies a placeholder buy rule, checks hard limits, and fills orders against the live book in a local paper ledger. The ledger keeps the day's starting equity and recent order times, so a restart doesn't reset the daily-loss or orders-per-minute limits. Resolved markets settle at their settlement price. `CLAUDE.md` and `.claude/settings.json` are the BotCookery safety rules for Claude Code.

## What was actually tested

- Mode: **paper**
- Date: 2026-10-26
- Limits: Order preview and real orders need your own keys and were not run.

The recipe page has the full findings, dated sample output and the prompt this code came from. The code was written by an AI coding assistant from that prompt, then run as described above. Market tickers and slugs in the config were live when it was tested and will expire; swap in current ones.

## Setup

Python 3.11 or newer.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Run it (no money)

Put open Polymarket US market slugs in `config.toml`, then:

```bash
python bot.py --paper --loops 5
```

Paper is the default. Each loop prints one JSON line per market (what it saw, the rule, the risk check, the paper fill) and a ledger line (cash, unrealized P&L, fees, exposure, daily loss). The paper ledger is written to `paper_ledger.json` (git-ignored).

`python cancel_all.py` cancels open orders when keys are set.

## Safety notes

- `--preview` and `--live` exist but were **not** run. Live needs keys plus a typed confirmation.
- Keys come from env vars (`POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY`); never commit them.
- Limits are in `limits.json`; `touch KILL` or `BOT_KILL=1` stops new orders.
- The buy rule is a placeholder to exercise the code, not a strategy.

## Not financial advice

This is example code for learning how these APIs work. It is not financial advice, not a strategy, and not a recommendation to trade anything. The placeholder rules and prices in the config are there to exercise the code, not forecasts. You are responsible for anything you run, especially with real keys or real money.

## License

MIT. See [LICENSE](LICENSE).
