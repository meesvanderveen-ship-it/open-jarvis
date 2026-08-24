"""Which tickers the running bot actually follows right now.

The dashboard backend never imports bot.config or reads .env (see
dashboard/backend/config.py) -- state/runtime_ticker_universe.json is the one
safe, no-secrets channel run_trader_loop.py uses to publish its current
ALLOWED_TICKERS/PHASE_C_ALLOWED_TICKERS to it. Used to filter stale tickers
(e.g. left over from a previously larger ticker list) out of current-state
views like positions, opportunities and the trade thesis.
"""

from __future__ import annotations

from dashboard.backend.security.safe_paths import resolve_state_file
from dashboard.backend.services.util import read_json_file


def get_allowed_tickers() -> list[str]:
    """Return the current ticker universe, or [] if unknown (e.g. bot never ran).

    Callers must treat [] as "no filter" (fail open) -- an empty/missing
    state file must never make every ticker silently disappear.
    """
    path = resolve_state_file("runtime_ticker_universe.json")
    data = read_json_file(path, default={})
    if not isinstance(data, dict):
        return []
    universe = data.get("configured_ticker_universe") or data.get("allowed_tickers") or []
    if not isinstance(universe, list):
        return []
    return [str(t).strip().upper() for t in universe if str(t or "").strip()]


def filter_to_allowed_tickers(items: list[dict], *, ticker_key: str = "ticker") -> list[dict]:
    """Filter a list of ticker-keyed dicts to the current universe.

    Fails open: if the universe is unknown (empty), returns items unchanged
    rather than hiding everything.
    """
    allowed = get_allowed_tickers()
    if not allowed:
        return items
    allowed_set = set(allowed)
    return [item for item in items if str(item.get(ticker_key) or "").strip().upper() in allowed_set]
