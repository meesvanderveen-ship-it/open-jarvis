from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.apply_reconstructed_position_risk_completion import (
    RUNTIME_ACK_ENV,
    build_risk_completion_report,
)


NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(root: Path, *, status: str = "open", current_price: str = "11") -> None:
    _write_json(
        root / "state/positions.json",
        {
            "ADA-USDC": {
                "ticker": "ADA-USDC",
                "status": status,
                "order_id": "ada-position-1",
                "position_size_base": "121.58054711",
                "bot_managed_base": "121.58054711",
                "entry_price": "10",
                "stop_price": "0",
                "invalidation_price": "0",
                "position_risk_incomplete": True,
                "protective_stop_status": "position_risk_incomplete",
            }
        },
    )
    _write_json(root / "state/open_orders.json", {"orders": {}})
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "positions": [
                {
                    "ticker": "ADA-USDC",
                    "position_id": "ada-position-1",
                    "base_filled": "121.58054711",
                    "avg_entry_price": "10",
                    "exposure": {
                        "base_size_local": "121.58054711",
                        "avg_entry_price": "10",
                        "current_price": current_price,
                        "market_evidence_timestamp": NOW.isoformat(),
                    },
                    "risk_reconstruction_preview": {
                        "proposed_stop_price": "9",
                        "proposed_invalidation_price": "8.5",
                        "current_price_vs_stop": "above",
                        "market_evidence_timestamp": NOW.isoformat(),
                    },
                }
            ]
        },
    )


def test_preview_is_read_only_and_hashes_exact_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    before = (tmp_path / "state/positions.json").read_text(encoding="utf-8")

    report = build_risk_completion_report(ticker="ADA-USDC", root=tmp_path, now=NOW)

    assert report["status"] == "risk_completion_preview_ready"
    assert report["evidence_hash"]
    assert report["state_write_performed"] is False
    assert (tmp_path / "state/positions.json").read_text(encoding="utf-8") == before


def test_apply_requires_matching_external_ack_and_evidence_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    preview = build_risk_completion_report(ticker="ADA-USDC", root=tmp_path, now=NOW)
    monkeypatch.setenv(RUNTIME_ACK_ENV, "operator-approved")

    report = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        apply=True,
        caller_ack="wrong",
        expected_evidence_hash=preview["evidence_hash"],
        now=NOW,
    )

    assert report["status"] == "risk_completion_apply_blocked"
    assert "caller_ack_missing_or_mismatch" in report["blockers"]
    assert report["state_write_performed"] is False


def test_closed_position_is_never_reconstructed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, status="closed")

    report = build_risk_completion_report(ticker="ADA-USDC", root=tmp_path, now=NOW)

    assert report["status"] == "risk_completion_preview_blocked"
    assert "position_not_currently_open" in report["blockers"]


def test_stop_breach_requires_controlled_close_route_without_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, current_price="8")

    report = build_risk_completion_report(ticker="ADA-USDC", root=tmp_path, now=NOW)

    assert report["status"] == "risk_completion_preview_blocked"
    assert "controlled_close_route_required_stop_breached" in report["blockers"]
    assert report["state_write_performed"] is False


def test_ephemeral_market_evidence_is_hashed_read_only_and_fresh(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, current_price="10")
    before = (tmp_path / "state/positions.json").read_text(encoding="utf-8")

    report = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        market_price="11.5",
        market_evidence_timestamp=NOW.isoformat(),
        now=NOW,
    )

    assert report["status"] == "risk_completion_preview_ready"
    assert report["ephemeral_market_evidence_used"] is True
    assert report["evidence"]["current_price"] == "11.5"
    assert report["evidence"]["market_evidence_timestamp"] == NOW.isoformat()
    assert report["state_write_performed"] is False
    assert (tmp_path / "state/positions.json").read_text(encoding="utf-8") == before


def test_ephemeral_market_evidence_requires_complete_fresh_pair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)

    missing_timestamp = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        market_price="11.5",
        now=NOW,
    )
    stale = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        market_price="11.5",
        market_evidence_timestamp=(NOW - timedelta(minutes=16)).isoformat(),
        now=NOW,
    )

    assert "market_evidence_override_pair_required" in missing_timestamp["blockers"]
    assert "market_evidence_missing_or_stale" in stale["blockers"]


def test_apply_is_atomic_and_idempotent_in_tmp_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    monkeypatch.setenv(RUNTIME_ACK_ENV, "operator-approved")
    preview = build_risk_completion_report(ticker="ADA-USDC", root=tmp_path, now=NOW)

    applied = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        apply=True,
        caller_ack="operator-approved",
        expected_evidence_hash=preview["evidence_hash"],
        now=NOW,
    )
    repeated = build_risk_completion_report(
        ticker="ADA-USDC",
        root=tmp_path,
        apply=True,
        caller_ack="operator-approved",
        expected_evidence_hash=preview["evidence_hash"],
        now=NOW,
    )

    assert applied["status"] == "risk_completion_apply_completed"
    assert applied["state_write_performed"] is True
    assert applied["mutation_lock"]["acquired"] is True
    assert repeated["status"] == "risk_completion_apply_idempotent_noop"
    assert repeated["state_write_performed"] is False
    state = json.loads((tmp_path / "state/positions.json").read_text(encoding="utf-8"))
    assert state["ADA-USDC"]["protective_stop_status"] == "protective_stop_state_complete"
    assert state["ADA-USDC"]["position_risk_incomplete"] is False
