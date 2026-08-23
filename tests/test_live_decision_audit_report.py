import json
from pathlib import Path

import pytest

from tools import build_live_decision_audit_report as audit


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_build_report_handles_missing_logs_and_writes_outputs(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "reports/live_learning").mkdir(parents=True)
    (tmp_path / "reports/live_runs").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "state/neural_shadow_policy.json").write_text(
        json.dumps(
            {
                "execution_allowed": False,
                "sample_count": 1,
                "trained_at": "2026-06-14T00:00:00Z",
                "majority_class": "prefer_no_trade",
                "class_counts": {"prefer_no_trade": 1},
                "centroids": {"prefer_no_trade": [1]},
            }
        ),
        encoding="utf-8",
    )

    report = audit.build_report(
        tmp_path,
        audit.parse_time("2026-06-14T00:00:00Z"),
        tmp_path / "reports/audits/live-decision-audit-latest.json",
        tmp_path / "reports/audits/live-decision-audit-latest.md",
    )

    assert report["read_only"] is True
    assert report["coinbase_action_attempted"] is False
    assert report["service_touched"] is False
    assert report["env_write_performed"] is False
    assert (tmp_path / "reports/audits/live-decision-audit-latest.json").exists()
    assert (tmp_path / "reports/audits/live-decision-audit-latest.md").exists()
    assert len(report["ticker_decisions"]) == 8


def test_recognizes_cycle_counts_and_decision_reasons(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "reports/live_learning").mkdir(parents=True)
    (tmp_path / "reports/live_runs").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "state/approved_parameter_profile.json").write_text(
        json.dumps({"profile_name": "test", "parameters": {"AUTONOMOUS_MAX_ORDER_QUOTE": "20.00"}}),
        encoding="utf-8",
    )
    (tmp_path / "state/neural_shadow_policy.json").write_text(
        json.dumps(
            {
                "execution_allowed": False,
                "sample_count": 10,
                "trained_at": "2026-06-14T00:00:00Z",
                "majority_class": "prefer_no_trade",
                "class_counts": {"prefer_no_trade": 10},
                "centroids": {"prefer_no_trade": [1]},
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        tmp_path / "logs/cycle_summary.jsonl",
        [
            {
                "generated_at": "2026-06-14T04:02:16Z",
                "total": 8,
                "approve_trade": 1,
                "wait": 6,
                "reject": 1,
                "executed": 1,
                "errors": 0,
            }
        ],
    )
    write_jsonl(
        tmp_path / "logs/execution.jsonl",
        [
            {
                "ticker": "BTC-USDC",
                "status": "no_trade",
                "executed": False,
                "reason": "judge_decision_wait",
                "judge": {
                    "ticker": "BTC-USDC",
                    "decision": "wait",
                    "strategy": "entry_gate_skip",
                    "size_quote": 0,
                    "reasons": [
                        "Pending plan trigger is not ready trigger_ready=false",
                        "Orderbook is ask-heavy",
                        "Neural shadow policy prefer_no_trade",
                    ],
                },
            }
        ],
    )
    write_jsonl(
        tmp_path / "logs/analysis.jsonl",
        [
            {
                "entry_gate": {
                    "ticker": "BTC-USDC",
                    "decision": "skip",
                    "priority": "low",
                    "setup_type": "trend_continuation",
                    "reasons": ["Higher timeframe bearish"],
                },
                "feature_pack": {"orderbook": {"spread_pct": "0.001", "best_bid": "1", "best_ask": "2"}},
            }
        ],
    )

    report = audit.build_report(
        tmp_path,
        audit.parse_time("2026-06-14T00:00:00Z"),
        tmp_path / "reports/audits/out.json",
        tmp_path / "reports/audits/out.md",
    )

    assert report["cycles"][0]["approve_trade"] == 1
    assert report["cycles"][0]["wait"] == 6
    assert report["cycles"][0]["reject"] == 1
    assert report["cycles"][0]["executed"] == 1
    btc = next(row for row in report["ticker_decisions"] if row["ticker"] == "BTC-USDC")
    assert btc["gate_decision"] == "skip"
    assert btc["final_judge_decision"] == "wait"
    assert any(b["blocker"] == "trigger_not_ready" for b in report["blockers"])
    assert any(b["blocker"] == "spread_orderbook_liquidity" for b in report["blockers"])


def test_refuses_writes_outside_reports_audits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        audit.ensure_audit_output(tmp_path / "state/bad.json", tmp_path)


def test_masks_secrets() -> None:
    assert "abc123" not in audit.mask('api_key="abc123" token: xyz')
    assert "Bearer secret" not in audit.mask("Authorization: Bearer secret")


def test_source_has_no_live_or_service_mutation_calls() -> None:
    source = Path(audit.__file__).read_text(encoding="utf-8")
    forbidden = [
        "coinbase.rest",
        "submit_order",
        "cancel_order",
        "create_order",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "dotenv.set_key",
        "set_key(",
    ]
    for needle in forbidden:
        assert needle not in source
