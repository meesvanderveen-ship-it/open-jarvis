"""Tests for Shadow Outcome Accelerator dashboard endpoints.

Covers:
- All 4 shadow-outcomes endpoints return correct shapes
- Graceful handling of missing JSONL / report files
- Parameters without proposals visible as no_proposal
- Not-wired parameters visible
- Governor-owned parameters correctly labeled
- Full parameter proposals endpoint
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard.backend.services import shadow_outcomes as so_service
from dashboard.backend.services import full_proposals as fp_service


# ---------------------------------------------------------------------------
# Shadow outcomes service — missing files
# ---------------------------------------------------------------------------

def test_status_missing_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(so_service, "_REPORT_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(so_service, "_STORE_JSONL", tmp_path / "missing.jsonl")
    from dashboard.backend import cache; cache.clear()
    result = so_service._compute_status()
    assert result["total_shadow_decisions"] == 0
    assert result["source"] == "no_data"
    assert result["no_live_orders"] is True
    assert result["no_coinbase_calls"] is True
    assert result["no_parameter_mutation"] is True


def test_status_reads_report_json_when_present(tmp_path, monkeypatch):
    report = {
        "total_shadow_decisions": 42,
        "usable_evidence_count": 5,
        "evidence_quality_score": 0.3,
        "status_counts": {"pending": 42},
        "evaluations_by_horizon": {},
        "by_ticker": {"BTC-USDC": 42},
        "by_regime": {"trend_up": 20, "range_chop": 22},
        "top_missed_opportunity_patterns": [],
        "top_bad_trade_avoided_patterns": [],
        "quality_distribution": {},
        "sufficient_for_optimization": False,
        "sufficiency_note": "Not yet sufficient",
        "learning_policy": "evidence only",
    }
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report))
    monkeypatch.setattr(so_service, "_REPORT_JSON", p)
    monkeypatch.setattr(so_service, "_STORE_JSONL", tmp_path / "missing.jsonl")
    from dashboard.backend import cache; cache.clear()
    result = so_service._compute_status()
    assert result["total_shadow_decisions"] == 42
    assert result["source"] == "report_json"


def test_status_falls_back_to_jsonl(tmp_path, monkeypatch):
    record = {
        "shadow_id": "sha_abc",
        "ticker": "ETH-USDC",
        "timestamp": "2026-06-25T10:00:00+00:00",
        "decision": "wait",
        "status": "pending",
        "market_regime": "range_chop",
        "evaluations": {"1h": None, "4h": None, "24h": None},
        "due_at": {"1h": "2026-06-25T11:00:00+00:00"},
    }
    p = tmp_path / "shadow.jsonl"
    p.write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(so_service, "_REPORT_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(so_service, "_STORE_JSONL", p)
    from dashboard.backend import cache; cache.clear()
    result = so_service._compute_status()
    assert result["total_shadow_decisions"] == 1
    assert result["source"] == "jsonl_derived"
    assert result["by_ticker"]["ETH-USDC"] == 1


def test_status_corrupt_jsonl_line_skipped(tmp_path, monkeypatch):
    lines = 'not json\n{"shadow_id":"sha_x","ticker":"BTC-USDC","status":"pending"}\n'
    p = tmp_path / "shadow.jsonl"
    p.write_text(lines)
    monkeypatch.setattr(so_service, "_REPORT_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(so_service, "_STORE_JSONL", p)
    from dashboard.backend import cache; cache.clear()
    result = so_service._compute_status()
    assert result["total_shadow_decisions"] == 1


# ---------------------------------------------------------------------------
# Recent endpoint
# ---------------------------------------------------------------------------

def test_recent_returns_newest_first(tmp_path, monkeypatch):
    records = [
        {"shadow_id": f"sha_{i}", "ticker": "BTC-USDC", "timestamp": f"2026-06-25T{i:02d}:00:00+00:00",
         "decision": "wait", "status": "pending", "evaluations": {}}
        for i in range(5)
    ]
    p = tmp_path / "shadow.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    monkeypatch.setattr(so_service, "_STORE_JSONL", p)
    from dashboard.backend import cache; cache.clear()
    result = so_service.get_shadow_outcomes_recent(limit=3)
    assert result["returned"] == 3
    assert result["total_records"] == 5
    assert result["records"][0]["shadow_id"] == "sha_4"  # newest first


def test_recent_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(so_service, "_STORE_JSONL", tmp_path / "missing.jsonl")
    from dashboard.backend import cache; cache.clear()
    result = so_service.get_shadow_outcomes_recent()
    assert result["total_records"] == 0
    assert result["records"] == []


# ---------------------------------------------------------------------------
# Coverage and patterns
# ---------------------------------------------------------------------------

def test_coverage_always_has_required_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(so_service, "_REPORT_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(so_service, "_STORE_JSONL", tmp_path / "missing.jsonl")
    from dashboard.backend import cache; cache.clear()
    result = so_service.get_shadow_outcomes_coverage()
    for key in ("by_ticker", "by_regime", "evaluations_by_horizon", "sufficient_for_optimization"):
        assert key in result


def test_patterns_always_has_required_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(so_service, "_REPORT_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(so_service, "_STORE_JSONL", tmp_path / "missing.jsonl")
    from dashboard.backend import cache; cache.clear()
    result = so_service.get_shadow_outcomes_patterns()
    assert "top_missed_opportunity_patterns" in result
    assert "top_bad_trade_avoided_patterns" in result
    assert result["no_live_orders"] is True


# ---------------------------------------------------------------------------
# Full parameter proposals service
# ---------------------------------------------------------------------------

def test_full_proposals_returns_all_known_parameters(monkeypatch):
    monkeypatch.setattr(fp_service, "_ROOT", Path("/nonexistent"))
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    names = {p["name"] for p in result["parameters"]}
    # All parameter meta entries should appear
    for param in fp_service._PARAMETER_META:
        assert param in names, f"{param} missing from full proposals"


def test_full_proposals_no_proposal_when_no_sources(monkeypatch):
    monkeypatch.setattr(fp_service, "_ROOT", Path("/nonexistent"))
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    no_proposal = [p for p in result["parameters"] if p["status"] == "no_proposal"]
    assert len(no_proposal) > 0, "Expected some parameters with no_proposal status"


def test_full_proposals_governor_allowlist_labeled(monkeypatch):
    monkeypatch.setattr(fp_service, "_ROOT", Path("/nonexistent"))
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    by_name = {p["name"]: p for p in result["parameters"]}
    assert by_name["MAX_SPREAD_PCT"]["in_governor_allowlist"] is True
    assert by_name["JUDGE_MIN_GATE_CONFIDENCE"]["in_governor_allowlist"] is False


def test_full_proposals_approved_profile_wires_current_value(tmp_path, monkeypatch):
    profile = {"parameters": {"MAX_SPREAD_PCT": "0.005", "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.012"}}
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "approved_parameter_profile.json").write_text(json.dumps(profile))
    monkeypatch.setattr(fp_service, "_ROOT", tmp_path)
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    by_name = {p["name"]: p for p in result["parameters"]}
    assert by_name["MAX_SPREAD_PCT"]["current_value"] == "0.005"
    assert by_name["MAX_SPREAD_PCT"]["active_in_runtime"] is True
    assert by_name["MAX_SPREAD_PCT"]["consumed_by_runtime"] is True
    assert by_name["MAX_SPREAD_PCT"]["visible_in_approved_profile"] is True


def test_full_proposals_river_proposal_enriches_row(tmp_path, monkeypatch):
    profile = {"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.01227188"}}
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "approved_parameter_profile.json").write_text(json.dumps(profile))
    river = {
        "generated_at": "2026-06-25T12:00:00Z",
        "proposals": [{
            "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
            "candidate_value": 0.01204777,
            "direction": "loosen",
            "confidence": 0.9,
            "evidence_count": 211,
            "blockers": [],
            "safe_to_activate_now": False,
            "activation_route": "current_governor_and_approved_profile",
            "rollback": ["retain_previous_approved_profile_hash"],
            "regimes": ["high_volatility", "trend_up"],
        }],
    }
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "growbot_river").mkdir(parents=True)
    (tmp_path / "reports" / "growbot_river" / "growbot-river-learning-latest.json").write_text(json.dumps(river))
    monkeypatch.setattr(fp_service, "_ROOT", tmp_path)
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    by_name = {p["name"]: p for p in result["parameters"]}
    edge = by_name["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]
    assert edge["source"] == "growbot_river"
    assert edge["proposed_value"] == 0.01204777
    assert edge["direction"] == "loosen"
    assert edge["status"] == "needs_more_evidence"
    assert "high_volatility" in edge["regimes_seen"]


def test_full_proposals_parameter_not_in_approved_profile_shows_not_wired(monkeypatch):
    monkeypatch.setattr(fp_service, "_ROOT", Path("/nonexistent"))
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    by_name = {p["name"]: p for p in result["parameters"]}
    # JUDGE params are not in approved_parameter_profile by default
    judge = by_name.get("JUDGE_MIN_GATE_CONFIDENCE")
    if judge:
        assert judge["active_in_runtime"] is False
        assert judge["visible_in_approved_profile"] is False


def test_full_proposals_summary_counts_correct(monkeypatch):
    monkeypatch.setattr(fp_service, "_ROOT", Path("/nonexistent"))
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    total = result["total_parameters"]
    assert total > 0
    assert result["parameters_no_proposal"] + result["parameters_with_proposal"] == total


def test_full_proposals_shadow_evidence_surfaced(tmp_path, monkeypatch):
    shadow_report = {
        "total_shadow_decisions": 30,
        "usable_evidence_count": 10,
        "sufficient_for_optimization": False,
    }
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "parameter_optimization").mkdir(parents=True)
    (tmp_path / "reports" / "parameter_optimization" / "shadow-outcome-accelerator-latest.json").write_text(
        json.dumps(shadow_report)
    )
    monkeypatch.setattr(fp_service, "_ROOT", tmp_path)
    from dashboard.backend import cache; cache.clear()
    result = fp_service._compute_full_proposals()
    assert result["shadow_evidence_total"] == 30
    assert result["shadow_evidence_usable"] == 10
    # Each parameter row should carry shadow evidence counts
    for row in result["parameters"]:
        assert row["shadow_evidence_total"] == 30
