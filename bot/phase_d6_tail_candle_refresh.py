from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path, normalize_candles
from bot.phase_d6_data_coverage import D6_MAX_CANDLES_PER_REQUEST, TIMEFRAME_SPECS, normalize_timeframes, normalize_tickers, parse_as_of
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_tail_aware_candle_refresh_v1"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"


def safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "live_order_action_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
    }


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_tail_chunk_plan(*, as_of: Any, timeframe: str, max_chunks: int) -> List[Dict[str, Any]]:
    if int(max_chunks) <= 0:
        raise ValueError("max_chunks_must_be_positive")
    timeframe_n = normalize_timeframes([timeframe])[0]
    as_of_dt = parse_as_of(as_of)
    spec = TIMEFRAME_SPECS[timeframe_n]
    chunks: List[Dict[str, Any]] = []
    cursor_end = as_of_dt
    for index in range(int(max_chunks)):
        cursor_start = datetime.fromtimestamp(
            cursor_end.timestamp() - spec.seconds * D6_MAX_CANDLES_PER_REQUEST,
            tz=timezone.utc,
        )
        chunks.append(
            {
                "chunk_index": index,
                "start": _iso(cursor_start),
                "end": _iso(cursor_end),
                "expected_candle_count": D6_MAX_CANDLES_PER_REQUEST,
                "coinbase_limit": D6_MAX_CANDLES_PER_REQUEST,
            }
        )
        cursor_end = cursor_start
    return list(reversed(chunks))


def _candidate_path(*, output_root: str | Path, ticker: str, timeframe: str) -> Path:
    root = assert_research_path(output_root)
    return root / f"product={ticker}" / f"timeframe={timeframe}" / "study_window=3y.json"


def _existing_path(*, ticker: str, timeframe: str) -> Path:
    return Path("research_data/coinbase/candles") / f"product={ticker}" / f"timeframe={timeframe}" / "study_window=3y.json"


def build_tail_refresh_plan(
    *,
    as_of: Any,
    tickers: Iterable[Any],
    timeframes: Iterable[Any],
    max_chunks: int,
    output_root: str | Path,
) -> Dict[str, Any]:
    tickers_n = normalize_tickers(tickers)
    timeframes_n = normalize_timeframes(timeframes)
    entries: List[Dict[str, Any]] = []
    for ticker in tickers_n:
        for timeframe in timeframes_n:
            chunks = build_tail_chunk_plan(as_of=as_of, timeframe=timeframe, max_chunks=max_chunks)
            spec = TIMEFRAME_SPECS[timeframe]
            entries.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "coinbase_granularity": spec.coinbase_granularity,
                    "chunks": chunks,
                    "chunks_requested": len(chunks),
                    "candidate_output_path": str(_candidate_path(output_root=output_root, ticker=ticker, timeframe=timeframe)),
                    "existing_cache_path": str(_existing_path(ticker=ticker, timeframe=timeframe)),
                    "tail_window_start": chunks[0]["start"],
                    "tail_window_end": chunks[-1]["end"],
                    "research_only": True,
                    "no_live_action": True,
                    "state_write_performed": False,
                    "parameter_change_allowed": False,
                    "learning_to_execution_allowed": False,
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "tail_aware_candle_refresh_tool_v1",
        "status": "tail_aware_candle_refresh_plan_ready",
        "required_ack": DATA_FETCH_ACK,
        "as_of": _iso(parse_as_of(as_of)),
        "tickers": tickers_n,
        "timeframes": timeframes_n,
        "max_chunks": int(max_chunks),
        "entry_count": len(entries),
        "planned_public_market_data_calls": sum(int(entry["chunks_requested"]) for entry in entries),
        "output_root": str(assert_research_path(output_root)),
        "fetch_executed": False,
        "dry_run": True,
        "entries": entries,
        **safety_flags(),
    }


def _call_public_candles(client: Any, *, entry: Dict[str, Any], chunk: Dict[str, Any]) -> Dict[str, Any]:
    start = str(int(parse_as_of(chunk["start"]).timestamp()))
    end = str(int(parse_as_of(chunk["end"]).timestamp()))
    return client.get_public_candles(
        product_id=entry["ticker"],
        granularity=entry["coinbase_granularity"],
        start=start,
        end=end,
        limit=int(chunk.get("coinbase_limit") or D6_MAX_CANDLES_PER_REQUEST),
    )


def execute_tail_refresh(
    *,
    plan: Dict[str, Any],
    client: Any,
    fetched_at: datetime | None = None,
) -> Dict[str, Any]:
    if client is None:
        raise ValueError("tail_refresh_requires_read_only_coinbase_client")
    fetched_at_dt = fetched_at or datetime.now(timezone.utc)
    result_entries: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    call_count = 0
    for entry in plan.get("entries") or []:
        candles: List[Dict[str, Any]] = []
        entry_errors: List[Dict[str, Any]] = []
        for chunk in entry.get("chunks") or []:
            try:
                call_count += 1
                raw = _call_public_candles(client, entry=entry, chunk=chunk)
                raw_candles = raw.get("candles", []) if isinstance(raw, dict) else []
                candles.extend(
                    normalize_candles(
                        raw_candles,
                        product_id=entry["ticker"],
                        timeframe=entry["timeframe"],
                        fetched_at=fetched_at_dt,
                    )
                )
            except Exception as exc:  # pragma: no cover - HTTP/client exception type is external.
                err = {
                    "ticker": entry["ticker"],
                    "timeframe": entry["timeframe"],
                    "chunk_index": chunk.get("chunk_index"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                errors.append(err)
                entry_errors.append(err)
        candles = normalize_candles(
            candles,
            product_id=entry["ticker"],
            timeframe=entry["timeframe"],
            fetched_at=fetched_at_dt,
            drop_open_candles=False,
        )
        output_path = assert_research_path(entry["candidate_output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result_entries.append(
            {
                "ticker": entry["ticker"],
                "timeframe": entry["timeframe"],
                "candidate_output_path": str(output_path),
                "existing_cache_path": entry["existing_cache_path"],
                "chunks_requested": len(entry.get("chunks") or []),
                "chunks_fetched": len(entry.get("chunks") or []) - len(entry_errors),
                "candle_count": len(candles),
                "first_candle_start": candles[0]["start"] if candles else None,
                "last_candle_start": candles[-1]["start"] if candles else None,
                "errors": entry_errors,
            }
        )
    return {
        **dict(plan),
        "generated_at": now_iso(),
        "status": "tail_aware_candle_refresh_fetched",
        "fetch_executed": True,
        "dry_run": False,
        "coinbase_public_market_data_call_count": call_count,
        "errors": errors,
        "entries": result_entries,
        **safety_flags(),
    }


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _dedup_sort(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_start: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            by_start[int(row.get("start"))] = dict(row)
        except Exception:
            continue
    return [by_start[start] for start in sorted(by_start)]


def merge_tail_refresh_result(*, fetch_result: Dict[str, Any]) -> Dict[str, Any]:
    merge_rows: List[Dict[str, Any]] = []
    for entry in fetch_result.get("entries") or []:
        candidate_path = entry.get("candidate_output_path")
        existing_path = entry.get("existing_cache_path")
        candidate_rows = _load_rows(candidate_path)
        existing_rows = _load_rows(existing_path)
        merged = _dedup_sort([*existing_rows, *candidate_rows])
        updated = len(merged) > len(existing_rows)
        if updated:
            safe_existing = assert_research_path(existing_path)
            safe_existing.parent.mkdir(parents=True, exist_ok=True)
            safe_existing.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        merge_rows.append(
            {
                "ticker": entry.get("ticker"),
                "timeframe": entry.get("timeframe"),
                "candidate_output_path": candidate_path,
                "existing_cache_path": existing_path,
                "before_count": len(existing_rows),
                "candidate_count": len(candidate_rows),
                "after_count": len(merged),
                "updated": updated,
                "state_write_performed": False,
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "tail_aware_refresh_merge_result_v1",
        "status": "tail_aware_refresh_merge_result_ready",
        "merge_rows": merge_rows,
        "updated_file_count": sum(1 for row in merge_rows if row.get("updated")),
        "state_write_performed": False,
        **safety_flags(),
    }


__all__ = [
    "DATA_FETCH_ACK",
    "PHASE",
    "build_tail_chunk_plan",
    "build_tail_refresh_plan",
    "execute_tail_refresh",
    "merge_tail_refresh_result",
    "safety_flags",
]
