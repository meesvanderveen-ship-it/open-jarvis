#!/usr/bin/env python3
"""Show the read-only GrowBot/River parameter-learning status."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import CANDIDATE_JSON_PATH
from bot.parameter_candidate_analysis import ANALYSIS_JSON_PATH
from bot.growbot_river_readiness import READINESS_PATH
from bot.river_online_parameter_learner import MODEL_STATE_PATH


REPORT_PATH = Path("reports/growbot_river/growbot-river-learning-latest.json")


def _load(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _per_parameter_diagnostics(river: Dict[str, Any]) -> list:
    """Rich per-parameter candidate scoring: every field the ranking actually uses."""
    signals = river.get("parameter_signals") if isinstance(river.get("parameter_signals"), list) else []
    diagnostics = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        diagnostics.append({
            "parameter": signal.get("parameter"),
            "direction": signal.get("direction"),
            "confidence": signal.get("confidence"),
            "evidence_count": signal.get("evidence_count"),
            "expected_reward": signal.get("expected_reward"),
            "good_trade_probability": signal.get("good_trade_probability"),
            "bad_trade_probability": signal.get("bad_trade_probability"),
            "missed_opportunity_probability": signal.get("missed_opportunity_probability"),
            "river_expected_reward": signal.get("river_expected_reward"),
            "river_good_trade_probability": signal.get("river_good_trade_probability"),
            "candidate_ranking_score": signal.get("candidate_ranking_score"),
            "dominant_regime": signal.get("dominant_regime"),
            "regime_effect_direction": signal.get("regime_effect_direction"),
            "regime_drift_hint": signal.get("regime_drift_hint"),
            "activation_route": signal.get("activation_route"),
            "safe_to_activate_now": signal.get("safe_to_activate_now"),
        })
    return diagnostics


def _per_regime_diagnostics(river: Dict[str, Any], river_state: Dict[str, Any]) -> Dict[str, Any]:
    """Per-regime reward/drift diagnostics, independent of any single parameter."""
    regime_drift = river.get("regime_drift") if isinstance(river.get("regime_drift"), dict) else {}
    deterministic = regime_drift.get("deterministic_summary") if isinstance(regime_drift.get("deterministic_summary"), dict) else {}
    if not deterministic:
        deterministic = river_state.get("regime_drift") if isinstance(river_state.get("regime_drift"), dict) else {}
    by_regime = deterministic.get("by_regime") if isinstance(deterministic.get("by_regime"), dict) else {}
    return {
        "distinct_regime_count": deterministic.get("distinct_regime_count", len(by_regime)),
        "global_drift_detected": deterministic.get("drift_detected", False),
        "by_regime": by_regime,
    }


def _river_dependency_status(river: Dict[str, Any]) -> Dict[str, Any]:
    """Whether River is genuinely unavailable, and why, for an operator dashboard.

    A successful `pip show river` does not guarantee `_import_river()`
    succeeds: river 0.23.0's own PyPI metadata omits `typing_extensions`,
    which `river.base.base` imports directly, so an incomplete dependency
    resolution fails *inside* the try/except and is reported here verbatim
    instead of only as the generic `river_native_sidecar_unavailable` blocker.
    """
    backend = river.get("backend") if isinstance(river.get("backend"), dict) else {}
    available = bool(backend.get("river_available"))
    return {
        "available": available,
        "backend": backend.get("backend") or "not_run",
        "import_error_detail": backend.get("import_error_detail") or "",
        "model_persistence": backend.get("model_persistence") or {},
        "fallback_backend_sufficient_for_report_only_use": True,
        "safe_install_route": [
            "python3 -m venv /opt/coinbase-river-sidecar",
            "/opt/coinbase-river-sidecar/bin/pip install -r requirements-river-sidecar.txt",
            "PYTHONPATH=$(pwd) /opt/coinbase-river-sidecar/bin/python tools/run_growbot_river_learning_cycle.py --json",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show report-only GrowBot/River learning status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    report = _load(root / REPORT_PATH)
    river_state = _load(root / MODEL_STATE_PATH)
    candidate = _load(root / CANDIDATE_JSON_PATH)
    analysis = _load(root / ANALYSIS_JSON_PATH)
    readiness = _load(root / READINESS_PATH)
    river = report.get("river") if isinstance(report.get("river"), dict) else {}
    processing = river.get("processing") if isinstance(river.get("processing"), dict) else {}
    phase = report.get("phase_decision") if isinstance(report.get("phase_decision"), dict) else {}
    safety = report.get("safety_policy") if isinstance(report.get("safety_policy"), dict) else {}
    status = {
        "available": bool(report),
        "generated_at": report.get("generated_at") or "",
        "phase": phase.get("phase") or "not_run",
        "episode_count": ((report.get("episode_report") or {}).get("summary") or {}).get("episode_count", 0),
        "memory_total": ((report.get("episode_report") or {}).get("memory") or {}).get("total_after", 0),
        "new_memory_episodes": ((report.get("episode_report") or {}).get("memory") or {}).get("added", 0),
        "episode_identity": ((report.get("episode_report") or {}).get("episode_identity") or {}),
        "regime_evidence": ((report.get("episode_report") or {}).get("summary") or {}).get("regime_evidence", {}),
        "learning_data_contract": ((report.get("episode_report") or {}).get("learning_data_contract") or {}),
        "growbot_open_source": report.get("growbot_open_source") or {},
        "product_readiness": readiness.get("readiness") or {},
        "product_readiness_blockers": readiness.get("blockers") or [],
        "river_backend": ((river.get("backend") or {}).get("backend") or "not_run"),
        "river_available": bool((river.get("backend") or {}).get("river_available")),
        "river_model_persistence": ((river.get("backend") or {}).get("model_persistence") or {}),
        "river_newly_processed": processing.get("newly_processed", 0),
        "river_replayed_for_contract_migration": bool(
            processing.get("model_state_rebuilt_for_episode_identity")
            or processing.get("model_state_rebuilt_for_regime_context")
        ),
        "river_already_processed": processing.get("already_processed", 0),
        "regime_drift": river.get("regime_drift") or river_state.get("regime_drift") or {},
        "proposal_count": len(report.get("proposals") or []),
        "blocked_proposal_count": len(report.get("blocked_proposals") or []),
        "top_proposals": (report.get("proposals") or [])[:5],
        "adaptive_policy_candidate_available": bool(candidate.get("candidate_available")),
        "parameter_candidate_analysis_available": bool(analysis.get("parameter_analysis_available")),
        "governor_invoked": False,
        "approved_profile_mutated": False,
        "execution_authority": bool(safety.get("execution_authority")),
        "parameter_mutation_allowed": bool(safety.get("parameter_mutation_allowed")),
        "C43_D3_bypass_allowed": bool(safety.get("C43_D3_bypass_allowed")),
        "per_parameter_diagnostics": _per_parameter_diagnostics(river),
        "per_regime_diagnostics": _per_regime_diagnostics(river, river_state),
        "river_dependency_status": _river_dependency_status(river),
        "stabilization_readiness": readiness.get("stabilization_readiness") or {},
        "next_operator_action": "review report-only proposals; use the existing adaptive/governor/hash-ACK route for any future activation",
    }
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(
            "growbot_river "
            f"available={status['available']} phase={status['phase']} "
            f"episodes={status['episode_count']} proposals={status['proposal_count']} "
            f"candidate_available={status['adaptive_policy_candidate_available']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
