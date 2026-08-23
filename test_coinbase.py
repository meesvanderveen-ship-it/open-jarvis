from decimal import Decimal
from dotenv import load_dotenv

from bot.coinbase_client import CoinbaseClient
from coinbase_executor import CoinbaseExecutor

load_dotenv()

if __name__ == "__main__":
    client = CoinbaseClient()

    print("=== Accounts ophalen ===")
    accounts = client.get_accounts()
    print(accounts)

    print("=== Product BTC-USD ophalen ===")
    product = client.get_product("BTC-USD")
    print(product)

    print("=== Best bid/ask ophalen ===")
    bba = client.get_best_bid_ask(["BTC-USD"])
    print(bba)

    # Nog GEEN echte order:
    # executor = CoinbaseExecutor()
    # result = executor.execute_trade("BTC-USD", "BUY", Decimal("10.00"))
    # print(result)
