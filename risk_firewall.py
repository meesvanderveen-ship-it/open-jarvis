import os
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Any, Iterable


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class RiskFirewall:
    def __init__(
        self,
        max_notional_usd: Decimal | None = None,
        max_spread_pct: Decimal | None = None,
        allowed_tickers: Iterable[str] | None = None,
    ):
        self.max_notional_usd = max_notional_usd or Decimal(
            os.getenv("MAX_NOTIONAL_USD", "50.00")
        )
        self.max_spread_pct = max_spread_pct or Decimal(
            os.getenv("MAX_SPREAD_PCT", "0.0100")
        )
        env_tickers = os.getenv(
            "ALLOWED_TICKERS",
            "BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,ADA-USDC,LINK-USDC,AVAX-USDC,DOGE-USDC,SUI-USDC,LTC-USDC,HBAR-USDC,ATOM-USDC,NEAR-USDC,APT-USDC,INJ-USDC,ARB-USDC,OP-USDC,UNI-USDC",
        )
        self.allowed_tickers = set(
            x.upper().strip()
            for x in (allowed_tickers or env_tickers.split(","))
            if x and x.strip()
        )

    @staticmethod
    def _normalize_side(side: str) -> str:
        side = side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Risk Block: side moet BUY of SELL zijn")
        return side

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        ticker = ticker.upper().strip()
        if not ticker or "-" not in ticker:
            raise ValueError("Risk Block: ticker moet formaat BASE-QUOTE hebben")
        return ticker

    @staticmethod
    def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
        if increment <= Decimal("0"):
            return value
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment

    def _extract_market_state(
        self,
        bid: Decimal,
        ask: Decimal,
    ) -> dict:
        if ask <= Decimal("0") or bid <= Decimal("0") or bid > ask:
            raise ValueError("Risk Block: ongeldige marktdata")

        spread_abs = ask - bid
        spread_pct = (spread_abs / ask) if ask > Decimal("0") else Decimal("0")

        return {
            "bid": bid,
            "ask": ask,
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
        }

    def _extract_product_state(self, product_meta: dict) -> dict:
        is_disabled = bool(product_meta.get("is_disabled", False))
        trading_disabled = bool(product_meta.get("trading_disabled", False))
        cancel_only = bool(product_meta.get("cancel_only", False))
        status = str(product_meta.get("status", "")).lower().strip()

        return {
            "is_disabled": is_disabled,
            "trading_disabled": trading_disabled,
            "cancel_only": cancel_only,
            "status": status,
            "quote_increment": _to_decimal(product_meta.get("quote_increment"), "0.01"),
            "base_increment": _to_decimal(product_meta.get("base_increment"), "0.00000001"),
            "quote_min_size": _to_decimal(product_meta.get("quote_min_size"), "1.00"),
            "base_min_size": _to_decimal(product_meta.get("base_min_size"), "0"),
        }

    def get_effective_min_size(self, side: str, product_meta: dict) -> Decimal:
        side = self._normalize_side(side)
        product_state = self._extract_product_state(product_meta)
        if side == "BUY":
            return max(product_state["quote_increment"], product_state["quote_min_size"])
        return max(product_state["base_increment"], product_state["base_min_size"])

    def preview_order_size(
        self,
        side: str,
        requested_size: Decimal,
        product_meta: dict,
        available_balance: Decimal | None = None,
    ) -> dict:
        side = self._normalize_side(side)
        product_state = self._extract_product_state(product_meta)
        increment = product_state["quote_increment"] if side == "BUY" else product_state["base_increment"]
        min_size = product_state["quote_min_size"] if side == "BUY" else product_state["base_min_size"]
        effective_min_size = self.get_effective_min_size(side, product_meta)

        executable = True
        reasons: list[str] = []
        requested = _to_decimal(requested_size, "0")
        normalized = Decimal("0")

        if requested <= Decimal("0"):
            executable = False
            reasons.append("requested_size_non_positive")
        else:
            normalized = self._quantize_down(requested, increment)
            if normalized <= Decimal("0"):
                executable = False
                reasons.append("rounded_to_zero_by_increment")
            elif normalized < min_size:
                executable = False
                reasons.append("below_min_size")

        balance_clamped = normalized
        if available_balance is not None:
            available_balance = _to_decimal(available_balance, "0")
            if balance_clamped > available_balance:
                balance_clamped = self._quantize_down(available_balance, increment)
                reasons.append("clamped_to_available_balance")
                if balance_clamped <= Decimal("0"):
                    executable = False
                    if "rounded_to_zero_by_increment" not in reasons:
                        reasons.append("rounded_to_zero_by_increment")
                elif balance_clamped < min_size:
                    executable = False
                    if "below_min_size" not in reasons:
                        reasons.append("below_min_size")

        return {
            "side": side,
            "requested_size": requested,
            "normalized_size": normalized,
            "balance_clamped_size": balance_clamped,
            "increment": increment,
            "min_size": min_size,
            "effective_min_size": effective_min_size,
            "available_balance": available_balance,
            "executable": executable,
            "reasons": reasons,
        }

    def normalize_order_size(
        self,
        side: str,
        requested_size: Decimal,
        product_meta: dict,
    ) -> Decimal:
        preview = self.preview_order_size(
            side=side,
            requested_size=requested_size,
            product_meta=product_meta,
            available_balance=None,
        )
        if preview["normalized_size"] <= Decimal("0"):
            label = "SELL" if str(side).upper().strip() == "SELL" else "BUY"
            raise ValueError(
                f"Risk Block: {label} size rounded_to_zero_by_increment requested={requested_size} increment={preview['increment']}"
            )
        return preview["normalized_size"]

    def validate_intent(
        self,
        ticker: str,
        side: str,
        size: Decimal,
        bid: Decimal,
        ask: Decimal,
        available_balance: Decimal,
        product_meta: dict,
    ) -> bool:
        ticker = self._normalize_ticker(ticker)
        side = self._normalize_side(side)

        if size <= Decimal("0"):
            raise ValueError("Risk Block: size moet > 0 zijn")

        market_state = self._extract_market_state(bid=bid, ask=ask)
        product_state = self._extract_product_state(product_meta)

        # Bewust NIET meer hard blokkeren op allowlist.
        # De scan-universe zit hoger in de botflow; execution moet vooral technische
        # uitvoerbaarheid bewaken.
        _ = self.allowed_tickers
        _ = self.max_spread_pct
        _ = self.max_notional_usd
        _ = ticker
        _ = market_state["spread_pct"]

        if product_state["is_disabled"] is True:
            raise ValueError("Risk Block: product is disabled")
        if product_state["trading_disabled"] is True:
            raise ValueError("Risk Block: trading_disabled=true")
        if product_state["cancel_only"] is True:
            raise ValueError("Risk Block: cancel_only=true")

        status = product_state["status"]
        if status and status not in {"online", "online_internal_only"}:
            raise ValueError(f"Risk Block: status={product_meta['status']}")

        current_price = ask if side == "BUY" else bid
        notional_in_quote = size if side == "BUY" else size * current_price

        # Bewust gn harde spread-block en gn harde max_notional-block meer.
        # Deze horen nu thuis in strategy/judge/sizing-context in plaats van
        # in de technische execution-firewall.
        _ = notional_in_quote

        if side == "BUY":
            quote_min_size = product_state["quote_min_size"]
            if size < quote_min_size:
                raise ValueError(
                    f"Risk Block: BUY quote_size {size} onder quote_min_size {quote_min_size}"
                )
            if size > available_balance:
                raise ValueError(
                    f"Risk Block: onvoldoende quote balance. Nodig {size}, beschikbaar {available_balance}"
                )
        else:
            base_min_size = product_state["base_min_size"]
            if size < base_min_size:
                raise ValueError(
                    f"Risk Block: SELL base_size {size} onder base_min_size {base_min_size}"
                )
            if size > available_balance:
                raise ValueError(
                    f"Risk Block: onvoldoende base asset. Nodig {size}, beschikbaar {available_balance}"
                )

        return True