"""Retired generic execution façade.

The production workflow owns execution in C.4.3 (BUY resting limit) and D3
(SELL reduce-only limit).  This compatibility class intentionally cannot
submit a generic market order, so stale callers fail before touching Coinbase.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class LegacyExecutionRouteBlockedError(RuntimeError):
    """The caller attempted to use a retired, non-canonical boundary."""


class CoinbaseExecutor:
    """Compatibility façade retained only to make stale call sites fail closed."""

    def __init__(
        self,
        client: Optional[Any] = None,
        firewall: Optional[Any] = None,
        cfg: Any = None,
    ) -> None:
        self.client = client
        self.firewall = firewall
        self.cfg = cfg

    @staticmethod
    def _blocked_message(*, side: str) -> str:
        boundary = "C.4.3 BUY resting-limit" if side == "BUY" else "D3 reduce-only SELL"
        return f"generic CoinbaseExecutor execution is retired; use the governed {boundary} boundary"

    def execute_trade(self, ticker: str, side: str, requested_amount: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise LegacyExecutionRouteBlockedError(self._blocked_message(side=str(side or "").upper().strip()))

    def execute_close_spot_position(self, ticker: str, requested_base_size: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise LegacyExecutionRouteBlockedError(self._blocked_message(side="SELL"))

    def preview_close_spot_position(self, ticker: str, requested_base_size: Any) -> Dict[str, Any]:
        """Return a no-I/O retirement diagnostic for stale preview callers."""
        return {
            "ticker": str(ticker or "").upper().strip(),
            "requested_base_size": str(requested_base_size),
            "executable": False,
            "blocker": "generic_market_close_route_retired",
        }


__all__ = ["CoinbaseExecutor", "LegacyExecutionRouteBlockedError"]
