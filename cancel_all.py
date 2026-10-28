"""Cancel every open order (live account) via POST /v1/orders/open/cancel."""
import sys
from broker import Broker, BrokerError, MissingKeys, load_keys_from_env


def main():
    try:
        key_id, secret = load_keys_from_env()
    except MissingKeys as e:
        print(f"cancel_all: {e}")
        return 2
    try:
        resp = Broker(key_id, secret).cancel_all()
    except BrokerError as e:
        print(f"cancel_all FAILED: {e}")
        return 1
    print(f"canceled: {resp.get('canceledOrderIds', [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
