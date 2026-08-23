from __future__ import annotations

import json
from pathlib import Path

from tools.show_runtime_guard_version import build_runtime_guard_version_report


PROFILE = {
    "profile_name": "fee_aware_default_quote_50_bounded_v1",
    "profile_version": 1,
    "parameters": {
        "DEFAULT_QUOTE_SIZE_USDC": "50.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "MAX_NOTIONAL_USD": "100.00",
    },
}


def _write_profile(root: Path) -> None:
    path = root / "state" / "approved_parameter_profile.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(PROFILE), encoding="utf-8")


def test_runtime_guard_version_report_is_prepared_without_restart(tmp_path: Path):
    _write_profile(tmp_path)

    report = build_runtime_guard_version_report(root=tmp_path)

    assert report["live_entry_guard_version"] == "wait-preview-block-v1"
    assert report["product_rule_normalizer_version"] == "product-rules-v1"
    assert report["approved_profile_effective_default_quote"] == "50.00"
    assert report["runtime_proof_prepared"] is True
    assert report["latest_journal_versions_seen"] is False
    assert report["safe_runtime_loaded"] is False
    assert report["restart_required_to_observe_runtime_log"] is True


def test_runtime_guard_version_report_recognizes_matching_journal(tmp_path: Path):
    _write_profile(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.joinpath("runtime_guard_version.jsonl").write_text(
        json.dumps({
            "live_entry_guard_version": "wait-preview-block-v1",
            "product_rule_normalizer_version": "product-rules-v1",
            "approved_profile_effective_default_quote": "50.00",
            "live_entry_required_gates": [
                "fresh_approve_trade",
                "buy",
                "valid_trade_plan",
                "product_rules",
                "precision_normalized",
            ],
        }) + "\n",
        encoding="utf-8",
    )

    report = build_runtime_guard_version_report(root=tmp_path)

    assert report["latest_journal_versions_seen"] is True
    assert report["safe_runtime_loaded"] is True


def test_runtime_guard_version_context_contains_startup_and_full_cycle_markers():
    source = Path("run_trader_loop.py").read_text(encoding="utf-8")

    assert "LIVE_ENTRY_GUARD_VERSION=%s" in source
    assert "PRODUCT_RULE_NORMALIZER_VERSION=%s" in source
    assert "APPROVED_PROFILE_EFFECTIVE_DEFAULT_QUOTE=%s" in source
    assert "LIVE_ENTRY_REQUIRED_GATES=%s" in source
    assert '_log_runtime_guard_version_context(cfg, source="startup")' in source
    assert '_log_runtime_guard_version_context(cfg, source="full_cycle")' in source
