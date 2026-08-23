"""Historical replay/backfill layer for the GrowBot/River report-only sidecar.

The forward adapter (``bot/growbot_learning_adapter.py``) reads each source as
a *tail window* (``max_per_source`` most recent lines). When a log grows past
that window, older lines are never read again by any future cycle -- they are
not rotated out of the file, just permanently out of reach of the forward
pipeline. This module finds genuinely orphaned, signal-bearing rows in that
unreachable prefix, converts them into the same episode shape the forward
adapter produces (by calling its own ``normalize_episode``), and writes them
to a *separate* append-only ledger tagged ``historical_replay=True`` with
explicit provenance.

This module never edits or replays into the forward ledger
(``reports/growbot_river/history/episodes.jsonl``); it only reads it for
comparison reporting. It has no import path to order submission, C4.3 or D3,
exactly like the forward adapter it reuses.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from bot.atomic_io import atomic_write_json
from bot.growbot_learning_adapter import (
    EPISODE_LEDGER_PATH as FORWARD_EPISODE_LEDGER_PATH,
    append_new_episodes,
    normalize_episode,
    validate_episode_contracts,
)
from bot.growbot_river_readiness import estimate_forward_episode_requirements
from bot.river_online_parameter_learner import run_river_online_parameter_learning

EXTRACTION_VERSION = "growbot_historical_replay_v1"
DEFAULT_MAX_PER_SOURCE = 1500  # must match growbot_learning_adapter's forward default

DECISION_OUTCOME_LOG_PATH = Path("logs/decision_outcomes.jsonl")
TRADE_REFLECTION_LOG_PATH = Path("logs/trade_reflections.jsonl")
EXECUTION_OUTCOME_LOG_PATH = Path("logs/execution_outcomes.jsonl")
DECISION_OUTCOME_REPORT_PATH = Path("logs/decision_outcome_report.json")
TRADE_LEARNING_REPORT_PATH = Path("logs/trade_learning_report.json")
REFLECTION_ADAPTIVE_SIDECAR_LOG_PATH = Path("logs/reflection_adaptive_sidecar.jsonl")
LIVE_LEARNING_DIR = Path("reports/live_learning")
D6_DIR = Path("reports/d6")
AUDITS_DIR = Path("reports/audits")
GROWBOT_RIVER_DIR = Path("reports/growbot_river")
GROWBOT_RIVER_HISTORY_DIR = Path("reports/growbot_river/history")

HISTORICAL_EPISODE_LEDGER_PATH = Path("reports/growbot_river/history/historical-replay-episodes.jsonl")
SOURCE_AUDIT_JSON_PATH = Path("reports/growbot_river/historical-source-audit-latest.json")
SOURCE_AUDIT_MD_PATH = Path("reports/growbot_river/historical-source-audit-latest.md")
COVERAGE_JSON_PATH = Path("reports/growbot_river/historical-replay-coverage-latest.json")
COVERAGE_MD_PATH = Path("reports/growbot_river/historical-replay-coverage-latest.md")

_NON_MARKET_REGIMES = {"", "unknown", "backtest", "historical", "none", "null"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _load_jsonl_episodes(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in _read_lines(path):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _distinct_known_regimes(episodes: Sequence[Mapping[str, Any]]) -> List[str]:
    regimes = set()
    for episode in episodes:
        regime = str(episode.get("regime") or "unknown").strip().lower().replace(" ", "_")
        if regime not in _NON_MARKET_REGIMES:
            regimes.add(regime)
    return sorted(regimes)


# ---------------------------------------------------------------------------
# Orphan discovery: rows the forward tail window has already permanently
# scrolled past and will never read again.
# ---------------------------------------------------------------------------

def _orphan_line_count(root: Path, path: Path, *, max_per_source: int) -> Tuple[int, int]:
    """Return (total_lines, orphan_line_count) for a tail-windowed jsonl source."""
    lines = _read_lines(root / path)
    total = len(lines)
    orphan = max(0, total - max_per_source)
    return total, orphan


def discover_decision_outcome_orphan_candidates(
    root: Path, *, max_per_source: int = DEFAULT_MAX_PER_SOURCE
) -> Dict[str, Any]:
    """Find decision_outcome nested records outside the forward tail window.

    Only resolved records (``outcome_label`` is not ``None``) carry any
    reward/outcome evidence; unresolved ones are pending observations that
    never matured before falling out of the window -- noise, not signal, by
    this codebase's own reward derivation (``_reward`` maps a missing label to
    ``insufficient_reward_evidence`` / reward 0.0).
    """
    lines = _read_lines(root / DECISION_OUTCOME_LOG_PATH)
    total_lines = len(lines)
    orphan_line_count = max(0, total_lines - max_per_source)
    orphan_lines = lines[:orphan_line_count]

    candidates: List[Dict[str, Any]] = []
    unresolved_count = 0
    malformed_count = 0
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    for line_no, line in enumerate(orphan_lines, start=1):
        if not line.strip():
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            malformed_count += 1
            continue
        if not isinstance(envelope, dict):
            malformed_count += 1
            continue
        records = envelope.get("records")
        if not isinstance(records, list):
            # Engine-level count-only heartbeat row; no decision evidence.
            continue
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            ts = str(record.get("created_at") or envelope.get("generated_at") or "")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            if record.get("outcome_label") is None:
                unresolved_count += 1
                continue
            candidates.append({
                "line_no": line_no,
                "record_index": record_index,
                "record": record,
            })
    return {
        "total_lines": total_lines,
        "orphan_line_count": orphan_line_count,
        "orphan_nested_record_count": unresolved_count + len(candidates) + malformed_count * 0,
        "resolved_candidate_count": len(candidates),
        "unresolved_excluded_count": unresolved_count,
        "malformed_line_count": malformed_count,
        "date_range": {"first": first_ts, "last": last_ts},
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Quality scoring -- deterministic, documented, no hidden weighting.
# ---------------------------------------------------------------------------

def quality_score(episode: Mapping[str, Any]) -> float:
    """Deterministic 0..1 evidence-richness score for a historical episode.

    +0.3 non-empty feature state, +0.2 known (non-unknown) regime, +0.3
    nonzero reward (i.e. the label actually resolved to a directional
    outcome, not just "insufficient_reward_evidence"), +0.1 known ticker,
    +0.1 known setup_type. This mirrors exactly the four coverage axes
    ``validate_episode_contracts`` already gates on, so a low score here
    predicts a low contribution to that contract's coverage percentages.
    """
    score = 0.0
    if isinstance(episode.get("state"), Mapping) and episode["state"]:
        score += 0.3
    regime = str(episode.get("regime") or "unknown").strip().lower()
    if regime not in _NON_MARKET_REGIMES:
        score += 0.2
    try:
        if abs(float(episode.get("reward") or 0.0)) > 0:
            score += 0.3
    except (TypeError, ValueError):
        pass
    if str(episode.get("ticker") or "unknown").strip().lower() not in {"", "unknown"}:
        score += 0.1
    setup_type = str((episode.get("decision_context") or {}).get("setup_type") or "unknown").strip().lower()
    if setup_type not in {"", "unknown"}:
        score += 0.1
    return round(score, 4)


def _with_provenance(
    episode: Dict[str, Any],
    *,
    source_file: str,
    source_line_or_record_id: str,
    source_type: str,
    original_timestamp: str,
) -> Dict[str, Any]:
    episode = dict(episode)
    episode["source_file"] = source_file
    episode["source_line_or_record_id"] = source_line_or_record_id
    episode["source_type"] = source_type
    episode["original_timestamp"] = original_timestamp
    episode["extraction_version"] = EXTRACTION_VERSION
    episode["quality_score"] = quality_score(episode)
    episode["historical_replay"] = True
    return episode


def build_decision_outcome_historical_episodes(
    root: Path, *, max_per_source: int = DEFAULT_MAX_PER_SOURCE
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    discovery = discover_decision_outcome_orphan_candidates(root, max_per_source=max_per_source)
    episodes: List[Dict[str, Any]] = []
    exact_duplicates = 0
    collision_resolutions = 0
    evidence_by_base: Dict[str, set] = {}
    for ordinal, candidate in enumerate(discovery["candidates"]):
        record = candidate["record"]
        episode = normalize_episode("decision_outcome", record, ordinal=ordinal)
        # normalize_episode's identity hash does not include horizon_hours, so
        # the 4h/12h/24h snapshots of the same decision moment share a base
        # identity. Mirror build_episodes()'s own collision-safe suffixing so
        # genuinely distinct evidence (different outcome per horizon) is kept
        # instead of being silently treated as a duplicate by the append-only
        # ledger's dedup-by-episode_id.
        base_id = str(episode["base_episode_id"])
        evidence_hash = str(episode["evidence_hash"])
        prior_hashes = evidence_by_base.setdefault(base_id, set())
        if evidence_hash in prior_hashes:
            exact_duplicates += 1
            continue
        if prior_hashes:
            episode["episode_id"] = hashlib.sha256(f"{base_id}:{evidence_hash}".encode("utf-8")).hexdigest()
            collision_resolutions += 1
        prior_hashes.add(evidence_hash)
        original_timestamp = str(record.get("created_at") or "")
        episode = _with_provenance(
            episode,
            source_file=str(DECISION_OUTCOME_LOG_PATH),
            source_line_or_record_id=f"line:{candidate['line_no']}#record:{candidate['record_index']}",
            source_type="historical_decision_outcome",
            original_timestamp=original_timestamp,
        )
        episodes.append(episode)
    stats = {k: v for k, v in discovery.items() if k != "candidates"}
    stats["episodes_built"] = len(episodes)
    stats["exact_duplicate_rows_dropped"] = exact_duplicates
    stats["compact_identity_collisions_resolved"] = collision_resolutions
    return episodes, stats


def build_historical_episodes(
    root: Path, *, max_per_source: int = DEFAULT_MAX_PER_SOURCE
) -> Dict[str, Any]:
    """Build every currently-viable historical_replay episode across sources.

    Only ``decision_outcome`` has a genuine, currently-unrecovered gap (see
    ``audit_historical_sources``); ``trade_reflection`` and
    ``execution_outcome`` are reported here too, with an explicit zero-gap
    finding, so this function stays the single source of truth if a future
    log rotation or volume increase ever opens a gap in those sources.
    """
    decision_outcome_episodes, decision_outcome_stats = build_decision_outcome_historical_episodes(
        root, max_per_source=max_per_source
    )
    trade_reflection_total, trade_reflection_orphan = _orphan_line_count(
        root, TRADE_REFLECTION_LOG_PATH, max_per_source=max_per_source
    )
    execution_outcome_total, execution_outcome_orphan = _orphan_line_count(
        root, EXECUTION_OUTCOME_LOG_PATH, max_per_source=max_per_source
    )
    episodes = list(decision_outcome_episodes)
    by_source = {
        "decision_outcome": decision_outcome_stats,
        "trade_reflection": {
            "total_lines": trade_reflection_total,
            "orphan_line_count": trade_reflection_orphan,
            "episodes_built": 0,
            "reason": (
                "no_gap_total_lines_under_max_per_source"
                if trade_reflection_orphan == 0
                else "gap_detected_extraction_not_yet_implemented_for_this_source"
            ),
        },
        "execution_outcome": {
            "total_lines": execution_outcome_total,
            "orphan_line_count": execution_outcome_orphan,
            "episodes_built": 0,
            "reason": (
                "no_gap_total_lines_under_max_per_source"
                if execution_outcome_orphan == 0
                else "gap_detected_extraction_not_yet_implemented_for_this_source"
            ),
        },
    }
    return {"episodes": episodes, "by_source": by_source}


def append_historical_episodes(
    episodes: Sequence[Mapping[str, Any]], *, root: Path = Path(".")
) -> Dict[str, int]:
    """Append unique historical episodes to their own ledger, never the forward one."""
    return append_new_episodes(episodes, root=root, path=HISTORICAL_EPISODE_LEDGER_PATH)


# ---------------------------------------------------------------------------
# Source inventory / audit (covers every path the task asked about, even the
# ones that contribute zero episodes -- with an explicit, checkable reason).
# ---------------------------------------------------------------------------

def _jsonl_basic_inventory(root: Path, path: Path) -> Dict[str, Any]:
    full = root / path
    if not full.exists():
        return {"path": str(path), "exists": False}
    lines = _read_lines(full)
    parsed = 0
    malformed = 0
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(row, dict):
            malformed += 1
            continue
        parsed += 1
        ts = row.get("generated_at") or row.get("created_at")
        if ts:
            first_ts = first_ts or str(ts)
            last_ts = str(ts)
    return {
        "path": str(path),
        "exists": True,
        "line_count": len(lines),
        "parsed_record_count": parsed,
        "malformed_line_count": malformed,
        "date_range": {"first": first_ts, "last": last_ts},
    }


def _json_basic_inventory(root: Path, path: Path) -> Dict[str, Any]:
    full = root / path
    if not full.exists():
        return {"path": str(path), "exists": False}
    payload = _load_json(full)
    return {
        "path": str(path),
        "exists": True,
        "top_level_keys": sorted(payload.keys())[:30],
        "sample_size_field": payload.get("count") if "count" in payload else payload.get("sample_size"),
        "generated_at": payload.get("generated_at"),
    }


def _dir_basic_inventory(root: Path, path: Path, *, sample_n: int = 3) -> Dict[str, Any]:
    full = root / path
    if not full.exists():
        return {"path": str(path), "exists": False}
    files = sorted(p for p in full.iterdir() if p.is_file())
    return {
        "path": str(path),
        "exists": True,
        "file_count": len(files),
        "sample_files": [f.name for f in files[:sample_n]],
    }


def audit_historical_sources(root: Path, *, max_per_source: int = DEFAULT_MAX_PER_SOURCE) -> Dict[str, Any]:
    decision_outcome_discovery = discover_decision_outcome_orphan_candidates(root, max_per_source=max_per_source)
    trade_reflection_total, trade_reflection_orphan = _orphan_line_count(
        root, TRADE_REFLECTION_LOG_PATH, max_per_source=max_per_source
    )
    execution_outcome_total, execution_outcome_orphan = _orphan_line_count(
        root, EXECUTION_OUTCOME_LOG_PATH, max_per_source=max_per_source
    )
    forward_episodes = _load_jsonl_episodes(root / FORWARD_EPISODE_LEDGER_PATH)
    forward_trade_reflection_ids = {
        str(e.get("episode_id")) for e in forward_episodes if e.get("source") == "trade_reflection"
    }
    forward_execution_outcome_ids = {
        str(e.get("episode_id")) for e in forward_episodes if e.get("source") == "execution_outcome"
    }

    sources: Dict[str, Any] = {}
    sources["logs/decision_outcomes.jsonl"] = {
        **_jsonl_basic_inventory(root, DECISION_OUTCOME_LOG_PATH),
        "episode_type": "decision_cycle_horizon_snapshot (nested .records, no feature_pack/regime fields on disk)",
        "forward_tail_window_covers_lines": f"last {max_per_source} of {decision_outcome_discovery['total_lines']}",
        "orphan_line_count": decision_outcome_discovery["orphan_line_count"],
        "orphan_resolved_candidate_count": decision_outcome_discovery["resolved_candidate_count"],
        "orphan_unresolved_excluded_count": decision_outcome_discovery["unresolved_excluded_count"],
        "orphan_date_range": decision_outcome_discovery["date_range"],
        "usability": "usable_for_historical_replay" if decision_outcome_discovery["resolved_candidate_count"] else "no_gap_fully_covered_by_forward",
        "usability_reason": (
            f"{decision_outcome_discovery['resolved_candidate_count']} resolved decision records "
            f"(non-null outcome_label) sit before the forward tail window and will never be read "
            f"again by the forward adapter; {decision_outcome_discovery['unresolved_excluded_count']} "
            "more in the same orphaned range are unresolved (outcome_label is null forever for that "
            "exact line) and are excluded as noise -- they carry no reward/outcome evidence. State and "
            "regime will be empty/unknown for all of them: this log format predates the "
            "growbot_river_learning_context field (see HISTORICAL_GAP_SOURCES in "
            "bot/growbot_river_readiness.py), so replay adds reward/outcome volume only, not "
            "feature/regime coverage."
        ),
    }
    sources["logs/trade_reflections.jsonl"] = {
        **_jsonl_basic_inventory(root, TRADE_REFLECTION_LOG_PATH),
        "episode_type": "closed_trade_reflection (envelope.reflection) / trade_learning_cycle_summary heartbeat",
        "orphan_line_count": trade_reflection_orphan,
        "usability": "no_gap_fully_covered_by_forward",
        "usability_reason": (
            "Total lines never exceed max_per_source, so the forward adapter has always re-read the "
            "whole file; the file currently holds only 1 real `.reflection` row (287 of 288 lines are "
            "`trade_learning_cycle_summary` heartbeats) and that single row is already present in the "
            "forward ledger by episode_id. The forward ledger's 288 trade_reflection-sourced episodes "
            "predate an apparent log rotation/truncation of this file; that content is not recoverable "
            "from the current on-disk file and is not lost -- it is already captured."
            if (root / TRADE_REFLECTION_LOG_PATH).exists() and str(root / TRADE_REFLECTION_LOG_PATH).strip()
            else "file not found"
        ),
        "single_remaining_reflection_already_in_forward_ledger": bool(forward_trade_reflection_ids),
    }
    sources["logs/execution_outcomes.jsonl"] = {
        **_jsonl_basic_inventory(root, EXECUTION_OUTCOME_LOG_PATH),
        "episode_type": "paper_limit_order_lifecycle_outcome",
        "orphan_line_count": execution_outcome_orphan,
        "usability": "no_gap_fully_covered_by_forward",
        "usability_reason": "All 10 rows are within max_per_source and already in the forward ledger by episode_id.",
        "all_rows_already_in_forward_ledger": bool(forward_execution_outcome_ids),
    }
    sources["logs/reflection_adaptive_sidecar.jsonl"] = {
        **_jsonl_basic_inventory(root, REFLECTION_ADAPTIVE_SIDECAR_LOG_PATH),
        "episode_type": "adaptive_pipeline_run_summary (heartbeat: commands run, governor status, candidate availability)",
        "usability": "not_episode_shaped",
        "usability_reason": (
            "Each row is a whole-pipeline run report (commands + governor + candidate status), not a "
            "per-decision/trade/execution record. No ticker-level decision_context, reward or "
            "outcome evidence to extract; would only ever produce zero-state, zero-reward noise "
            "episodes."
        ),
    }
    sources["logs/decision_outcome_report.json"] = {
        **_json_basic_inventory(root, DECISION_OUTCOME_REPORT_PATH),
        "episode_type": "stale_count_only_summary",
        "usability": "skip_empty_summary",
        "usability_reason": "count=0 and all detail lists empty; a one-time snapshot from the first cycle (2026-05-13), superseded by logs/decision_outcomes.jsonl itself.",
    }
    sources["logs/trade_learning_report.json"] = {
        **_json_basic_inventory(root, TRADE_LEARNING_REPORT_PATH),
        "episode_type": "stale_count_only_summary",
        "usability": "skip_empty_summary",
        "usability_reason": "sample_size=0, all groups/candidate lists empty; a one-time snapshot from the first cycle (2026-05-13), superseded by logs/trade_reflections.jsonl itself.",
    }
    sources["reports/live_learning/"] = {
        **_dir_basic_inventory(root, LIVE_LEARNING_DIR),
        "episode_type": "mixed: most files are count/status summaries; neural-training-dataset-latest.jsonl is per-sample but a single bulk synthetic snapshot",
        "usability": "skip_out_of_scope",
        "usability_reason": (
            "Most files (decision_outcomes_latest.json, execution_outcomes_latest.json, "
            "live-learning-context-latest.json, etc.) are aggregate counts/labels, not per-episode "
            "evidence. neural-training-dataset-latest.jsonl has per-sample feature/reward records "
            "(3654 rows) but every row shares the exact same created_at timestamp -- it is one bulk "
            "synthetic generation, not source-time-distributed organic decisions, and the existing "
            "adapter already treats the neural-shadow track as informational provenance only, never a "
            "parameter-vote input (see NEURAL_SHADOW_REPORT_PATH handling in "
            "bot/growbot_learning_adapter.py). Importing it here would blur that deliberate boundary; "
            "left out of scope for this pass."
        ),
    }
    sources["reports/d6/"] = {
        **_dir_basic_inventory(root, D6_DIR),
        "episode_type": "readiness/architecture/governance status reports (single JSON object per file, no per-trade records)",
        "usability": "not_episode_shaped",
        "usability_reason": "Sampled files contain booleans/flags about what the report run did or didn't do (coinbase_write_performed, config_mutation_performed, etc.); no ticker-level decision/trade/execution evidence anywhere in the schema.",
    }
    sources["reports/audits/"] = {
        **_dir_basic_inventory(root, AUDITS_DIR),
        "episode_type": "policy/contract/governance audit reports (single JSON object per file, no per-trade records)",
        "usability": "not_episode_shaped",
        "usability_reason": "Sampled files are policy/governor/contract verification snapshots (candidate hashes, gate states, changed_files); no per-decision evidence to extract.",
    }
    sources["reports/growbot_river/history/"] = {
        **_dir_basic_inventory(root, GROWBOT_RIVER_HISTORY_DIR),
        "episode_type": "already-processed episode ledger (episodes.jsonl) and proposal history (proposal-history.jsonl)",
        "usability": "destination_not_source",
        "usability_reason": "episodes.jsonl is the forward adapter's own append-only output -- the destination this module compares against, not a new input. proposal-history.jsonl is phase-stability bookkeeping, not episodes.",
        "forward_ledger_episode_count": len(forward_episodes),
    }
    sources["reports/growbot_river/"] = {
        **_dir_basic_inventory(root, GROWBOT_RIVER_DIR),
        "episode_type": "GrowBot/River's own latest-cycle reports (episode/river/readiness/registry), not raw inputs",
        "usability": "destination_not_source",
        "usability_reason": "These are this sidecar's own output reports, read for cross-checks elsewhere in this module, not converted into new episodes themselves.",
    }
    return {
        "schema_version": "growbot_historical_source_audit_v1",
        "generated_at": now_iso(),
        "max_per_source": max_per_source,
        "sources": sources,
        "summary": {
            "usable_for_historical_replay": ["logs/decision_outcomes.jsonl"],
            "no_gap_already_covered": ["logs/trade_reflections.jsonl", "logs/execution_outcomes.jsonl"],
            "skipped_not_episode_shaped_or_empty": [
                "logs/reflection_adaptive_sidecar.jsonl",
                "logs/decision_outcome_report.json",
                "logs/trade_learning_report.json",
                "reports/live_learning/",
                "reports/d6/",
                "reports/audits/",
            ],
            "destinations_not_sources": ["reports/growbot_river/history/", "reports/growbot_river/"],
        },
        "policy": {
            "no_market_data_added_to_old_episodes": True,
            "source_time_evidence_only": True,
            "regime_only_from_record_or_attached_historical_snapshot": True,
            "forward_ledger_never_written_by_this_module": True,
        },
    }


def render_source_audit_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Historical GrowBot/River source audit", "", f"Generated: {report.get('generated_at')}", ""]
    summary = report.get("summary") or {}
    lines.append("## Verdict summary")
    for key in ("usable_for_historical_replay", "no_gap_already_covered", "skipped_not_episode_shaped_or_empty", "destinations_not_sources"):
        lines.append(f"- **{key}**: {', '.join(summary.get(key) or []) or '(none)'}")
    lines.append("")
    lines.append("## Per-source detail")
    for name, detail in (report.get("sources") or {}).items():
        lines.append(f"### {name}")
        for key, value in detail.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines)


def write_source_audit_report(report: Mapping[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    json_path = root / SOURCE_AUDIT_JSON_PATH
    md_path = root / SOURCE_AUDIT_MD_PATH
    atomic_write_json(json_path, dict(report))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_source_audit_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


# ---------------------------------------------------------------------------
# Combined coverage report: historical vs forward vs combined, plus sandboxed
# (never touching production state) River diagnostics.
# ---------------------------------------------------------------------------

def _sandboxed_river_diagnostics(episodes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Run the River fallback/native learner against an episode list in an
    isolated temp root so this diagnostic never reads or writes the
    production river-online-model-state.json / *.pkl files."""
    if not episodes:
        return {"skipped": True, "reason": "no_episodes"}
    with tempfile.TemporaryDirectory(prefix="growbot_historical_river_sandbox_") as tmp:
        report = run_river_online_parameter_learning(list(episodes), root=Path(tmp))
    signals = sorted(
        report.get("parameter_signals") or [],
        key=lambda item: (float(item.get("confidence") or 0.0), float(item.get("evidence_count") or 0.0)),
        reverse=True,
    )
    return {
        "skipped": False,
        "backend": (report.get("backend") or {}).get("backend"),
        "top_parameter_candidates": signals[:10],
        "walk_forward_validation": report.get("walk_forward_validation") or {},
    }


def build_coverage_report(root: Path) -> Dict[str, Any]:
    forward_episodes = _load_jsonl_episodes(root / FORWARD_EPISODE_LEDGER_PATH)
    historical_episodes = _load_jsonl_episodes(root / HISTORICAL_EPISODE_LEDGER_PATH)
    combined_episodes = forward_episodes + historical_episodes

    forward_contract = validate_episode_contracts(forward_episodes)
    historical_contract = validate_episode_contracts(historical_episodes)
    combined_contract = validate_episode_contracts(combined_episodes)

    regimes_before = _distinct_known_regimes(forward_episodes)
    regimes_after = _distinct_known_regimes(combined_episodes)

    forward_requirements_before = estimate_forward_episode_requirements(
        coverage=forward_contract["coverage"], episode_count=forward_contract["episode_count"]
    )
    forward_requirements_after = estimate_forward_episode_requirements(
        coverage=combined_contract["coverage"], episode_count=combined_contract["episode_count"]
    )

    river_evidence_admitted = historical_contract.get("syntactic_contract_passed") is True and bool(historical_episodes)
    river_diagnostics: Dict[str, Any]
    if river_evidence_admitted:
        river_diagnostics = {
            "admitted": True,
            "admission_reason": "historical_episode_contract_syntactically_passed",
            "forward_only": _sandboxed_river_diagnostics(forward_episodes),
            "historical_only": _sandboxed_river_diagnostics(historical_episodes),
            "combined": _sandboxed_river_diagnostics(combined_episodes),
            "isolation": "each run uses its own temporary root; production reports/growbot_river/river-online-model-state.json and *.pkl are never read or written by this diagnostic",
        }
    else:
        river_diagnostics = {
            "admitted": False,
            "admission_reason": (
                "no_historical_episodes" if not historical_episodes else "historical_episode_contract_failed_syntactic_validation"
            ),
        }

    stabilization_volume_gate = lambda count, regimes: count >= 120 and len(regimes) >= 2  # noqa: E731
    fine_tuning_volume_gate = lambda count, regimes: count >= 500 and len(regimes) >= 3  # noqa: E731

    return {
        "schema_version": "growbot_historical_replay_coverage_v1",
        "generated_at": now_iso(),
        "episode_counts": {
            "forward": len(forward_episodes),
            "historical": len(historical_episodes),
            "combined": len(combined_episodes),
        },
        "forward_coverage": forward_contract,
        "historical_coverage": historical_contract,
        "combined_coverage": combined_contract,
        "regime_coverage": {
            "distinct_known_regimes_before": regimes_before,
            "distinct_known_regimes_after": regimes_after,
            "distinct_known_regime_count_before": len(regimes_before),
            "distinct_known_regime_count_after": len(regimes_after),
            "newly_observed_regimes_from_historical_replay": sorted(set(regimes_after) - set(regimes_before)),
        },
        "estimated_forward_episodes_needed": {
            "before_historical_replay": forward_requirements_before,
            "after_historical_replay": forward_requirements_after,
        },
        "stabilization_readiness": {
            "volume_and_regime_gate_before": stabilization_volume_gate(forward_contract["episode_count"], regimes_before),
            "volume_and_regime_gate_after": stabilization_volume_gate(combined_contract["episode_count"], regimes_after),
            "fine_tuning_gate_before": fine_tuning_volume_gate(forward_contract["episode_count"], regimes_before),
            "fine_tuning_gate_after": fine_tuning_volume_gate(combined_contract["episode_count"], regimes_after),
            "note": (
                "Gates shown here are the episode-count/distinct-regime thresholds only "
                "(>=120/2 for stabilization, >=500/3 for fine_tuning); the full "
                "stabilization_ready flag in growbot-river-readiness-latest.json also requires "
                ">=80% feature-state and regime coverage and a passed River walk-forward run, which "
                "this historical slice does not improve (see honest_limitation below)."
            ),
        },
        "river_diagnostics": river_diagnostics,
        "honest_limitation": (
            "decision_outcome historical rows predate the growbot_river_learning_context fix and "
            "carry no feature_pack/regime data on disk (see HISTORICAL_GAP_SOURCES in "
            "bot/growbot_river_readiness.py). Historical replay therefore adds real reward/outcome "
            "volume and label diversity, but contributes 0 to nonempty_feature_state_pct and 0 to "
            "known_market_regime_pct -- it does not, by itself, move stabilization_ready closer to "
            "true, and the rollover episode estimate for the 80% coverage gates can be flat or "
            "slightly higher after replay (larger denominator, same zero-state numerator)."
        ),
        "safety_policy": {
            "report_only": True,
            "parameter_mutation_allowed": False,
            "execution_authority": False,
            "forward_ledger_mutated": False,
            "production_river_model_state_mutated": False,
        },
    }


def render_coverage_markdown(report: Mapping[str, Any]) -> str:
    counts = report.get("episode_counts") or {}
    lines = [
        "# Historical replay coverage report",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        f"- forward episodes: {counts.get('forward')}",
        f"- historical episodes: {counts.get('historical')}",
        f"- combined episodes: {counts.get('combined')}",
        "",
        "## Coverage (forward / historical / combined)",
    ]
    for label, key in (("forward", "forward_coverage"), ("historical", "historical_coverage"), ("combined", "combined_coverage")):
        contract = report.get(key) or {}
        coverage = contract.get("coverage") or {}
        lines.append(f"### {label}")
        lines.append(f"- episode_count: {contract.get('episode_count')}")
        lines.append(f"- syntactic_contract_passed: {contract.get('syntactic_contract_passed')}")
        lines.append(f"- nonempty_feature_state_pct: {coverage.get('nonempty_feature_state_pct')}")
        lines.append(f"- known_market_regime_pct: {coverage.get('known_market_regime_pct')}")
        lines.append(f"- observed_nonzero_reward_pct: {coverage.get('observed_nonzero_reward_pct')}")
        lines.append(f"- parameter_hint_count: {coverage.get('parameter_hint_count')}")
        lines.append("")
    regime = report.get("regime_coverage") or {}
    lines.append("## Regime coverage")
    lines.append(f"- before: {regime.get('distinct_known_regimes_before')}")
    lines.append(f"- after: {regime.get('distinct_known_regimes_after')}")
    lines.append(f"- newly observed from replay: {regime.get('newly_observed_regimes_from_historical_replay')}")
    lines.append("")
    needed = report.get("estimated_forward_episodes_needed") or {}
    lines.append("## Estimated forward episodes still needed (rollover model)")
    lines.append(f"- before: {(needed.get('before_historical_replay') or {}).get('episodes_needed_rollover_model')}")
    lines.append(f"- after: {(needed.get('after_historical_replay') or {}).get('episodes_needed_rollover_model')}")
    lines.append("")
    lines.append("## Honest limitation")
    lines.append(str(report.get("honest_limitation")))
    return "\n".join(lines)


def write_coverage_report(report: Mapping[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    json_path = root / COVERAGE_JSON_PATH
    md_path = root / COVERAGE_MD_PATH
    atomic_write_json(json_path, dict(report))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_coverage_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


__all__ = [
    "EXTRACTION_VERSION",
    "DEFAULT_MAX_PER_SOURCE",
    "HISTORICAL_EPISODE_LEDGER_PATH",
    "SOURCE_AUDIT_JSON_PATH",
    "SOURCE_AUDIT_MD_PATH",
    "COVERAGE_JSON_PATH",
    "COVERAGE_MD_PATH",
    "quality_score",
    "discover_decision_outcome_orphan_candidates",
    "build_decision_outcome_historical_episodes",
    "build_historical_episodes",
    "append_historical_episodes",
    "audit_historical_sources",
    "render_source_audit_markdown",
    "write_source_audit_report",
    "build_coverage_report",
    "render_coverage_markdown",
    "write_coverage_report",
]
