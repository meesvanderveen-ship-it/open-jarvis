"""Reports & Audits browser.

Report "ids" are just the validated relative path under reports/ — safe
because every read goes through `resolve_under_reports()` first, which
re-resolves and hard-checks containment regardless of what the caller
sends. We deliberately keep `reports/reflection/` shallow (it holds 2GB+ of
snapshots) and cap directory scans so a request can never enumerate
hundreds of thousands of files.
"""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.backend import config
from dashboard.backend.security.safe_paths import UnsafePathError, resolve_under_reports

_INCLUDED_EXTENSIONS = {".json", ".md"}
_MAX_ENTRIES_PER_CATEGORY = 200
_MAX_DEPTH = 2


def _category_for(relative_path: Path) -> str:
    return relative_path.parts[0] if relative_path.parts else "root"


def list_reports(category: str | None = None) -> list[dict]:
    if not config.REPORTS_ROOT.is_dir():
        return []

    entries = []
    for path in config.REPORTS_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _INCLUDED_EXTENSIONS:
            continue
        relative = path.relative_to(config.REPORTS_ROOT)
        if len(relative.parts) > _MAX_DEPTH:
            continue
        cat = _category_for(relative)
        if category and cat != category:
            continue
        stat = path.stat()
        entries.append(
            {
                "id": str(relative),
                "category": cat,
                "name": path.name,
                "extension": path.suffix,
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "is_latest": "latest" in path.stem,
            }
        )

    entries.sort(key=lambda e: e["modified_at"], reverse=True)

    capped: list[dict] = []
    per_category_count: dict[str, int] = {}
    for entry in entries:
        count = per_category_count.get(entry["category"], 0)
        if count >= _MAX_ENTRIES_PER_CATEGORY:
            continue
        per_category_count[entry["category"]] = count + 1
        capped.append(entry)

    return capped


def get_report(report_id: str) -> dict:
    try:
        path = resolve_under_reports(report_id)
    except UnsafePathError as exc:
        raise FileNotFoundError(str(exc)) from exc

    if not path.is_file():
        raise FileNotFoundError(report_id)

    stat = path.stat()
    metadata = {
        "id": report_id,
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }

    if stat.st_size > config.MAX_INLINE_BYTES:
        metadata["truncated"] = True
        metadata["content"] = None
        return metadata

    metadata["truncated"] = False
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            metadata["content"] = json.loads(text)
        except json.JSONDecodeError:
            metadata["content"] = text
    else:
        metadata["content"] = text
    return metadata
