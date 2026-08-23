#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import build_regime_enrichment_fields
from bot.atomic_io import atomic_write_json
from bot.reflection_persistence import REFLECTION_LEDGER_PATH, load_reflection_events, read_jsonl_ledger


JSON_PATH = Path("reports/audits/regime-detection-audit-latest.json")
MD_PATH = Path("reports/audits/regime-detection-audit-latest.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _count(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    values = Counter(str(row.get(key) or "unknown").strip() or "unknown" for row in rows)
    return dict(sorted(values.items(), key=lambda item: (-item[1], item[0])))


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _stale_diagnosis(mi: Dict[str, Any]) -> Dict[str, Any]:
    expires = _parse_time(mi.get("expires_at"))
    generated = _parse_time(mi.get("generated_at"))
    now = datetime.now(timezone.utc)
    stale_by_expiry = bool(expires and expires < now)
    return {
        "market_intelligence_available": bool(mi),
        "market_intelligence_generated_at": mi.get("generated_at") or "",
        "market_intelligence_expires_at": mi.get("expires_at") or "",
        "market_intelligence_stale_flag": bool(mi.get("stale")),
        "market_intelligence_stale_by_expiry": stale_by_expiry,
        "market_intelligence_age_hours": round((now - generated).total_seconds() / 3600.0, 4) if generated else None,
    }


def build_report(*, root: Path = Path(".")) -> Dict[str, Any]:
    reflections, reflection_corrupt = load_reflection_events(root)
    pressure, pressure_corrupt = read_jsonl_ledger(root / "reports/adaptive_policy/history/parameter-pressure-events.jsonl")
    mi = _load_json(root / "state/market_intelligence_context.json")
    rows = [row for row in reflections if row.get("validated_conclusion") is True]
    enriched_preview: List[Dict[str, Any]] = []
    for row in rows:
        clone = dict(row)
        clone.update(build_regime_enrichment_fields(clone, mi, clone.get("candle_context") if isinstance(clone.get("candle_context"), dict) else {}))
        enriched_preview.append(clone)
    known_trend_vol = [row for row in enriched_preview if str(row.get("trend_regime") or "unknown") != "unknown" or str(row.get("volatility_regime") or "unknown") != "unknown"]
    adaptive_omits_candle = [
        row for row in known_trend_vol
        if "trend_" not in str(row.get("adaptive_market_regime") or "") or "volatility_" not in str(row.get("adaptive_market_regime") or "")
    ]
    return {
        "phase": "regime_detection_audit_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "can_authorize_execution": False,
        "can_mutate_parameters": False,
        "reflection_ledger_path": str(root / REFLECTION_LEDGER_PATH),
        "reflection_corrupt_lines": reflection_corrupt,
        "pressure_corrupt_lines": pressure_corrupt,
        "validated_reflection_rows": len(rows),
        "pressure_event_rows": len(pressure),
        "current_adaptive_regimes": sorted({str(row.get("adaptive_market_regime") or "unknown") for row in enriched_preview}),
        "raw_regimes": sorted({str(row.get("raw_market_regime") or row.get("market_regime") or "unknown") for row in enriched_preview}),
        "regime_sources": _count(enriched_preview, "regime_source"),
        "regime_key_designs": _count(enriched_preview, "regime_key_design"),
        "counts_by_adaptive_market_regime": _count(enriched_preview, "adaptive_market_regime"),
        "counts_by_raw_market_regime": _count(enriched_preview, "raw_market_regime"),
        "counts_by_trend_regime": _count(enriched_preview, "trend_regime"),
        "counts_by_volatility_regime": _count(enriched_preview, "volatility_regime"),
        "counts_by_liquidity_regime": _count(enriched_preview, "liquidity_regime"),
        "counts_by_network_regime": _count(enriched_preview, "network_regime"),
        "missing_feature_counts": {
            "raw_market_regime": sum(1 for row in enriched_preview if str(row.get("raw_market_regime") or "unknown") == "unknown"),
            "trend_regime": sum(1 for row in enriched_preview if str(row.get("trend_regime") or "unknown") == "unknown"),
            "volatility_regime": sum(1 for row in enriched_preview if str(row.get("volatility_regime") or "unknown") == "unknown"),
            "liquidity_regime": sum(1 for row in enriched_preview if str(row.get("liquidity_regime") or "unknown") == "unknown"),
            "network_regime": sum(1 for row in enriched_preview if str(row.get("network_regime") or "unknown") == "unknown"),
        },
        "stale_cached_input_diagnosis": _stale_diagnosis(mi),
        "candle_trend_volatility_being_ignored": bool(adaptive_omits_candle),
        "candle_context_rows_with_known_trend_or_volatility": len(known_trend_vol),
        "adaptive_rows_omitting_known_candle_context": len(adaptive_omits_candle),
        "proposed_richer_regime_key_design": "network_{network}_liquidity_{liquidity}_trend_{trend}_volatility_{volatility}",
        "proposed_design_notes": [
            "Preserve historical rows when adaptive_market_regime is already explicit.",
            "Use market-intelligence network/liquidity and candle trend/volatility together.",
            "Keep unknown trend/volatility explicit instead of silently suppressing them.",
        ],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Regime Detection Audit",
            "",
            f"Generated: {report.get('generated_at')}",
            f"Validated rows: {report.get('validated_reflection_rows')}",
            f"Adaptive regimes: {', '.join(report.get('current_adaptive_regimes') or []) or 'none'}",
            f"Candle trend/volatility ignored: {report.get('candle_trend_volatility_being_ignored')}",
            "",
            "## Missing Features",
            json.dumps(report.get("missing_feature_counts") or {}, indent=2, sort_keys=True),
            "",
            "## Counts By Adaptive Regime",
            json.dumps(report.get("counts_by_adaptive_market_regime") or {}, indent=2, sort_keys=True),
            "",
            "## Proposed Design",
            str(report.get("proposed_richer_regime_key_design")),
        ]
    ) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show read-only regime detection audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    report = build_report(root=root)
    atomic_write_json(root / JSON_PATH, report)
    (root / MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / MD_PATH).write_text(render_markdown(report), encoding="utf-8")
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
