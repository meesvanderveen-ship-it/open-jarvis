from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dig(data: dict, dotted_path: str, default: Any = None) -> Any:
    """Fetch a nested value via 'a.b.c', tolerant of missing keys/non-dicts."""
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def read_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default
