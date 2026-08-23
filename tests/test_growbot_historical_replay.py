from __future__ import annotations

import json
from pathlib import Path

from bot.growbot_historical_replay import (
    HISTORICAL_EPISODE_LEDGER_PATH,
    append_historical_episodes,
    audit_historical_sources,
    build_coverage_report,
    build_decision_outcome_historical_episodes,
    build_historical_episodes,
    discover_decision_outcome_orphan_candidates,
    quality_score,
    write_coverage_report,
    write_source_audit_report,
)
from bot.growbot_learning_adapter import EPISODE_LEDGER_PATH as FORWARD_EPISODE_LEDGER_PATH


def _write_decision_outcome_log(root: Path, *, before_window: int, in_window: int) -> None:
    """Write `before_window` resolved lines (will fall outside a small tail
    window) followed by `in_window` lines that the forward adapter would
    still read today."""
    log_path = root / "logs/decision_outcomes.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(before_window):
        envelope = {
            "generated_at": f"2026-05-01T00:00:{i:02d}Z",
            "event": "decision_outcome_snapshots_stored",
            "records": [
                {
                    "ticker": "BTC-USDC",
                    "created_at": f"2026-05-01T00:00:{i:02d}Z",
                    "horizon_hours": 4,
                    "decision_category": "wait",
                    "decision": "wait",
                    "plan_action": "no_plan",
                    "outcome_label": "correct_avoid" if i % 2 == 0 else "missed_opportunity",
                    "price_change_pct": -0.01,
                    "max_favorable_pct": 0.001,
                    "max_adverse_pct": -0.02,
                },
                {
                    "ticker": "BTC-USDC",
                    "created_at": f"2026-05-01T00:00:{i:02d}Z",
                    "horizon_hours": 12,
                    "decision_category": "wait",
                    "decision": "wait",
                    "plan_action": "no_plan",
                    "outcome_label": None,
                    "price_change_pct": None,
                    "max_favorable_pct": None,
                    "max_adverse_pct": None,
                },
            ],
        }
        lines.append(json.dumps(envelope))
    for i in range(in_window):
        envelope = {
            "generated_at": f"2026-06-01T00:00:{i:02d}Z",
            "event": "decision_outcome_snapshots_stored",
            "records": [
                {
                    "ticker": "ETH-USDC",
                    "created_at": f"2026-06-01T00:00:{i:02d}Z",
                    "horizon_hours": 4,
                    "decision_category": "wait",
                    "decision": "wait",
                    "plan_action": "no_plan",
                    "outcome_label": "correct_avoid",
                    "price_change_pct": -0.01,
                    "max_favorable_pct": 0.001,
                    "max_adverse_pct": -0.02,
                }
            ],
        }
        lines.append(json.dumps(envelope))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_orphan_discovery_only_sees_lines_outside_the_tail_window(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=10, in_window=3)
    discovery = discover_decision_outcome_orphan_candidates(tmp_path, max_per_source=3)
    assert discovery["total_lines"] == 13
    assert discovery["orphan_line_count"] == 10
    # Each orphan line has one resolved + one unresolved nested record.
    assert discovery["resolved_candidate_count"] == 10
    assert discovery["unresolved_excluded_count"] == 10
    assert len(discovery["candidates"]) == 10


def test_orphan_discovery_finds_nothing_when_file_is_within_the_window(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=0, in_window=3)
    discovery = discover_decision_outcome_orphan_candidates(tmp_path, max_per_source=1500)
    assert discovery["orphan_line_count"] == 0
    assert discovery["candidates"] == []


def test_unresolved_records_are_excluded_as_noise(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=5, in_window=0)
    episodes, stats = build_decision_outcome_historical_episodes(tmp_path, max_per_source=0)
    # Only the resolved (horizon_hours=4) record per line should be built.
    assert stats["resolved_candidate_count"] == 5
    assert stats["unresolved_excluded_count"] == 5
    assert len(episodes) == 5
    assert all(e["decision_context"]["decision"] == "wait" for e in episodes)


def test_provenance_fields_present_on_every_historical_episode(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=3, in_window=0)
    episodes, _ = build_decision_outcome_historical_episodes(tmp_path, max_per_source=0)
    for episode in episodes:
        assert episode["historical_replay"] is True
        assert episode["source_file"] == "logs/decision_outcomes.jsonl"
        assert episode["source_type"] == "historical_decision_outcome"
        assert episode["extraction_version"] == "growbot_historical_replay_v1"
        assert episode["original_timestamp"]
        assert "#record:" in episode["source_line_or_record_id"]
        assert "line:" in episode["source_line_or_record_id"]
        assert 0.0 <= episode["quality_score"] <= 1.0


def test_quality_score_rewards_richer_episodes() -> None:
    bare = {"state": {}, "regime": "unknown", "reward": 0.0, "ticker": "unknown", "decision_context": {}}
    rich = {
        "state": {"confidence": 0.7},
        "regime": "trend_up",
        "reward": 0.5,
        "ticker": "BTC-USDC",
        "decision_context": {"setup_type": "breakout"},
    }
    assert quality_score(bare) == 0.0
    assert quality_score(rich) == 1.0


def test_collision_safe_ids_keep_distinct_evidence_for_same_decision_moment(tmp_path: Path) -> None:
    """Two horizon snapshots of the same decision (same ticker/occurred_at/
    decision/label identity) but different evidence must not collapse to one
    episode_id -- that would silently drop real evidence as a "duplicate".
    """
    log_path = tmp_path / "logs/decision_outcomes.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "generated_at": "2026-05-01T00:00:00Z",
        "event": "decision_outcome_snapshots_stored",
        "records": [
            {
                "ticker": "BTC-USDC",
                "created_at": "2026-05-01T00:00:00Z",
                "horizon_hours": 4,
                "decision_category": "wait",
                "decision": "wait",
                "outcome_label": "correct_avoid",
                "price_change_pct": -0.01,
            },
            {
                "ticker": "BTC-USDC",
                "created_at": "2026-05-01T00:00:00Z",
                "horizon_hours": 24,
                "decision_category": "wait",
                "decision": "wait",
                "outcome_label": "correct_avoid",
                "price_change_pct": -0.05,
            },
        ],
    }
    log_path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
    episodes, stats = build_decision_outcome_historical_episodes(tmp_path, max_per_source=0)
    assert len(episodes) == 2
    assert stats["compact_identity_collisions_resolved"] == 1
    assert episodes[0]["episode_id"] != episodes[1]["episode_id"]
    assert episodes[0]["base_episode_id"] == episodes[1]["base_episode_id"]


def test_append_historical_episodes_is_idempotent_and_separate_from_forward_ledger(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=4, in_window=0)
    episodes, _ = build_decision_outcome_historical_episodes(tmp_path, max_per_source=0)
    first = append_historical_episodes(episodes, root=tmp_path)
    assert first["added"] == len(episodes)
    second = append_historical_episodes(episodes, root=tmp_path)
    assert second["added"] == 0
    assert second["total_after"] == first["total_after"]
    assert (tmp_path / HISTORICAL_EPISODE_LEDGER_PATH).exists()
    assert not (tmp_path / FORWARD_EPISODE_LEDGER_PATH).exists()


def test_build_historical_episodes_reports_zero_gap_for_small_sources(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=2, in_window=0)
    (tmp_path / "logs/trade_reflections.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "logs/execution_outcomes.jsonl").write_text("", encoding="utf-8")
    built = build_historical_episodes(tmp_path, max_per_source=1500)
    assert built["by_source"]["trade_reflection"]["orphan_line_count"] == 0
    assert built["by_source"]["trade_reflection"]["reason"] == "no_gap_total_lines_under_max_per_source"
    assert built["by_source"]["execution_outcome"]["episodes_built"] == 0


def test_audit_reports_usability_verdict_per_source(tmp_path: Path) -> None:
    _write_decision_outcome_log(tmp_path, before_window=10, in_window=2)
    (tmp_path / "logs/trade_reflections.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "logs/execution_outcomes.jsonl").write_text("", encoding="utf-8")
    report = audit_historical_sources(tmp_path, max_per_source=2)
    assert "logs/decision_outcomes.jsonl" in report["summary"]["usable_for_historical_replay"]
    assert "logs/trade_reflections.jsonl" in report["summary"]["no_gap_already_covered"]
    detail = report["sources"]["logs/decision_outcomes.jsonl"]
    assert detail["orphan_resolved_candidate_count"] == 10
    outputs = write_source_audit_report(report, root=tmp_path)
    assert Path(outputs["json"]).exists()
    assert Path(outputs["md"]).exists()


def test_coverage_report_never_mutates_forward_ledger(tmp_path: Path) -> None:
    forward_ledger = tmp_path / FORWARD_EPISODE_LEDGER_PATH
    forward_ledger.parent.mkdir(parents=True, exist_ok=True)
    forward_episode = {
        "episode_id": "forward-1",
        "base_episode_id": "forward-1",
        "source": "reflection",
        "episode_type": "closed_trade",
        "state": {"confidence": 0.6},
        "regime": "trend_up",
        "decision_context": {"decision": "buy", "setup_type": "breakout", "main_blocker": ""},
        "action": "parameter_setting_or_threshold_selection",
        "reward": 0.5,
        "reward_reasons": ["positive_closed_or_execution_outcome"],
        "parameter_hints": [],
        "raw_evidence_ref": {"source": "reflection", "ticker": "BTC-USDC", "label": "good_trade"},
        "execution_authority": False,
        "ticker": "BTC-USDC",
        "label": "good_trade",
    }
    forward_ledger.write_text(json.dumps(forward_episode) + "\n", encoding="utf-8")
    before = forward_ledger.read_text(encoding="utf-8")

    _write_decision_outcome_log(tmp_path, before_window=6, in_window=0)
    episodes, _ = build_decision_outcome_historical_episodes(tmp_path, max_per_source=0)
    append_historical_episodes(episodes, root=tmp_path)

    coverage = build_coverage_report(tmp_path)
    assert forward_ledger.read_text(encoding="utf-8") == before
    assert coverage["episode_counts"]["forward"] == 1
    assert coverage["episode_counts"]["historical"] == len(episodes)
    assert coverage["episode_counts"]["combined"] == 1 + len(episodes)
    assert coverage["forward_coverage"]["syntactic_contract_passed"] is True
    assert coverage["historical_coverage"]["syntactic_contract_passed"] is True
    assert coverage["river_diagnostics"]["admitted"] is True
    outputs = write_coverage_report(coverage, root=tmp_path)
    assert Path(outputs["json"]).exists()
    assert Path(outputs["md"]).exists()


def test_river_diagnostics_skipped_when_no_historical_episodes(tmp_path: Path) -> None:
    forward_ledger = tmp_path / FORWARD_EPISODE_LEDGER_PATH
    forward_ledger.parent.mkdir(parents=True, exist_ok=True)
    forward_ledger.write_text("", encoding="utf-8")
    coverage = build_coverage_report(tmp_path)
    assert coverage["river_diagnostics"]["admitted"] is False
    assert coverage["river_diagnostics"]["admission_reason"] == "no_historical_episodes"
