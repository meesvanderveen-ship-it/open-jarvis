"""Parameter Proposal Board data: merges three already-vetted read-only
sources into one row per parameter. Never writes anything, never calls
`autonomous_parameter_governor.run_governor(apply=True)` — that function is
not imported anywhere in this dashboard.

Sources:
- `approved_parameter_profile.parameters` (via the live-status tool): the
  current, operator-approved values actually loaded by BotConfig.
- `per_parameter_diagnostics` (GrowBot/River): confidence/evidence/direction
  signal per learnable parameter.
- `top_proposals` (GrowBot/River): the richer record for whichever
  parameter is currently the top candidate (reason, blockers, rollback
  steps, candidate value, regimes seen).
"""

from __future__ import annotations

from dashboard.backend.services.learning_status import get_learning_status
from dashboard.backend.services.live_status import get_live_status
from dashboard.backend.services.util import dig

_CATEGORY_PREFIXES = [
    ("PHASE_D2", "D2 planner / exit economics"),
    ("PHASE_D3", "D3 controlled exit"),
    ("PHASE_C", "C4.3 entry"),
    ("SMALL_PROBE", "Small-probe promotion gate"),
    ("JUDGE", "Judge / confidence gate"),
    ("MAX_SPREAD", "Liquidity guard"),
    ("AUTONOMOUS_MAX", "Autonomy caps"),
    ("MAX_OPEN", "Exposure caps"),
    ("MAX_NOTIONAL", "Exposure caps"),
    ("DEFAULT_QUOTE_SIZE", "Sizing"),
    ("EXIT_TARGET", "D3 controlled exit"),
]


def _category_for(parameter: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if parameter.startswith(prefix):
            return category
    return "Other"


def _clean_regimes(regimes: list | None) -> list[str]:
    if not regimes:
        return []
    cleaned = []
    seen = set()
    for r in regimes:
        if not isinstance(r, str) or "{" in r or len(r) > 60:
            continue
        if r not in seen:
            seen.add(r)
            cleaned.append(r)
    return cleaned[:10]


def get_parameter_proposals() -> dict:
    live = get_live_status()
    learning = get_learning_status()

    approved_params: dict = dig(live, "approved_profile_status.parameters", {}) or {}
    diagnostics: list = learning.get("per_parameter_diagnostics") or []
    top_proposals: list = learning.get("top_proposals") or []

    diagnostics_by_param = {d.get("parameter"): d for d in diagnostics if d.get("parameter")}
    top_by_param = {p.get("parameter"): p for p in top_proposals if p.get("parameter")}

    all_param_names = set(approved_params) | set(diagnostics_by_param) | set(top_by_param)

    rows = []
    for parameter in sorted(all_param_names):
        diag = diagnostics_by_param.get(parameter, {})
        top = top_by_param.get(parameter, {})
        current_value = approved_params.get(parameter, top.get("current_value"))
        has_active_signal = bool(diag) or bool(top)
        blockers = top.get("blockers") or []
        safe_now = top.get("safe_to_activate_now")

        if not has_active_signal:
            safety_status = "no_active_proposal"
            apply_status = "no_active_proposal"
        elif blockers:
            safety_status = "blocked"
            apply_status = "blocked"
        elif safe_now:
            safety_status = "safe_to_activate"
            apply_status = "ready_for_review"
        else:
            safety_status = "needs_more_evidence"
            apply_status = "preview_only"

        rows.append(
            {
                "parameter": parameter,
                "category": _category_for(parameter),
                "current_value": current_value,
                "proposed_value": top.get("candidate_value"),
                "direction": top.get("direction") or diag.get("direction") or "keep",
                "reason": top.get("reason"),
                "confidence": diag.get("confidence") or top.get("confidence"),
                "evidence_count": diag.get("evidence_count") or top.get("evidence_count"),
                "regimes_seen": _clean_regimes(top.get("regimes")) or (
                    [diag["dominant_regime"]] if diag.get("dominant_regime") else []
                ),
                "expected_effect": {
                    "expected_reward": diag.get("expected_reward"),
                    "good_trade_probability": diag.get("good_trade_probability"),
                    "bad_trade_probability": diag.get("bad_trade_probability"),
                    "missed_opportunity_probability": diag.get("missed_opportunity_probability"),
                },
                "risk_impact": diag.get("regime_effect_direction"),
                "safety_status": safety_status,
                "apply_status": apply_status,
                "rollback_plan": top.get("rollback") or [],
                "source": "growbot_river" if has_active_signal else "approved_profile",
                "blockers": blockers,
                "operator_ack_needed": bool(top.get("requires_operator_review", has_active_signal)),
                "activation_route": top.get("activation_route") or diag.get("activation_route"),
            }
        )

    return {
        "generated_at": learning.get("generated_at"),
        "proposals": rows,
        "product_readiness": learning.get("product_readiness"),
        "product_readiness_blockers": learning.get("product_readiness_blockers"),
        "next_operator_action": learning.get("next_operator_action"),
        "proposal_count": learning.get("proposal_count"),
        "blocked_proposal_count": learning.get("blocked_proposal_count"),
    }
