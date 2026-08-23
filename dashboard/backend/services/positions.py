from __future__ import annotations

from dashboard.backend.security.safe_paths import resolve_state_file
from dashboard.backend.services.util import read_json_file


def get_positions() -> dict:
    path = resolve_state_file("positions.json")
    data = read_json_file(path, default={})
    if not isinstance(data, dict):
        data = {}

    positions = []
    for ticker, fields in data.items():
        if not isinstance(fields, dict):
            continue
        entry = dict(fields)
        entry["ticker"] = ticker
        entry["is_open"] = entry.get("close_time") is None
        positions.append(entry)

    open_count = sum(1 for p in positions if p["is_open"])
    # A closed position can still carry a leftover position_risk_incomplete=true
    # flag from before it was closed (e.g. controlled_position_close_filled) --
    # that is historical data quality, not current exposure. Only OPEN
    # positions with this flag represent an actual, actionable risk warning.
    open_risk_incomplete = [p["ticker"] for p in positions if p["is_open"] and p.get("position_risk_incomplete")]
    closed_risk_incomplete = [
        p["ticker"] for p in positions if not p["is_open"] and p.get("position_risk_incomplete")
    ]

    return {
        "positions": positions,
        "summary": {
            "total": len(positions),
            "open_count": open_count,
            "open_risk_incomplete_count": len(open_risk_incomplete),
            "open_risk_incomplete_tickers": open_risk_incomplete,
            "closed_risk_incomplete_count": len(closed_risk_incomplete),
            "closed_risk_incomplete_tickers": closed_risk_incomplete,
        },
    }
