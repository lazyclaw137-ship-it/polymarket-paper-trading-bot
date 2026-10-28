"""Public market data from https://gateway.polymarket.us (no keys)."""
import time
import requests

GATEWAY = "https://gateway.polymarket.us"
RETRY_STATUS = {429, 500, 502, 503, 504}


class DataError(Exception):
    pass


def _retry_after(r):
    try:
        return max(0.0, float(r.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 0.0


def _get(session, path, params=None, max_retries=4, base_delay=1.0, sleep=time.sleep):
    """GET with bounded exponential backoff on 429/5xx and network errors.
    A 429 waits at least Retry-After; its body may be HTML so it is never parsed."""
    url = GATEWAY + path
    last = None
    for attempt in range(max_retries + 1):
        wait = base_delay * (2 ** attempt)
        try:
            r = session.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            last = f"network error: {type(e).__name__}"
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code not in RETRY_STATUS:
                raise DataError(f"GET {path} -> HTTP {r.status_code}: {r.text[:200]}")
            last = f"HTTP {r.status_code}"
            if r.status_code == 429:
                wait = max(wait, _retry_after(r))
        if attempt < max_retries:
            sleep(wait)
    raise DataError(f"GET {path} failed after {max_retries + 1} tries ({last})")


class MarketData:
    def __init__(self, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self._meta = {}

    def list_markets(self, limit=20):
        return _get(self.session, "/v1/markets",
                    {"active": "true", "closed": "false", "limit": limit}, sleep=self.sleep)["markets"]

    def market(self, slug, fresh=False):
        """Market metadata (tick, min qty, fee coefficient, status). Cached 5 minutes."""
        now = time.time()
        hit = self._meta.get(slug)
        if hit and not fresh and now - hit[0] < 300:
            return hit[1]
        m = _get(self.session, f"/v1/market/slug/{slug}", sleep=self.sleep)["market"]
        self._meta[slug] = (now, m)
        return m

    def book(self, slug):
        """Returns {"bids": [(px, qty)] best first, "offers": [...] best first, "state", "settlement_px"}.
        Prices are YES-side."""
        md = _get(self.session, f"/v1/markets/{slug}/book", sleep=self.sleep)["marketData"]
        bids = sorted(((float(l["px"]["value"]), float(l["qty"])) for l in md.get("bids") or []), key=lambda x: -x[0])
        offers = sorted(((float(l["px"]["value"]), float(l["qty"])) for l in md.get("offers") or []), key=lambda x: x[0])
        sp = ((md.get("stats") or {}).get("settlementPx") or {}).get("value")
        return {"bids": bids, "offers": offers, "state": md.get("state"),
                "settlement_px": float(sp) if sp not in (None, "") else None}

    def bbo(self, slug):
        return _get(self.session, f"/v1/markets/{slug}/bbo", sleep=self.sleep)["marketData"]
