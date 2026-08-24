"""Path safety: allowlisted roots only, no traversal, hard-denied secrets.

Every function here resolves a candidate path and verifies the resolved,
real path is still inside one of the explicitly allowed roots. `.env`,
`.git`, `.ssh`, and anything outside the allowed roots is rejected
unconditionally — independent of any caller-supplied input — so a bug in a
router can never turn into a path-traversal read of the bot's secrets.
"""

from __future__ import annotations

from pathlib import Path

from dashboard.backend import config

# Filenames under state/ that are safe to ever expose (read-only, no
# secrets expected). Everything else in state/ (backups, .bak files,
# diagnostic dumps) is invisible to the API even if new files appear there.
ALLOWED_STATE_FILES = {
    "positions.json",
    "open_orders.json",
    "runtime.json",
    "run_trader_loop_cycles.json",
    "decision_outcomes.json",
    "pending_order_intents.json",
    "pending_trade_plans.json",
    "trade_reflections.jsonl",
    "reflection_learning_context.json",
    "cooldowns.json",
    "daily_pnl.json",
    "market_intelligence_context.json",
    "neural_shadow_policy.json",
    "approved_parameter_profile.json",
    "runtime_ticker_universe.json",
}

_DENY_NAME_PARTS = (".env", ".git", ".ssh", "__pycache__")


class UnsafePathError(PermissionError):
    pass


def _deny_if_dangerous(path: Path) -> None:
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith(".env") or lowered in (".git", ".ssh"):
            raise UnsafePathError(f"refused to touch denylisted path component: {part}")


def _ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    _deny_if_dangerous(resolved)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafePathError(f"{resolved} escapes allowed root {resolved_root}") from exc
    return resolved


def resolve_state_file(filename: str) -> Path:
    if filename not in ALLOWED_STATE_FILES:
        raise UnsafePathError(f"{filename} is not on the state-file allowlist")
    return _ensure_within(config.STATE_ROOT / filename, config.STATE_ROOT)


def resolve_under_reports(relative: str) -> Path:
    candidate = (config.REPORTS_ROOT / relative).resolve()
    return _ensure_within(candidate, config.REPORTS_ROOT)


def resolve_under_logs(relative: str) -> Path:
    candidate = (config.LOGS_ROOT / relative).resolve()
    return _ensure_within(candidate, config.LOGS_ROOT)


def file_metadata(path: Path) -> dict:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "exceeds_inline_limit": stat.st_size > config.MAX_INLINE_BYTES,
    }
