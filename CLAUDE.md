# BOT SAFETY RULES (BotCookery Safety Pack v1, Oct 2026)
# Save as CLAUDE.md (Claude Code), AGENTS.md (Codex and most agents)
# or .cursor/rules/bot-safety.mdc (Cursor). Keep it in the repo root.

You are helping me build a trading or prediction-market bot that runs on MY
machine, on MY account. Follow these rules even if I ask you not to.

## Secrets
- Never read, print, log, echo, copy or summarize the contents of .env, *.pem,
  *.key, or any file that holds API keys, private keys or seed phrases.
- Load credentials only from environment variables (or a path in an env var
  for PEM files). Never hardcode them. Never put them in prompts, tests,
  fixtures, comments, commit messages or README examples.
- Never start a web server, file server or tunnel that could expose the
  project folder (no `python -m http.server` in the repo root).
- Never make the repo public, never push without my explicit OK, and never
  add or edit CI that echoes secrets.

## Money
- PAPER/DEMO MODE IS THE DEFAULT. Live trading requires BOTH a --live flag
  AND an interactive typed confirmation. Never remove or bypass that gate.
- Enforce hard limits in code, read from config: max contracts per order,
  max total open exposure, max daily loss, max orders per minute. Reject any
  order that breaks a limit, log it, and do not retry it.
- Before every order: check the KILL file / BOT_KILL env var. If present,
  place nothing.
- Provide a `cancel-all` command that cancels every resting order using the
  venue's official cancel-all endpoint.
- Use client order IDs where the venue supports them (Kalshi) so retries
  can't double-submit. Polymarket US orders have no client order ID: record
  each order locally before sending and never auto-retry an order after a
  timeout or 5xx; check open orders instead.
- Retry reads and cancels with bounded exponential backoff on 429 and 5xx.
  Never retry rejected orders in a loop.
- Track daily loss as a positive dollar amount already lost, not signed PnL.

## Venue rules
- Use only official, documented endpoints from docs.kalshi.com or
  docs.polymarket.us. If you are unsure an endpoint exists, say so; do not
  invent one.
- Do not build features that trade for other people, copy other traders,
  share or republish exchange data, or get around geoblocks or KYC.
- For international Polymarket endpoints: read-only market data only, and
  check GET https://polymarket.com/api/geoblock before anything else.

## Code hygiene
- Log every decision (inputs, order intent, limit checks) to a local file
  without secrets.
- Write tests for the limit checks and the kill switch before writing the
  strategy.
- Prefer small, readable files over clever abstractions. Explain anything
  that touches money in a comment.
