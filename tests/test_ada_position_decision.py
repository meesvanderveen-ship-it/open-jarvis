from __future__ import annotations

import json
from pathlib import Path

from tools.prepare_ada_position_decision import build_ada_position_decision, write_ada_position_decision


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_reports(root: Path) -> None:
    _write_json(
        root / "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
        {
            "positions_to_close": ["ETH-USDC", "AVAX-USDC", "SOL-USDC"],
            "positions_to_review": ["ADA-USDC"],
            "positions": [
                {
                    "ticker": "ADA-USDC",
                    "base_balance_verified": True,
                    "below_reconstructed_stop": False,
                }
            ],
        },
    )
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "positions": [
                {
                    "ticker": "ADA-USDC",
                    "current_base_balance_verified": True,
                }
            ]
        },
    )
    _write_json(
        root / "state/positions.json",
        {
            "ADA-USDC": {
                "status": "open",
                "protective_stop_status": "position_risk_incomplete",
                "position_risk_incomplete": True,
            }
        },
    )


def test_ada_position_decision_prepares_separate_routes_without_auto_close(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    report = build_ada_position_decision(root=tmp_path)

    assert report["ticker"] == "ADA-USDC"
    assert report["current_status"] == "position_risk_incomplete"
    assert report["above_reconstructed_stop"] is True
    assert report["base_balance_verified"] is True
    assert report["routes"] == [
        "manual_hold_review",
        "risk_completion_apply_after_ack",
        "controlled_close_after_ack",
    ]
    assert report["recommended_route"] == "manual_hold_review_or_risk_completion_after_ack"
    assert report["operator_ack_required"] is True
    assert report["live_action_allowed_now"] is False
    assert report["ada_in_controlled_close_batch"] is False


def test_ada_decision_tool_never_submits_or_writes_state(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    state_path = tmp_path / "state/positions.json"
    before = state_path.read_text(encoding="utf-8")

    report = build_ada_position_decision(root=tmp_path)
    write_ada_position_decision(report, root=tmp_path)

    assert report["coinbase_call_attempted"] is False
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False
    assert state_path.read_text(encoding="utf-8") == before
    assert (tmp_path / "reports/audits/ada-position-decision-prep-latest.json").exists()
    assert (tmp_path / "reports/audits/ada-position-decision-prep-latest.md").exists()
