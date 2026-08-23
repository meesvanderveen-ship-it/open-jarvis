from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COINBASE_CLIENT = ROOT / "bot" / "coinbase_client.py"
PROMPTS = ROOT / "bot" / "prompts.py"

ORDERBOOK_METHODS = '''
    @staticmethod
    def _normalize_book_levels(levels: Any) -> List[Dict[str, str]]:
        """
        Normalize Coinbase orderbook levels to [{"price": "...", "size": "..."}].
        Coinbase endpoints normally return dict levels, but this also accepts
        list/tuple levels to keep tests and future endpoint variants safe.
        """
        normalized: List[Dict[str, str]] = []
        if not isinstance(levels, list):
            return normalized

        for level in levels:
            price = "0"
            size = "0"

            if isinstance(level, dict):
                price = str(level.get("price", "0"))
                size = str(level.get("size", "0"))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                price = str(level[0])
                size = str(level[1])

            if price not in {"", "0", "0.0"} and size not in {"", "0", "0.0"}:
                normalized.append({"price": price, "size": size})

        return normalized

    def get_product_book(self, product_id: str, limit: int = 25) -> Dict[str, Any]:
        """
        Fetch a Coinbase orderbook snapshot for one product.

        This method is intentionally defensive because Coinbase exposes both a
        public product-book endpoint and an authenticated product-book endpoint.
        We try the public endpoint first, then the authenticated endpoint, then
        fall back to best_bid_ask so MarketDataService can still receive a real
        top-of-book snapshot instead of all-zero/unknown microstructure fields.
        """
        product_id = self._normalize_product_id(product_id)

        try:
            safe_limit = int(limit)
        except Exception:
            safe_limit = 25
        safe_limit = max(1, min(safe_limit, 100))

        attempts = [
            ("/api/v3/brokerage/market/product_book", False),
            ("/api/v3/brokerage/product_book", True),
            ("/api/v3/brokerage/market/product_book", True),
        ]

        last_error: Optional[BaseException] = None

        for path, auth_required in attempts:
            try:
                data = self._request(
                    "GET",
                    path,
                    params={"product_id": product_id, "limit": safe_limit},
                    auth_required=auth_required,
                )

                pricebook = data.get("pricebook", data) if isinstance(data, dict) else {}
                bids = self._normalize_book_levels(pricebook.get("bids", []))
                asks = self._normalize_book_levels(pricebook.get("asks", []))

                if bids or asks:
                    return {
                        "product_id": str(pricebook.get("product_id", product_id)),
                        "bids": bids,
                        "asks": asks,
                        "time": pricebook.get("time"),
                        "last": data.get("last") if isinstance(data, dict) else None,
                        "mid_market": data.get("mid_market") if isinstance(data, dict) else None,
                        "spread_bps": data.get("spread_bps") if isinstance(data, dict) else None,
                        "spread_absolute": data.get("spread_absolute") if isinstance(data, dict) else None,
                        "source_path": path,
                        "auth_required": auth_required,
                        "depth_is_top_only": False,
                        "limit": safe_limit,
                    }

            except Exception as exc:
                last_error = exc
                continue

        # Last-resort fallback: Coinbase best_bid_ask usually contains one bid
        # and one ask with sizes. This is not full depth, but it is safer than
        # letting the strategy see top sizes/depth as 0 and book_pressure=unknown.
        try:
            data = self.get_best_bid_ask([product_id])
            for pricebook in data.get("pricebooks", []) if isinstance(data, dict) else []:
                if str(pricebook.get("product_id", product_id)).upper() != product_id:
                    continue

                bids = self._normalize_book_levels(pricebook.get("bids", []))
                asks = self._normalize_book_levels(pricebook.get("asks", []))
                if bids or asks:
                    return {
                        "product_id": product_id,
                        "bids": bids,
                        "asks": asks,
                        "time": pricebook.get("time"),
                        "last": None,
                        "mid_market": None,
                        "spread_bps": None,
                        "spread_absolute": None,
                        "source_path": "/api/v3/brokerage/best_bid_ask",
                        "auth_required": True,
                        "depth_is_top_only": True,
                        "limit": 1,
                    }
        except Exception as exc:
            last_error = exc

        raise RuntimeError(f"Coinbase product book unavailable for {product_id}: {last_error}")
'''

OLD_PROMPT_LINE = "- penalize fake breakout risk, low volume, high spread, missing orderbook confirmation, and late entries"
NEW_PROMPT_BLOCK = """- penalize fake breakout risk, low volume, high spread, and late entries
- missing orderbook confirmation is only a minor uncertainty factor; do not reject solely because orderbook data is unavailable if price action, volume, structure, and trigger quality are strong"""


def patch_coinbase_client() -> bool:
    text = COINBASE_CLIENT.read_text()

    if "def get_product_book(" in text:
        print("coinbase_client.py: get_product_book already present; leaving file unchanged")
        return False

    marker = re.search(
        r"(?P<block>    def get_public_ticker\([\s\S]*?\n        \)\n)(?=\n    def get_public_candles\()",
        text,
    )
    if not marker:
        raise RuntimeError("Could not find insertion point after get_public_ticker() in bot/coinbase_client.py")

    updated = text[: marker.end("block")] + ORDERBOOK_METHODS + text[marker.end("block") :]
    COINBASE_CLIENT.write_text(updated)
    print("coinbase_client.py: inserted _normalize_book_levels() and get_product_book()")
    return True


def patch_prompts() -> bool:
    if not PROMPTS.exists():
        print("prompts.py: not found; skipping prompt softening")
        return False

    text = PROMPTS.read_text()
    if "missing orderbook confirmation is only a minor uncertainty factor" in text:
        print("prompts.py: orderbook wording already softened; leaving file unchanged")
        return False

    if OLD_PROMPT_LINE not in text:
        print("prompts.py: exact old orderbook penalty line not found; leaving file unchanged")
        return False

    updated = text.replace(OLD_PROMPT_LINE, NEW_PROMPT_BLOCK, 1)
    PROMPTS.write_text(updated)
    print("prompts.py: softened missing-orderbook wording")
    return True


def main() -> None:
    if not COINBASE_CLIENT.exists():
        raise FileNotFoundError(COINBASE_CLIENT)

    changed_client = patch_coinbase_client()
    changed_prompts = patch_prompts()

    if changed_client or changed_prompts:
        print("Orderbook patch applied. Run py_compile/pytest before restarting the bot.")
    else:
        print("No changes needed; orderbook patch appears to be already applied or prompt line differed.")


if __name__ == "__main__":
    main()
