from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.show_phase_b_final_report import build_final_report


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _force_phase_b_paper_only_env(monkeypatch) -> None:
    """Keep legacy B.8 tests isolated from current Phase-C/autonomous live env flags."""
    # BotConfig laadt op productiehosts bewust projectroot .env met override=True.
    # Voor deze legacy B.8 paper-only tests moet de echte server-.env echter
    # geen invloed hebben op de geïsoleerde tmp_path state.
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    # BotConfig requires OPENAI_API_KEY even in paper-only status tests.
    # Use a dummy value so this legacy B.8 test remains independent from
    # the real project .env while still exercising normal config validation.
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_READ_ONLY_EXECUTION_PLANNER", "true")
    monkeypatch.setenv("ENABLE_LIMIT_ORDER_MANAGER", "true")
    monkeypatch.setenv("ENABLE_LIVE_LIMIT_ORDERS", "false")
    monkeypatch.setenv("ENABLE_LIVE_ENTRY_ORDERS", "false")
    monkeypatch.setenv("ENABLE_LIVE_EXIT_ORDERS", "false")
    monkeypatch.setenv("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS", "false")
    monkeypatch.setenv("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT", "false")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE", "false")
    monkeypatch.setenv("ENABLE_PHASE_C43_AUTONOMOUS_ENTRY_SUBMITTER", "false")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "")


def test_phase_b8_report_keeps_replaced_intents_out_of_promotion_lists(tmp_path: Path, monkeypatch) -> None:
    _force_phase_b_paper_only_env(monkeypatch)

    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(
        tmp_path / "state/pending_order_intents.json",
        {
            "intents": {
                "old": {
                    "intent_id": "old",
                    "ticker": "BTC-USDC",
                    "status": "replaced",
                    "source_kind": "gate_watch_order_intent",
                    "last_evaluation": {
                        "trigger_ready": True,
                        "reason": "old_ready",
                        "current_price": "100",
                    },
                },
                "new": {
                    "intent_id": "new",
                    "ticker": "ETH-USDC",
                    "status": "needs_fresh_analysis",
                    "source_kind": "gate_watch_order_intent",
                    "last_evaluation": {
                        "trigger_ready": True,
                        "reason": "fresh_required",
                        "current_price": "200",
                    },
                },
            }
        },
    )
    _write_jsonl(tmp_path / "logs/execution_outcomes.jsonl", [])
    _write_jsonl(tmp_path / "logs/execution_plans.jsonl", [])
    _write_jsonl(tmp_path / "logs/errors.jsonl", [])
    _write_jsonl(tmp_path / "logs/llm_corrupt.jsonl", [])
    _write_jsonl(tmp_path / "logs/pending_order_intents.jsonl", [])
    _write_jsonl(tmp_path / "logs/replication_outbox.jsonl", [])

    args = argparse.Namespace(
        project_root=str(tmp_path),
        open_orders_path="state/open_orders.json",
        pending_intents_path="state/pending_order_intents.json",
        execution_outcomes_path="logs/execution_outcomes.jsonl",
        execution_plans_path="logs/execution_plans.jsonl",
        logs_dir="logs",
        limit=50,
        include_source_hygiene=False,
    )
    report = build_final_report(args)
    pending = report["status"]["pending_order_intents"]

    assert report["phase_b_safe_to_continue_paper_only"] is True
    assert pending["trigger_ready"] == []
    assert pending["needs_fresh_analysis"] == ["ETH-USDC"]
    assert pending["promotion_ready"] == ["ETH-USDC"]
    assert report["phase_c_ready_without_human_review"] is False


def test_phase_b8_report_flags_source_hygiene_without_printing_secret_values(tmp_path: Path, monkeypatch) -> None:
    _force_phase_b_paper_only_env(monkeypatch)

    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(tmp_path / "state/pending_order_intents.json", {"intents": {}})
    _write_jsonl(tmp_path / "logs/execution_outcomes.jsonl", [])
    _write_jsonl(tmp_path / "logs/execution_plans.jsonl", [])
    _write_jsonl(tmp_path / "logs/errors.jsonl", [])
    _write_jsonl(tmp_path / "logs/llm_corrupt.jsonl", [])
    _write_jsonl(tmp_path / "logs/pending_order_intents.jsonl", [])
    _write_jsonl(tmp_path / "logs/replication_outbox.jsonl", [])
    (tmp_path / ".env").write_text("SECRET_DO_NOT_PRINT=abc123", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".git").mkdir()

    args = argparse.Namespace(
        project_root=str(tmp_path),
        open_orders_path="state/open_orders.json",
        pending_intents_path="state/pending_order_intents.json",
        execution_outcomes_path="logs/execution_outcomes.jsonl",
        execution_plans_path="logs/execution_plans.jsonl",
        logs_dir="logs",
        limit=50,
        include_source_hygiene=True,
    )
    report = build_final_report(args)
    rendered = json.dumps(report, ensure_ascii=False)

    assert ".env" in report["source_hygiene"]["findings"]["env_files"]
    assert "SECRET_DO_NOT_PRINT" not in rendered
    assert "abc123" not in rendered
    assert report["warnings"]
