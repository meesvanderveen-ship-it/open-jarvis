"""Retired legacy market-BUY script.

Mode A accepts entries only through the governed C.4.3 resting-limit boundary.
This file deliberately has no Coinbase client construction, dotenv loading, or
submission path so an accidental invocation cannot place an order.
"""

if __name__ == "__main__":
    raise SystemExit(
        "live_buy_test.py is retired: use the read-only preflight and governed "
        "C.4.3 workflow; direct market BUY is not a supported execution path."
    )
