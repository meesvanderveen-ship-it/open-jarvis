from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.config import configured_ticker_universe, effective_phase_c_allowed_tickers
from bot.product_rules import canonical_product_rules, load_product_rules_cache, normalize_product_id


CONTROLLED_CLOSE_REPAIR_TICKERS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
ADA_REVIEW_TICKERS = ["ADA-USDC"]


def _normalize_tickers(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        ticker = normalize_product_id(value)
        if not ticker or "-" not in ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


def load_product_rules_for_readiness(root: Path | str = ".") -> Dict[str, Dict[str, Any]]:
    root_path = Path(root)
    for relative in (
        Path("reports/audits/per-ticker-product-rule-evidence-cache-latest.json"),
        Path("reports/d6/per-ticker-product-rule-evidence-cache-20260609.json"),
        Path("reports/d6/product-rule-fixture-evidence-20260609.json"),
    ):
        rules = load_product_rules_cache(root_path / relative)
        if rules:
            return rules
    return {}


def build_env_ticker_universe_workflow_readiness(
    *,
    cfg: Any,
    product_rules_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    configured = _normalize_tickers(configured_ticker_universe(cfg))
    allowed = set(_normalize_tickers(getattr(cfg, "allowed_tickers", []) or []))
    effective_phase_c = set(_normalize_tickers(effective_phase_c_allowed_tickers(cfg)))
    raw_phase_c = _normalize_tickers(getattr(cfg, "phase_c_allowed_tickers", []) or [])
    autonomous = _normalize_tickers(getattr(cfg, "autonomous_allowed_tickers", []) or [])
    rules_by_ticker = product_rules_by_ticker if isinstance(product_rules_by_ticker, dict) else load_product_rules_cache()

    eligible: List[str] = []
    blocked: Dict[str, List[str]] = {}
    for ticker in configured:
        reasons: List[str] = []
        if ticker not in allowed:
            reasons.append("ticker_not_in_allowed_tickers")
        if ticker not in effective_phase_c:
            reasons.append("ticker_not_in_effective_phase_c_allowed_tickers")

        rules = rules_by_ticker.get(ticker) or {}
        product_rules = canonical_product_rules(ticker, rules)
        if not product_rules.get("raw_rules_present"):
            reasons.append("product_rules_missing")
        elif not product_rules.get("precision_context_available"):
            reasons.append("product_precision_context_missing")

        if reasons:
            blocked[ticker] = list(dict.fromkeys(reasons))
        else:
            eligible.append(ticker)

    return {
        "normal_workflow_uses_env_ticker_universe": bool(configured),
        "hardcoded_incident_ticker_scope_removed_from_normal_workflow": configured != CONTROLLED_CLOSE_REPAIR_TICKERS,
        "controlled_close_scope_isolated": True,
        "ada_review_scope_isolated": True,
        "configured_tickers": configured,
        "allowed_tickers": sorted(allowed),
        "phase_c_allowed_tickers": raw_phase_c,
        "autonomous_allowed_tickers": autonomous,
        "effective_phase_c_allowed_tickers": sorted(effective_phase_c),
        "eligible_tickers": eligible,
        "blocked_tickers": blocked,
        "unsupported_tickers_blocked_with_reasons": bool(blocked) or bool(configured),
        "controlled_close_repair_tickers": list(CONTROLLED_CLOSE_REPAIR_TICKERS),
        "ada_review_tickers": list(ADA_REVIEW_TICKERS),
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submit_attempted": False,
        "live_order_submitted": False,
        "state_write_performed": False,
    }


__all__ = [
    "ADA_REVIEW_TICKERS",
    "CONTROLLED_CLOSE_REPAIR_TICKERS",
    "build_env_ticker_universe_workflow_readiness",
    "load_product_rules_for_readiness",
]
