import base64, json
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import broker as broker_mod
from broker import Broker, BrokerError


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.text = status, body or {}, json.dumps(body or {})
    def json(self):
        return self._b


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append((method, url, headers, data))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(responses, tmp_path):
    pk = ed25519.Ed25519PrivateKey.generate()
    seed = pk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    secret = base64.b64encode(seed + pk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    s = FakeSession(responses)
    b = Broker("kid", secret, session=s, clock=lambda: 1700000000.123, sent_path=tmp_path / "sent.json", sleep=lambda x: None)
    return b, s, pk.public_key()


ORDER = {"marketSlug": "m", "type": "ORDER_TYPE_LIMIT", "price": {"value": "0.17", "currency": "USD"},
         "quantity": 1, "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL", "intent": "ORDER_INTENT_BUY_SHORT",
         "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC"}


def test_signature_verifies(tmp_path):
    b, s, pub = make([FakeResp(200, {"positions": []})], tmp_path)
    b.positions()
    _, url, h, _ = s.calls[0]
    assert url.endswith("/v1/portfolio/positions")
    assert h["X-PM-Timestamp"] == "1700000000123"
    pub.verify(base64.b64decode(h["X-PM-Signature"]), b"1700000000123GET/v1/portfolio/positions")

def test_preview_wraps_request(tmp_path):
    b, s, _ = make([FakeResp(200, {})], tmp_path)
    b.preview_order(ORDER)
    assert json.loads(s.calls[0][3]) == {"request": ORDER}

def test_create_order_not_retried_on_5xx(tmp_path):
    b, s, _ = make([FakeResp(503), FakeResp(200, {"id": "x"})], tmp_path)
    with pytest.raises(BrokerError):
        b.create_order(ORDER)
    assert len(s.calls) == 1
    sent = json.loads((tmp_path / "sent.json").read_text())
    assert list(sent.values())[0]["status"].startswith("unknown")

def test_reads_retry_429(tmp_path):
    b, s, _ = make([FakeResp(429), FakeResp(200, {"ok": 1})], tmp_path)
    assert b.balances() == {"ok": 1}
    assert len(s.calls) == 2

def test_cancel_all_body(tmp_path):
    b, s, _ = make([FakeResp(200, {"canceledOrderIds": []})], tmp_path)
    b.cancel_all()
    assert s.calls[0][1].endswith("/v1/orders/open/cancel")
    assert json.loads(s.calls[0][3]) == {"slugs": []}

def test_yes_price_inversion_for_no_buy():
    # buying NO at 0.83 sends YES price 0.17
    from risk import order_cost
    assert ORDER["price"]["value"] == "0.17"
    assert order_cost(ORDER) == pytest.approx(0.83)

def test_missing_keys(monkeypatch):
    monkeypatch.delenv("POLYMARKET_KEY_ID", raising=False)
    monkeypatch.delenv("POLYMARKET_SECRET_KEY", raising=False)
    with pytest.raises(broker_mod.MissingKeys):
        broker_mod.load_keys_from_env()
