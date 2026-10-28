"""ONE placeholder rule. Replace it with your own. No ML, no 'AI picks'."""


def decide(slug, market, book, ledger_positions, target_price):
    """Return (order_body or None, one-line reason)."""
    state = book.get("state")
    if state != "MARKET_STATE_OPEN":
        return None, f"market state {state}, not open"
    pos = ledger_positions.get(slug, {})
    if pos.get("yes", 0) > 0:
        return None, "already hold YES here (placeholder buys once per market)"
    if not book["offers"]:
        return None, "no YES offers on the book"
    best_ask = book["offers"][0][0]
    if best_ask > target_price:
        return None, f"best YES offer {best_ask} > target {target_price}"
    qty = float(market.get("minimumTradeQty") or 1)
    order = {
        "marketSlug": slug,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": f"{best_ask:.4f}".rstrip("0").rstrip("."), "currency": "USD"},
        "quantity": qty,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "intent": "ORDER_INTENT_BUY_LONG",
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
    }
    return order, f"best YES offer {best_ask} <= target {target_price}: buy {qty:g} YES"
