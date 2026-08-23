from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_data_coverage import (
    D6_DATA_SOURCE,
    D6_MAX_CANDLES_PER_REQUEST,
    TIMEFRAME_SPECS,
    build_phase_d6_data_coverage_report,
)


D6_COINBASE_CANDLE_INGEST_PHASE = "D6_coinbase_candle_ingest_v1"
DEFAULT_OUTPUT_ROOT = "research_data/coinbase/candles"
DEFAULT_MANIFEST_ROOT = "reports/d6/coverage"
MAX_FETCH_CALLS_PER_RUN = 25


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _to_decimal_str(value: Any) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "0"
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, TypeError, ValueError):
        return "0"


def assert_research_path(path: str | Path) -> Path:
    output = Path(path)
    raw = str(output)
    parts = {part.lower() for part in output.parts}
    if "state" in parts:
        raise ValueError("d6_ingest_output_path_must_not_be_under_state")
    if ".env" in parts or raw.endswith(".env") or "/.env" in raw:
        raise ValueError("d6_ingest_output_path_must_not_target_env")
    return output


def _entry_output_path(entry: Dict[str, Any], output_root: str | Path) -> Path:
    root = assert_research_path(output_root)
    return (
        root
        / f"product={entry['ticker']}"
        / f"timeframe={entry['timeframe']}"
        / f"study_window={entry['study_window']}.json"
    )


def _manifest_output_path(as_of: str, manifest_output: str | Path | None) -> Optional[Path]:
    if not manifest_output:
        return None
    return assert_research_path(manifest_output)


def normalize_candles(
    raw_candles: Iterable[Dict[str, Any]],
    *,
    product_id: str,
    timeframe: str,
    fetched_at: datetime,
    drop_open_candles: bool = True,
) -> List[Dict[str, Any]]:
    spec = TIMEFRAME_SPECS[timeframe]
    dedup: Dict[int, Dict[str, Any]] = {}
    now_ts = int(fetched_at.timestamp())
    for raw in raw_candles or []:
        try:
            start = int(raw.get("start"))
        except (TypeError, ValueError):
            continue
        if drop_open_candles and start + spec.seconds > now_ts:
            continue
        dedup[start] = {
            "product_id": product_id,
            "timeframe": timeframe,
            "start": start,
            "open": _to_decimal_str(raw.get("open")),
            "high": _to_decimal_str(raw.get("high")),
            "low": _to_decimal_str(raw.get("low")),
            "close": _to_decimal_str(raw.get("close")),
            "volume": _to_decimal_str(raw.get("volume")),
            "source": D6_DATA_SOURCE,
            "fetched_at": _iso(fetched_at),
        }
    return [dedup[start] for start in sorted(dedup)]


def _gap_count(candles: List[Dict[str, Any]], timeframe: str) -> int:
    if len(candles) < 2:
        return 0
    step = TIMEFRAME_SPECS[timeframe].seconds
    gaps = 0
    starts = [int(c["start"]) for c in candles]
    for prev, current in zip(starts, starts[1:]):
        if current - prev > step:
            gaps += 1
    return gaps


def _call_read_only_candles(client: Any, *, entry: Dict[str, Any], chunk: Dict[str, Any]) -> Dict[str, Any]:
    return client.get_public_candles(
        product_id=entry["ticker"],
        granularity=entry["coinbase_granularity"],
        start=str(int(_parse_time(chunk["start"]).timestamp())),
        end=str(int(_parse_time(chunk["end"]).timestamp())),
        limit=int(chunk.get("coinbase_limit") or D6_MAX_CANDLES_PER_REQUEST),
    )


def _entry_manifest(
    *,
    entry: Dict[str, Any],
    output_path: Path,
    chunks_requested: int,
    chunks_fetched: int,
    candles: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "ticker": entry["ticker"],
        "timeframe": entry["timeframe"],
        "study_window": entry["study_window"],
        "requested_start": entry["requested_start"],
        "requested_end": entry["requested_end"],
        "chunks_requested": chunks_requested,
        "chunks_fetched": chunks_fetched,
        "candle_count": len(candles),
        "first_candle_start": candles[0]["start"] if candles else None,
        "last_candle_start": candles[-1]["start"] if candles else None,
        "gap_count": _gap_count(candles, entry["timeframe"]) if candles else 0,
        "errors": errors,
        "output_path": str(output_path),
        "research_only": True,
        "no_live_action": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def build_phase_d6_coinbase_candle_ingest_report(
    *,
    as_of: Any,
    tickers: Optional[Iterable[Any]] = None,
    timeframes: Optional[Iterable[Any]] = None,
    years: Optional[Iterable[Any]] = None,
    max_chunks: Optional[int] = None,
    fetch: bool = False,
    client: Any = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    manifest_output: str | Path | None = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or _now()
    coverage = build_phase_d6_data_coverage_report(
        as_of=as_of,
        tickers=tickers,
        timeframes=timeframes,
        years=years,
    )
    output_root_path = assert_research_path(output_root)
    manifest_path = _manifest_output_path(str(coverage.get("as_of") or ""), manifest_output)
    errors: List[Dict[str, Any]] = []
    blockers: List[str] = []
    entry_manifests: List[Dict[str, Any]] = []
    coinbase_call_count = 0

    if max_chunks is not None and int(max_chunks) <= 0:
        raise ValueError("max_chunks_must_be_positive")
    max_chunks_int = int(max_chunks) if max_chunks is not None else None

    if fetch and max_chunks_int is None:
        blockers.append("fetch_requires_explicit_max_chunks")
    if fetch and client is None:
        blockers.append("fetch_requires_read_only_coinbase_client")

    planned_calls = 0
    for entry in coverage["entries"]:
        chunk_count = len(entry.get("chunks") or [])
        planned_calls += min(chunk_count, max_chunks_int) if max_chunks_int is not None else chunk_count
    if fetch and planned_calls > MAX_FETCH_CALLS_PER_RUN:
        blockers.append("fetch_selection_too_large")

    if fetch and blockers:
        fetch = False

    for entry in coverage["entries"]:
        chunks = list(entry.get("chunks") or [])
        selected_chunks = chunks[:max_chunks_int] if max_chunks_int is not None else chunks
        output_path = _entry_output_path(entry, output_root_path)
        candles: List[Dict[str, Any]] = []
        entry_errors: List[Dict[str, Any]] = []
        chunks_fetched = 0

        if fetch:
            for chunk in selected_chunks:
                try:
                    coinbase_call_count += 1
                    raw = _call_read_only_candles(client, entry=entry, chunk=chunk)
                    raw_candles = raw.get("candles", []) if isinstance(raw, dict) else []
                    candles.extend(
                        normalize_candles(
                            raw_candles,
                            product_id=entry["ticker"],
                            timeframe=entry["timeframe"],
                            fetched_at=now_dt,
                        )
                    )
                    chunks_fetched += 1
                except Exception as exc:  # pragma: no cover - exact exception type comes from HTTP client
                    err = {
                        "chunk_index": chunk.get("chunk_index"),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                    entry_errors.append(err)
                    errors.append({"ticker": entry["ticker"], "timeframe": entry["timeframe"], **err})

            candles = normalize_candles(
                candles,
                product_id=entry["ticker"],
                timeframe=entry["timeframe"],
                fetched_at=now_dt,
                drop_open_candles=False,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        entry_manifests.append(
            _entry_manifest(
                entry=entry,
                output_path=output_path,
                chunks_requested=len(selected_chunks),
                chunks_fetched=chunks_fetched,
                candles=candles,
                errors=entry_errors,
            )
        )

    status = "d6_coinbase_candle_ingest_fetched" if fetch else "d6_coinbase_candle_ingest_dry_run"
    if blockers:
        status = "d6_coinbase_candle_ingest_blocked"

    report = {
        "generated_at": _iso(now_dt),
        "phase": D6_COINBASE_CANDLE_INGEST_PHASE,
        "status": status,
        "coverage_phase": coverage["phase"],
        "as_of": coverage["as_of"],
        "fetch_requested": bool(fetch or blockers),
        "fetch_executed": bool(fetch),
        "dry_run": not bool(fetch),
        "tickers": coverage["tickers"],
        "timeframes": coverage["timeframes"],
        "study_windows": coverage["study_windows"],
        "entry_count": len(entry_manifests),
        "max_chunks": max_chunks_int,
        "max_fetch_calls_per_run": MAX_FETCH_CALLS_PER_RUN,
        "coinbase_call_count": coinbase_call_count,
        "read_only_coinbase_methods_allowed": ["get_public_candles"],
        "chunks_requested": sum(int(m["chunks_requested"]) for m in entry_manifests),
        "chunks_fetched": sum(int(m["chunks_fetched"]) for m in entry_manifests),
        "candle_count": sum(int(m["candle_count"]) for m in entry_manifests),
        "errors": errors,
        "blockers": blockers,
        "output_root": str(output_root_path),
        "manifest_output": str(manifest_path) if manifest_path else "",
        "entries": entry_manifests,
        "research_only": True,
        "no_coinbase_write_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "no_backtest": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "safety_policy": {
            "dry_run_default": True,
            "fetch_requires_explicit_flag": True,
            "fetch_requires_explicit_max_chunks": True,
            "refuses_state_paths": True,
            "refuses_env_paths": True,
            "does_not_change_parameters": True,
            "does_not_touch_live_orders": True,
        },
    }

    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return report


__all__ = [
    "D6_COINBASE_CANDLE_INGEST_PHASE",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_MANIFEST_ROOT",
    "MAX_FETCH_CALLS_PER_RUN",
    "assert_research_path",
    "normalize_candles",
    "build_phase_d6_coinbase_candle_ingest_report",
]
