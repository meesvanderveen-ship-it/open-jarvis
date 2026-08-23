from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.state_store import StateStore


class PositionStore:
    """Small compatibility facade for pipeline tests and contract checks.

    Production position persistence is owned by :class:`bot.state_store.StateStore`.
    This facade keeps the public pipeline name explicit without introducing a
    second state schema.
    """

    def __init__(self, state_store: Optional[StateStore] = None) -> None:
        self.state_store = state_store or StateStore()

    @property
    def positions_file(self) -> Path:
        return self.state_store.positions_file

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        return self.state_store.get_position(ticker)

    def upsert_position(self, ticker: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.state_store.upsert_position(ticker, payload)

    def all_positions(self) -> List[Dict[str, Any]]:
        raw = self.state_store.get_positions()
        return [dict(value) for value in raw.values() if isinstance(value, dict)]

    def open_positions(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for position in self.all_positions():
            status = str(position.get("status") or "open").strip().lower()
            if status in {"open", "active"}:
                out.append(position)
        return out


__all__ = ["PositionStore"]
