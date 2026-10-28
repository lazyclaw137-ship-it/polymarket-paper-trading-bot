import data


class R:
    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code, self._b, self.headers, self.text = status, body, headers or {}, text
    def json(self):
        if self._b is None:
            raise ValueError("not json")
        return self._b


class S:
    def __init__(self, rs):
        self.rs = list(rs)
    def get(self, url, params=None, timeout=None):
        return self.rs.pop(0)


def test_429_honors_retry_after_and_html_body():
    waits = []
    s = S([R(429, None, {"Retry-After": "10"}, "<html>Too Many Requests</html>"), R(200, {"ok": 1})])
    assert data._get(s, "/v1/x", sleep=waits.append) == {"ok": 1}
    assert waits == [10.0]

def test_429_without_header_uses_backoff():
    waits = []
    s = S([R(429), R(429), R(200, {"ok": 1})])
    data._get(s, "/v1/x", sleep=waits.append)
    assert waits == [1.0, 2.0]

def test_book_reads_settlement_px():
    md = {"marketData": {"bids": [], "offers": [], "state": "MARKET_STATE_EXPIRED",
                         "stats": {"settlementPx": {"value": "1.0000", "currency": "USD"}}}}
    b = data.MarketData(session=S([R(200, md)])).book("m")
    assert b["settlement_px"] == 1.0 and b["state"] == "MARKET_STATE_EXPIRED"
