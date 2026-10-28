"""LIVE adapter for https://api.polymarket.us. Ed25519-signed requests.
Keys only from env vars. Never printed."""
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives.asymmetric import ed25519

API = "https://api.polymarket.us"
RETRY_STATUS = {429, 500, 502, 503, 504}


class BrokerError(Exception):
    pass


class MissingKeys(BrokerError):
    pass


def load_keys_from_env():
    key_id = os.environ.get("POLYMARKET_KEY_ID", "").strip()
    secret = os.environ.get("POLYMARKET_SECRET_KEY", "").strip()
    if not key_id or not secret:
        raise MissingKeys("needs API keys: set POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY")
    return key_id, secret


class Broker:
    def __init__(self, key_id, secret_b64, session=None, clock=time.time,
                 sent_path="sent_orders.json", sleep=time.sleep):
        self.key_id = key_id
        # secret key is base64; the first 32 decoded bytes are the Ed25519 seed
        self._pk = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret_b64)[:32])
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.sent_path = Path(sent_path)

    def __repr__(self):
        return "Broker(key_id=***)"

    def headers(self, method, path):
        ts = str(int(self.clock() * 1000))
        sig = base64.b64encode(self._pk.sign(f"{ts}{method}{path}".encode())).decode()
        return {"X-PM-Access-Key": self.key_id, "X-PM-Timestamp": ts,
                "X-PM-Signature": sig, "Content-Type": "application/json"}

    def _request(self, method, path, body=None, retry=True, max_retries=4):
        last = None
        for attempt in range(max_retries + 1 if retry else 1):
            try:
                r = self.session.request(method, API + path, headers=self.headers(method, path),
                                         data=json.dumps(body) if body is not None else None, timeout=10)
            except requests.RequestException as e:
                last = f"network error: {type(e).__name__}"
                if not retry:
                    raise BrokerError(f"{method} {path}: {last} (outcome unknown, check open orders)")
            else:
                if r.status_code == 200:
                    return r.json()
                if not retry or r.status_code not in RETRY_STATUS:
                    raise BrokerError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
                last = f"HTTP {r.status_code}"
            if attempt < max_retries:
                self.sleep(2 ** attempt)
        raise BrokerError(f"{method} {path} failed after retries ({last})")

    # --- reads (retried) ---
    def positions(self):
        return self._request("GET", "/v1/portfolio/positions")

    def balances(self):
        return self._request("GET", "/v1/account/balances")

    def open_orders(self):
        return self._request("GET", "/v1/orders/open")

    # --- orders ---
    def preview_order(self, order):
        return self._request("POST", "/v1/order/preview", {"request": order})

    def _sent(self):
        return json.loads(self.sent_path.read_text()) if self.sent_path.exists() else {}

    def create_order(self, order):
        """No client order id on Polymarket US: record locally BEFORE sending, never auto-retry."""
        sent = self._sent()
        key = hashlib.sha256((json.dumps(order, sort_keys=True) + secrets.token_hex(8)).encode()).hexdigest()
        if key in sent:
            raise BrokerError("duplicate order key; refusing to resend")
        sent[key] = {"ts": self.clock(), "order": order, "status": "sending"}
        self.sent_path.write_text(json.dumps(sent, indent=1))
        try:
            resp = self._request("POST", "/v1/orders", order, retry=False)
        except BrokerError as e:
            sent[key]["status"] = f"unknown/failed: {e}"
            self.sent_path.write_text(json.dumps(sent, indent=1))
            raise
        sent[key]["status"] = "sent"
        sent[key]["id"] = resp.get("id")
        self.sent_path.write_text(json.dumps(sent, indent=1))
        return resp

    def cancel_all(self, slugs=None):
        return self._request("POST", "/v1/orders/open/cancel", {"slugs": slugs or []})
