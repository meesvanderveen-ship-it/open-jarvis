from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from bot.atomic_io import atomic_write_json


class CycleBoundaryGuard:
    def __init__(self, path: str | Path = "state/run_trader_loop_cycles.json") -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        import json

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def boundary_key(cycle_type: str, now_utc: datetime) -> str:
        boundary = now_utc.replace(minute=0, second=0, microsecond=0)
        return f"{cycle_type}:{boundary.isoformat()}"

    def should_run(self, cycle_type: str, now_utc: datetime) -> bool:
        key = self.boundary_key(cycle_type, now_utc)
        data = self._load()
        if data.get("last_boundary_key") == key:
            return False
        data["last_boundary_key"] = key
        data["updated_at"] = now_utc.isoformat()
        atomic_write_json(self.path, data)
        return True


__all__ = ["CycleBoundaryGuard"]
