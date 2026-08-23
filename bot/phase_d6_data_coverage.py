from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


D6_DATA_COVERAGE_PHASE = "D6_data_coverage_inventory_v1"
D6_DATA_SOURCE = "Coinbase candles"
D6_MAX_CANDLES_PER_REQUEST = 350
D6_DEFAULT_TICKERS = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "ADA-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "DOGE-USDC",
    "SUI-USDC",
    "LTC-USDC",
    "HBAR-USDC",
    "ATOM-USDC",
    "NEAR-USDC",
    "APT-USDC",
    "INJ-USDC",
    "ARB-USDC",
    "OP-USDC",
    "UNI-USDC",
]
D6_REQUIRED_TIMEFRAMES = ["1H", "4H", "1D"]
D6_OPTIONAL_TIMEFRAMES = ["15M"]
D6_SUPPORTED_TIMEFRAMES = ["15M", "1H", "4H", "1D"]
D6_DEFAULT_YEARS = [3, 5]


@dataclass(frozen=True)
class TimeframeSpec:
    name: str
    seconds: int
    coinbase_granularity: str
    required: bool


TIMEFRAME_SPECS: Dict[str, TimeframeSpec] = {
    "15M": TimeframeSpec("15M", 15 * 60, "FIFTEEN_MINUTE", False),
    "1H": TimeframeSpec("1H", 60 * 60, "ONE_HOUR", True),
    "4H": TimeframeSpec("4H", 4 * 60 * 60, "FOUR_HOUR", True),
    "1D": TimeframeSpec("1D", 24 * 60 * 60, "ONE_DAY", True),
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper().replace("/", "-")
    if not ticker:
        raise ValueError("ticker_missing")
    if "-" not in ticker:
        raise ValueError(f"invalid_ticker_format:{ticker}")
    return ticker


def normalize_tickers(values: Optional[Iterable[Any]] = None) -> List[str]:
    raw_values = list(values or D6_DEFAULT_TICKERS)
    out: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        ticker = _normalize_ticker(raw)
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


def normalize_timeframe(value: Any) -> str:
    tf = str(value or "").strip().upper()
    aliases = {
        "15": "15M",
        "15M": "15M",
        "15MIN": "15M",
        "15MINUTE": "15M",
        "1H": "1H",
        "1HR": "1H",
        "1HOUR": "1H",
        "4H": "4H",
        "4HR": "4H",
        "4HOUR": "4H",
        "1D": "1D",
        "D": "1D",
        "DAY": "1D",
    }
    normalized = aliases.get(tf)
    if normalized not in TIMEFRAME_SPECS:
        raise ValueError(f"unsupported_timeframe:{value}")
    return normalized


def normalize_timeframes(values: Optional[Iterable[Any]] = None) -> List[str]:
    raw_values = list(values or [*D6_REQUIRED_TIMEFRAMES, *D6_OPTIONAL_TIMEFRAMES])
    out: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        tf = normalize_timeframe(raw)
        if tf in seen:
            continue
        seen.add(tf)
        out.append(tf)
    return out


def normalize_years(values: Optional[Iterable[Any]] = None) -> List[int]:
    raw_values = list(values or D6_DEFAULT_YEARS)
    out: List[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        years = int(str(raw).strip())
        if years <= 0:
            raise ValueError(f"invalid_year_window:{raw}")
        if years in seen:
            continue
        seen.add(years)
        out.append(years)
    return out


def parse_as_of(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise ValueError("as_of_missing")
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def subtract_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year - years)
    except ValueError:
        # Leap-day as-of dates map to Feb 28 in non-leap target years.
        return dt.replace(year=dt.year - years, day=28)


def _candle_count(start: datetime, end: datetime, timeframe: str) -> int:
    seconds = TIMEFRAME_SPECS[timeframe].seconds
    duration_seconds = Decimal(str((end - start).total_seconds()))
    if duration_seconds <= 0:
        return 0
    return int((duration_seconds / Decimal(seconds)).to_integral_value(rounding=ROUND_CEILING))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_chunk_plan(
    *,
    requested_start: datetime,
    requested_end: datetime,
    timeframe: str,
    max_candles_per_request: int = D6_MAX_CANDLES_PER_REQUEST,
) -> List[Dict[str, Any]]:
    if max_candles_per_request <= 0:
        raise ValueError("max_candles_per_request_must_be_positive")
    spec = TIMEFRAME_SPECS[timeframe]
    chunks: List[Dict[str, Any]] = []
    cursor = requested_start
    index = 0
    while cursor < requested_end:
        chunk_seconds = spec.seconds * max_candles_per_request
        chunk_end = min(requested_end, datetime.fromtimestamp(cursor.timestamp() + chunk_seconds, tz=timezone.utc))
        expected = _candle_count(cursor, chunk_end, timeframe)
        chunks.append(
            {
                "chunk_index": index,
                "start": _iso(cursor),
                "end": _iso(chunk_end),
                "expected_candle_count": expected,
                "coinbase_limit": max_candles_per_request,
            }
        )
        cursor = chunk_end
        index += 1
    return chunks


def _cache_path(ticker: str, timeframe: str) -> str:
    return f"research_data/coinbase/candles/product={ticker}/timeframe={timeframe}/"


def _report_path(study_window: str, as_of: datetime) -> str:
    return f"reports/d6/coverage/as_of={as_of.date().isoformat()}/study_window={study_window}/"


def build_coverage_entry(
    *,
    ticker: str,
    timeframe: str,
    years: int,
    as_of: datetime,
    max_candles_per_request: int = D6_MAX_CANDLES_PER_REQUEST,
    coverage_class: str = "planned",
) -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker)
    timeframe_n = normalize_timeframe(timeframe)
    as_of_utc = parse_as_of(as_of)
    start = subtract_years(as_of_utc, years)
    end = as_of_utc
    expected = _candle_count(start, end, timeframe_n)
    chunks = build_chunk_plan(
        requested_start=start,
        requested_end=end,
        timeframe=timeframe_n,
        max_candles_per_request=max_candles_per_request,
    )
    study_window = f"{years}y"
    spec = TIMEFRAME_SPECS[timeframe_n]
    return {
        "ticker": ticker_n,
        "timeframe": timeframe_n,
        "coinbase_granularity": spec.coinbase_granularity,
        "timeframe_required": spec.required,
        "study_window": study_window,
        "window_years": years,
        "requested_start": _iso(start),
        "requested_end": _iso(end),
        "expected_candle_count": expected,
        "planned_chunk_count": len(chunks),
        "max_candles_per_request": max_candles_per_request,
        "chunks": chunks,
        "coverage_class": coverage_class,
        "data_source": D6_DATA_SOURCE,
        "proposed_cache_path": _cache_path(ticker_n, timeframe_n),
        "proposed_report_path": _report_path(study_window, as_of_utc),
        "research_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def build_phase_d6_data_coverage_report(
    *,
    as_of: Any,
    tickers: Optional[Iterable[Any]] = None,
    timeframes: Optional[Iterable[Any]] = None,
    years: Optional[Iterable[Any]] = None,
    max_candles_per_request: int = D6_MAX_CANDLES_PER_REQUEST,
    coverage_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    as_of_dt = parse_as_of(as_of)
    tickers_n = normalize_tickers(tickers)
    timeframes_n = normalize_timeframes(timeframes)
    years_n = normalize_years(years)
    overrides = dict(coverage_overrides or {})
    entries: List[Dict[str, Any]] = []
    for ticker in tickers_n:
        for timeframe in timeframes_n:
            for year_window in years_n:
                key = f"{ticker}|{timeframe}|{year_window}y"
                entries.append(
                    build_coverage_entry(
                        ticker=ticker,
                        timeframe=timeframe,
                        years=year_window,
                        as_of=as_of_dt,
                        max_candles_per_request=max_candles_per_request,
                        coverage_class=overrides.get(key, "planned"),
                    )
                )

    return {
        "generated_at": _iso(datetime.now(timezone.utc)),
        "phase": D6_DATA_COVERAGE_PHASE,
        "status": "d6_data_coverage_inventory_ready",
        "as_of": _iso(as_of_dt),
        "data_source": D6_DATA_SOURCE,
        "tickers": tickers_n,
        "timeframes": timeframes_n,
        "required_timeframes": list(D6_REQUIRED_TIMEFRAMES),
        "optional_timeframes": list(D6_OPTIONAL_TIMEFRAMES),
        "out_of_scope_lower_timeframes": ["5M", "1M"],
        "study_windows": [f"{y}y" for y in years_n],
        "max_candles_per_request": max_candles_per_request,
        "entry_count": len(entries),
        "entries": entries,
        "proposed_cache_root": "research_data/coinbase/candles/",
        "proposed_report_root": "reports/d6/coverage/",
        "research_only": True,
        "no_coinbase_call": True,
        "no_bulk_data_fetch": True,
        "no_live_action": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "safety_policy": {
            "does_not_import_coinbase_client": True,
            "does_not_read_live_trading_state": True,
            "does_not_write_state": True,
            "does_not_change_parameters": True,
            "research_reports_only": True,
        },
    }


def assert_research_output_path(path: str | Path) -> Path:
    output = Path(path)
    parts = {part.lower() for part in output.parts}
    if "state" in parts:
        raise ValueError("d6_output_path_must_not_be_under_state")
    return output


__all__ = [
    "D6_DATA_COVERAGE_PHASE",
    "D6_DEFAULT_TICKERS",
    "D6_REQUIRED_TIMEFRAMES",
    "D6_OPTIONAL_TIMEFRAMES",
    "D6_SUPPORTED_TIMEFRAMES",
    "D6_DEFAULT_YEARS",
    "D6_MAX_CANDLES_PER_REQUEST",
    "build_phase_d6_data_coverage_report",
    "build_coverage_entry",
    "build_chunk_plan",
    "normalize_tickers",
    "normalize_timeframes",
    "normalize_years",
    "parse_as_of",
    "assert_research_output_path",
]
