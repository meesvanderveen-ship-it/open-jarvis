"""Logs & Evidence Viewer: tails logs/*.jsonl without ever loading a whole
file into memory — several of these logs are 100MB+. Reads backward from
EOF in chunks (like `tail`), stopping once enough matching lines are found
or a hard scan cap is hit.
"""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.backend import config
from dashboard.backend.security.safe_paths import resolve_under_logs

_CHUNK_SIZE = 65536
_MAX_RAW_LINES_SCANNED = 20_000
# Hard cap on bytes read backward, independent of line count — some logs
# (e.g. analysis.jsonl) have very long lines, so a line-count cap alone
# would still force a full multi-hundred-MB read.
_MAX_BYTES_SCANNED = 8 * 1024 * 1024


def list_available_logs() -> list[dict]:
    if not config.LOGS_ROOT.is_dir():
        return []
    entries = []
    for path in sorted(config.LOGS_ROOT.glob("*.jsonl")):
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append({"name": path.name, "size_bytes": stat.st_size, "modified_at": stat.st_mtime})
    return entries


def _read_lines_from_end(path: Path, max_lines: int) -> tuple[list[str], bool]:
    """Read up to `max_lines` lines from the end of `path`, oldest first.

    Bounded by both line count and total bytes read, so a file with very
    long lines (or no newlines at all) can never trigger a full-file read.
    Returns (lines, stopped_early) — stopped_early is True if the start of
    the file was not reached (i.e. older entries exist but were not read).
    """
    lines: list[str] = []
    bytes_read = 0
    with path.open("rb") as fh:
        fh.seek(0, 2)
        file_size = fh.tell()
        position = file_size
        buffer = b""
        while position > 0 and len(lines) <= max_lines and bytes_read < _MAX_BYTES_SCANNED:
            read_size = min(_CHUNK_SIZE, position)
            position -= read_size
            fh.seek(position)
            buffer = fh.read(read_size) + buffer
            bytes_read += read_size
            lines = buffer.split(b"\n")
        decoded = [ln.decode("utf-8", errors="replace") for ln in lines if ln.strip()]
    return decoded[-max_lines:], position > 0


def tail_log(
    filename: str,
    *,
    limit: int = 100,
    ticker: str | None = None,
    q: str | None = None,
) -> dict:
    path = resolve_under_logs(filename)
    if not path.is_file():
        return {"entries": [], "total_scanned": 0, "truncated": False}

    raw_lines, stopped_early = _read_lines_from_end(path, _MAX_RAW_LINES_SCANNED)
    entries = []
    for line in reversed(raw_lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = {"raw": line}

        if ticker and record.get("ticker") != ticker:
            continue
        if q and q.lower() not in line.lower():
            continue

        entries.append(record)
        if len(entries) >= limit:
            break

    return {
        "entries": entries,
        "total_scanned": len(raw_lines),
        "truncated": stopped_early,
    }
