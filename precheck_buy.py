from decimal import Decimal
from dotenv import load_dotenv

from bot.coinbase_client import CoinbaseClient
from risk_firewall import RiskFirewall

load_dotenv()

ticker = "BTC-USDC"
side = "BUY"
requested_amount = Decimal("10.00")

client = CoinbaseClient()
firewall = RiskFirewall()

product_meta = client.get_product(ticker)
print("PRODUCT:", product_meta["product_id"])

bba = client.get_best_bid_ask([ticker])
book = bba["pricebooks"][0]
bid = Decimal(str(book["bids"][0]["price"]))
ask = Decimal(str(book["asks"][0]["price"]))

normalized = firewall.normalize_order_size(
    side=side,
    requested_size=requested_amount,
    product_meta=product_meta,
)

available_balance = client.get_available_balance("USDC")

print("BID:", bid)
print("ASK:", ask)
print("REQUESTED:", requested_amount)
print("NORMALIZED:", normalized)
print("AVAILABLE USDC:", available_balance)

firewall.validate_intent(
    ticker=ticker,
    side=side,
    size=normalized,
    bid=bid,
    ask=ask,
    available_balance=available_balance,
    product_meta=product_meta,
)

print("PRECHECK OK")
