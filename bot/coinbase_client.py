from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from coinbase_auth import generate_coinbase_rest_jwt


def _normalize_product_id_value(product_id: str) -> str:
    product_id = str(product_id or "").upper().strip().replace("/", "-")
    if not product_id or "-" not in product_id:
        raise ValueError("product_id moet in formaat BASE-QUOTE zijn, bv. BTC-USDC")
    return product_id


_MISSING = object()
_ACCOUNT_COLLECTION_FIELDS = ("accounts", "data", "items", "results")
_CURRENCY_FIELDS = ("currency", "code", "symbol", "asset", "asset_id", "name")
_BALANCE_VALUE_FIELDS = ("value", "amount", "balance", "available", "available_balance", "hold")


def _field(value: Any, key: str, default: Any = _MISSING) -> Any:
    """Read a field from a REST dict or an SDK response object without coercion."""
    if isinstance(value, Mapping):
        return value.get(key, default)
    try:
        return getattr(value, key)
    except (AttributeError, TypeError):
        return default


def _is_record(value: Any) -> bool:
    return isinstance(value, Mapping) or any(
        _field(value, key) is not _MISSING
        for key in ("currency", "available_balance", "balance", "hold")
    )


def _normalize_currency(value: Any) -> str:
    if isinstance(value, Mapping) or _is_record(value):
        for key in _CURRENCY_FIELDS:
            nested = _field(value, key)
            if nested is _MISSING or nested is value:
                continue
            normalized = _normalize_currency(nested)
            if normalized:
                return normalized
        return ""
    if value is None:
        return ""
    return str(value).strip().upper()


def _extract_accounts_list(payload: Any, _seen: set[int] | None = None) -> List[Any]:
    """Support REST dicts/lists and Coinbase SDK objects with account attributes."""
    seen = _seen if _seen is not None else set()
    if payload is None:
        return []
    payload_id = id(payload)
    if payload_id in seen:
        return []
    seen.add(payload_id)

    if isinstance(payload, (list, tuple)):
        return [item for item in payload if _is_record(item)]

    for key in _ACCOUNT_COLLECTION_FIELDS:
        candidate = _field(payload, key)
        if candidate is _MISSING or candidate is None or candidate is payload:
            continue
        if isinstance(candidate, (list, tuple)):
            return [item for item in candidate if _is_record(item)]
        nested = _extract_accounts_list(candidate, seen)
        if nested:
            return nested

    return [payload] if _is_record(payload) else []


def _balance_payload(account: Any, *keys: str) -> Any:
    for key in keys:
        value = _field(account, key)
        if value is not _MISSING:
            return value
    return None


def _balance_scalar_with_path(payload: Any, prefix: str) -> tuple[str, bool, str]:
    if payload is None or payload is _MISSING:
        return "", False, ""
    if isinstance(payload, Mapping) or _is_record(payload):
        for key in _BALANCE_VALUE_FIELDS:
            value = _field(payload, key)
            if value is _MISSING or value is payload:
                continue
            text, present, suffix = _balance_scalar_with_path(value, f"{prefix}.{key}")
            if present:
                return text, True, suffix
        return "", False, ""
    text = str(payload).strip()
    return text, bool(text), prefix if text else ""


def _balance_value_with_path(account: Any, *keys: str) -> tuple[str, bool, str]:
    """Return balance text, presence, and the exact supported field path used."""
    for key in keys:
        payload = _field(account, key)
        if payload is _MISSING:
            continue
        value, present, path = _balance_scalar_with_path(payload, key)
        if present:
            return value, True, path
    return "", False, ""


def _balance_value(account: Any, *keys: str) -> tuple[str, bool]:
    value, present, _path = _balance_value_with_path(account, *keys)
    return value, present


def _balance_currency(account: Any, *keys: str) -> str:
    payload = _balance_payload(account, *keys)
    if payload is None:
        return ""
    return _normalize_currency(payload)


def _account_currency(account: Any) -> str:
    for key in ("currency", "asset", "asset_id", "symbol"):
        value = _field(account, key)
        if value is _MISSING:
            continue
        normalized = _normalize_currency(value)
        if normalized:
            return normalized
    for keys in (
        ("available_balance", "available", "available_balance_value", "available_funds"),
        ("balance", "total_balance", "hold", "hold_balance"),
    ):
        normalized = _balance_currency(account, *keys)
        if normalized:
            return normalized
    return ""


def _parse_decimal_exact(value: Any) -> tuple[Optional[Decimal], bool]:
    try:
        if value is None:
            return None, False
        text = str(value).strip()
        if not text:
            return None, False
        parsed = Decimal(text)
        if parsed.is_nan() or parsed.is_infinite():
            return None, False
        return parsed, True
    except (InvalidOperation, ValueError, TypeError):
        return None, False


def _find_account_for_currency(accounts: List[Any], currency: str) -> tuple[Optional[Any], str]:
    expected = _normalize_currency(currency)
    first_observed = ""
    for account in accounts:
        observed = _account_currency(account)
        if observed and not first_observed:
            first_observed = observed
        if observed == expected:
            return account, observed
    return None, first_observed


def _account_for_report(account: Any) -> Dict[str, Any]:
    """Keep execution reports JSON-safe when the underlying client returns SDK objects."""
    if isinstance(account, dict):
        return account
    if account is None:
        return {}
    available, available_present, _available_path = _balance_value_with_path(
        account,
        "available_balance",
        "available",
        "available_balance_value",
        "available_funds",
        "cash_available",
        "balance",
    )
    hold, hold_present, _hold_path = _balance_value_with_path(
        account,
        "hold",
        "hold_balance",
        "hold_balance_value",
        "on_hold",
        "locked",
    )
    return {
        "currency": _account_currency(account),
        "available_balance": {"value": available} if available_present else {},
        "hold": {"value": hold} if hold_present else {},
    }


def normalize_coinbase_account_balances(product_id: str, accounts_payload: Any) -> Dict[str, Any]:
    """Normalize Coinbase account/balance payloads for spot base verification.

    Coinbase Advanced Trade account rows are keyed by account currency, not by
    product. This helper intentionally matches the product base asset against
    the account currency and preserves missing/unparseable balance evidence so
    callers can fail closed instead of silently treating it as zero.
    """
    product = _normalize_product_id_value(product_id)
    base_symbol, quote_symbol = product.split("-", 1)
    accounts = _extract_accounts_list(accounts_payload)
    base_account, base_currency = _find_account_for_currency(accounts, base_symbol)
    quote_account, quote_currency = _find_account_for_currency(accounts, quote_symbol)

    available_base, available_base_present, available_base_path = _balance_value_with_path(
        base_account,
        "available_balance",
        "available",
        "available_balance_value",
        "available_funds",
        "cash_available",
        "balance",
    )
    hold_base, hold_base_present, hold_base_path = _balance_value_with_path(
        base_account,
        "hold",
        "hold_balance",
        "hold_balance_value",
        "on_hold",
        "locked",
    )
    available_quote, available_quote_present, available_quote_path = _balance_value_with_path(
        quote_account,
        "available_balance",
        "available",
        "available_balance_value",
        "available_funds",
        "cash_available",
        "balance",
    )
    hold_quote, hold_quote_present, hold_quote_path = _balance_value_with_path(
        quote_account,
        "hold",
        "hold_balance",
        "hold_balance_value",
        "on_hold",
        "locked",
    )

    _, available_base_parseable = _parse_decimal_exact(available_base)
    _, hold_base_parseable = _parse_decimal_exact(hold_base)
    _, available_quote_parseable = _parse_decimal_exact(available_quote)
    _, hold_quote_parseable = _parse_decimal_exact(hold_quote)

    base_asset_match = bool(base_currency and base_currency == base_symbol)
    quote_asset_match = bool(quote_currency and quote_currency == quote_symbol)
    lookup_empty = bool(not accounts or not base_account or not available_base_present)
    lookup_success = bool(base_asset_match and available_base_present and available_base_parseable)

    return {
        "product_id": product,
        "base_symbol": base_symbol,
        "quote_symbol": quote_symbol,
        "base_asset": base_symbol,
        "quote_asset": quote_symbol,
        "lookup_base_asset": base_currency,
        "lookup_quote_asset": quote_currency,
        "base_asset_match": base_asset_match,
        "quote_asset_match": quote_asset_match,
        "accounts_count": len(accounts),
        "base_account_found": bool(base_account),
        "quote_account_found": bool(quote_account),
        "available_base_balance": available_base if available_base_present else "",
        "hold_base_balance": hold_base if hold_base_present else "",
        "available_quote_balance": available_quote if available_quote_present else "",
        "hold_quote_balance": hold_quote if hold_quote_present else "",
        "available_base_balance_field_path": available_base_path,
        "hold_base_balance_field_path": hold_base_path,
        "available_quote_balance_field_path": available_quote_path,
        "hold_quote_balance_field_path": hold_quote_path,
        "available_base_balance_present": available_base_present,
        "hold_base_balance_present": hold_base_present,
        "available_quote_balance_present": available_quote_present,
        "hold_quote_balance_present": hold_quote_present,
        "available_base_balance_parseable": available_base_parseable,
        "hold_base_balance_parseable": hold_base_parseable,
        "available_quote_balance_parseable": available_quote_parseable,
        "hold_quote_balance_parseable": hold_quote_parseable,
        "base_balance_lookup_success": lookup_success,
        "base_balance_lookup_empty": lookup_empty,
        "base_balance_source": "coinbase_live_account",
        "base_account": _account_for_report(base_account),
        "quote_account": _account_for_report(quote_account),
    }


class CoinbaseClient:
    def __init__(self, host: Optional[str] = None, timeout: Optional[int] = None):
        self.host = (host or os.getenv("COINBASE_API_HOST", "api.coinbase.com")).strip()
        self.base_url = f"https://{self.host}"
        self.timeout = int(timeout or os.getenv("COINBASE_TIMEOUT_SECONDS", "15"))
        self.session = requests.Session()

        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)

    @staticmethod
    def _normalize_product_id(product_id: str) -> str:
        return _normalize_product_id_value(product_id)

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(default)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        auth_required: bool = True,
    ) -> Dict[str, Any]:
        method = method.upper().strip()

        headers = {
            "Accept": "application/json",
        }

        if auth_required:
            token = generate_coinbase_rest_jwt(method, self.host, path)
            headers["Authorization"] = f"Bearer {token}"

        if payload is not None:
            headers["Content-Type"] = "application/json"

        response = None
        try:
            response = self.session.request(
                method=method,
                url=f"{self.base_url}{path}",
                json=payload,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )

            raw_text = response.text or ""
            try:
                raw_data: Dict[str, Any] = response.json() if raw_text else {}
            except ValueError:
                raw_data = {"raw_text": raw_text}

            response.raise_for_status()
            return raw_data

        except requests.HTTPError as e:
            status = response.status_code if response is not None else "unknown"
            body = response.text if response is not None else "<no body>"
            raise RuntimeError(f"Coinbase HTTP error {status}: {body}") from e

        except requests.RequestException as e:
            raise RuntimeError(f"Coinbase request failed: {e}") from e

    def get_accounts(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/brokerage/accounts")

    def get_account(self, account_uuid: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v3/brokerage/accounts/{account_uuid}")

    def get_account_by_currency(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = _normalize_currency(symbol)
        accounts = self.get_accounts()

        for acc in _extract_accounts_list(accounts):
            if _account_currency(acc) == symbol:
                return acc

        return None

    def get_available_balance(self, symbol: str) -> Decimal:
        acc = self.get_account_by_currency(symbol)
        if not acc:
            return Decimal("0")
        value, _present = _balance_value(
            acc,
            "available_balance",
            "available",
            "available_balance_value",
            "available_funds",
            "cash_available",
            "balance",
        )
        return self._to_decimal(value, "0")

    def get_hold_balance(self, symbol: str) -> Decimal:
        acc = self.get_account_by_currency(symbol)
        if not acc:
            return Decimal("0")
        value, _present = _balance_value(acc, "hold", "hold_balance", "hold_balance_value", "on_hold", "locked")
        return self._to_decimal(value, "0")

    def get_spot_position(self, product_id: str) -> Dict[str, Any]:
        """
        Geeft de echte exchange-balances terug voor BASE en QUOTE van een product.
        Dit is de source of truth voor spotpositie-checks.
        """
        product_id = self._normalize_product_id(product_id)
        return normalize_coinbase_account_balances(product_id, self.get_accounts())

    def get_product(self, product_id: str) -> Dict[str, Any]:
        product_id = self._normalize_product_id(product_id)
        return self._request("GET", f"/api/v3/brokerage/products/{product_id}")

    def get_best_bid_ask(self, product_ids: list[str]) -> Dict[str, Any]:
        normalized = [self._normalize_product_id(x) for x in product_ids]
        return self._request(
            "GET",
            "/api/v3/brokerage/best_bid_ask",
            params={"product_ids": normalized},
        )

    def get_public_ticker(self, product_id: str) -> Dict[str, Any]:
        product_id = self._normalize_product_id(product_id)
        return self._request(
            "GET",
            f"/api/v3/brokerage/market/products/{product_id}/ticker",
            auth_required=False,
        )

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

    def get_public_candles(
        self,
        product_id: str,
        granularity: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        product_id = self._normalize_product_id(product_id)
        params: Dict[str, Any] = {"granularity": granularity}

        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if limit is not None:
            params["limit"] = int(limit)

        return self._request(
            "GET",
            f"/api/v3/brokerage/market/products/{product_id}/candles",
            params=params,
            auth_required=False,
        )

    def place_market_order(
        self,
        ticker: str,
        side: str,
        size: Decimal,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_product_id(ticker)
        side = side.upper().strip()

        if side not in {"BUY", "SELL"}:
            raise ValueError("side moet BUY of SELL zijn")

        if size <= Decimal("0"):
            raise ValueError("size moet > 0 zijn")

        client_oid = client_order_id or str(uuid.uuid4())

        if side == "BUY":
            order_cfg = {"quote_size": format(size, "f")}
        else:
            order_cfg = {"base_size": format(size, "f")}

        payload = {
            "client_order_id": client_oid,
            "product_id": ticker,
            "side": side,
            "order_configuration": {
                "market_market_ioc": order_cfg
            },
        }

        return self._request(
            "POST",
            "/api/v3/brokerage/orders",
            payload=payload,
        )

    def place_limit_order(
        self,
        ticker: str,
        side: str,
        base_size: Decimal,
        limit_price: Decimal,
        client_order_id: Optional[str] = None,
        post_only: bool = True,
    ) -> Dict[str, Any]:
        """Place a Coinbase Advanced Trade GTC limit order.

        This method is intentionally not called by the strategy unless later
        Phase-C live-submit gates explicitly allow it. BUY limit orders use
        base_size derived from quote/limit_price by the Phase-C submitter.
        """
        ticker = self._normalize_product_id(ticker)
        side = side.upper().strip()

        if side not in {"BUY", "SELL"}:
            raise ValueError("side moet BUY of SELL zijn")
        if base_size <= Decimal("0"):
            raise ValueError("base_size moet > 0 zijn")
        if limit_price <= Decimal("0"):
            raise ValueError("limit_price moet > 0 zijn")

        client_oid = client_order_id or str(uuid.uuid4())
        payload = {
            "client_order_id": client_oid,
            "product_id": ticker,
            "side": side,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": format(base_size, "f"),
                    "limit_price": format(limit_price, "f"),
                    "post_only": bool(post_only),
                }
            },
        }
        return self._request(
            "POST",
            "/api/v3/brokerage/orders",
            payload=payload,
        )

    def submit_limit_buy_order(
        self,
        *,
        ticker: str,
        quote_size: Optional[Decimal] = None,
        base_size: Optional[Decimal] = None,
        limit_price: Decimal,
        client_order_id: Optional[str] = None,
        post_only: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility wrapper for C4.3 BUY limit entry submits.

        Coinbase Advanced Trade limit GTC orders require base_size in the order
        configuration. The Phase-C submitter remains quote-sized at the policy
        layer, derives/rounds base_size from quote/limit price, then calls this
        wrapper with both values for auditability. Only base_size is sent to
        Coinbase.
        """
        if base_size is None:
            quote = self._to_decimal(quote_size, "0")
            price = self._to_decimal(limit_price, "0")
            base_size = (quote / price) if quote > Decimal("0") and price > Decimal("0") else Decimal("0")
        return self.place_limit_order(
            ticker=ticker,
            side="BUY",
            base_size=base_size,
            limit_price=limit_price,
            client_order_id=client_order_id,
            post_only=post_only,
        )

    def list_orders(
        self,
        product_id: Optional[str] = None,
        order_status: Optional[str] = None,
        limit: Optional[int] = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if product_id:
            params["product_id"] = self._normalize_product_id(product_id)
        if order_status:
            params["order_status"] = order_status
        if limit is not None:
            params["limit"] = int(limit)
        if cursor:
            params["cursor"] = cursor

        return self._request(
            "GET",
            "/api/v3/brokerage/orders/historical/batch",
            params=params,
        )

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v3/brokerage/orders/historical/{order_id}",
        )

    def cancel_orders(self, order_ids: List[str]) -> Dict[str, Any]:
        clean_ids = [str(order_id).strip() for order_id in order_ids if str(order_id).strip()]
        if not clean_ids:
            raise ValueError("order_ids mag niet leeg zijn")
        return self._request(
            "POST",
            "/api/v3/brokerage/orders/batch_cancel",
            payload={"order_ids": clean_ids},
        )

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        clean_id = str(order_id or "").strip()
        if not clean_id:
            raise ValueError("order_id mag niet leeg zijn")
        return self.cancel_orders([clean_id])

    def list_fills(
        self,
        product_id: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: Optional[int] = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if product_id:
            params["product_id"] = self._normalize_product_id(product_id)
        if order_id:
            params["order_id"] = order_id
        if limit is not None:
            params["limit"] = int(limit)
        if cursor:
            params["cursor"] = cursor

        return self._request(
            "GET",
            "/api/v3/brokerage/orders/historical/fills",
            params=params,
        )

    def get_recent_fills_for_order(self, order_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self.list_fills(order_id=order_id, limit=limit)
        return data.get("fills", [])

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        return default

    def summarize_fills_for_order(self, order_id: str) -> Dict[str, Any]:
        fills = self.get_recent_fills_for_order(order_id=order_id)

        total_base = Decimal("0")
        total_quote = Decimal("0")
        total_fees = Decimal("0")
        normalized_fills: List[Dict[str, Any]] = []
        saw_quote_sized_fill = False
        saw_base_sized_fill = False

        for fill in fills:
            raw_size = self._to_decimal(fill.get("size"), "0")
            price = self._to_decimal(fill.get("price"), "0")
            commission = self._to_decimal(fill.get("commission"), "0")
            size_in_quote = self._to_bool(fill.get("size_in_quote"), False)

            # Coinbase Advanced Trade can return fills where `size` is a quote
            # amount for quote-sized BUY orders. For normal base-sized fills,
            # `size` is the base amount. Mixing those up corrupts local state:
            # e.g. a 60 USDC ADA buy at 0.2824 would be stored as 59 ADA
            # instead of about 210 ADA.
            if size_in_quote:
                saw_quote_sized_fill = True
                quote_size = raw_size
                base_size = (quote_size / price) if price > Decimal("0") else Decimal("0")
            else:
                saw_base_sized_fill = True
                base_size = raw_size
                quote_size = base_size * price if price > Decimal("0") else Decimal("0")

            total_base += base_size
            total_quote += quote_size
            total_fees += commission

            enriched_fill = dict(fill)
            enriched_fill["normalized_base_size"] = str(base_size)
            enriched_fill["normalized_quote_value"] = str(quote_size)
            enriched_fill["normalized_price"] = str(price)
            normalized_fills.append(enriched_fill)

        avg_price = (total_quote / total_base) if total_base > 0 else Decimal("0")

        return {
            "order_id": order_id,
            "fill_count": len(fills),
            "filled_size_base": str(total_base),
            "filled_quote_value": str(total_quote),
            "avg_fill_price": str(avg_price),
            "fees": str(total_fees),
            "fills": fills,
            "normalized_fills": normalized_fills,
            "saw_quote_sized_fill": saw_quote_sized_fill,
            "saw_base_sized_fill": saw_base_sized_fill,
        }
