#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from bot.strategy_engine import StrategyEngine


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _fmt_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _short_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _read_jsonl_tail(path: Path, max_lines: int = 5) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []

    return rows[-max_lines:]


def main() -> None:
    print("=== Coinbase Bot: Eenmalige Analyse Run ===")
    print(f"Starttijd: {datetime.utcnow().isoformat()}Z")

    try:
        engine = StrategyEngine()
        cfg = getattr(engine, "cfg", None)

        if cfg is not None:
            print(
                "Config: "
                f"mode={getattr(cfg, 'execution_mode', 'unknown')} | "
                f"tickers={len(getattr(cfg, 'allowed_tickers', []))} | "
                f"interval={getattr(cfg, 'primary_interval_hours', 'n/a')}h | "
                f"max_open_positions={getattr(cfg, 'max_open_positions', 'n/a')}"
            )

            if hasattr(cfg, "enable_candidate_ranking"):
                print(
                    "Flow flags: "
                    f"ranking={_fmt_bool(getattr(cfg, 'enable_candidate_ranking', False))} | "
                    f"strict_meanrev_postfilter={_fmt_bool(getattr(cfg, 'enable_strict_meanrev_postfilter', False))} | "
                    f"raw_llm_logging={_fmt_bool(getattr(cfg, 'llm_raw_logging_enabled', False))} | "
                    f"corrupt_llm_logging={_fmt_bool(getattr(cfg, 'llm_corrupt_logging_enabled', False))}"
                )

        print("Bezig met data verzamelen en LLM analyse...")
        results = engine.run_cycle()

        print("\n--- RESULTAAT (volledig JSON) ---")
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))

        print("\n--- SAMENVATTING PER TICKER ---")

        rows = _safe_list(results.get("results"))
        if not rows:
            print("Geen tickerresultaten ontvangen.")

        for res in rows:
            if not isinstance(res, dict):
                print(f"\nOnverwacht result-type: {res!r}")
                continue

            ticker = res.get("ticker", "Unknown")

            if "error" in res:
                print(f"\nFOUT bij ticker {ticker}: {res['error']}")
                continue

            analysis = _safe_dict(res.get("analysis"))
            execution = _safe_dict(res.get("execution"))
            position_execution = _safe_dict(res.get("position_execution"))
            entry_gate = _safe_dict(res.get("entry_gate"))
            deepseek_pack = _safe_dict(res.get("deepseek_pack"))
            synthesis = _safe_dict(res.get("synthesis"))

            active_exec = execution if execution else position_execution

            decision = analysis.get("decision", "unknown")
            confidence = analysis.get("confidence", 0)
            strategy = analysis.get("strategy", "unknown")
            setup_type = (
                entry_gate.get("setup_type")
                or analysis.get("setup_type")
                or synthesis.get("setup_type")
                or "unknown"
            )
            gate_decision = entry_gate.get("decision", "n/a")
            gate_priority = entry_gate.get("priority", "n/a")
            exec_status = active_exec.get("status", "none")
            executed = active_exec.get("executed", False)
            side = analysis.get("side", "NONE")
            size_quote = analysis.get("size_quote", 0)

            print(
                f"\nTicker={ticker} | gate={gate_decision}/{gate_priority} | "
                f"decision={decision} | side={side} | size_quote={size_quote} | "
                f"confidence={confidence} | strategy={strategy} | setup_type={setup_type} | "
                f"execution_status={exec_status} | executed={executed}"
            )

            gate_reasons = _safe_list(entry_gate.get("reasons"))
            if gate_reasons:
                print("  Gate reasons:")
                for reason in gate_reasons[:3]:
                    print(f"    - {_short_text(reason)}")

            analysis_reasons = _safe_list(analysis.get("reasons"))
            if analysis_reasons:
                print("  Judge reasons:")
                for reason in analysis_reasons[:4]:
                    print(f"    - {_short_text(reason)}")

            must_reject_if = _safe_list(analysis.get("must_reject_if"))
            if must_reject_if:
                print("  Reject if:")
                for item in must_reject_if[:3]:
                    print(f"    - {_short_text(item)}")

            warnings = _safe_list(entry_gate.get("warnings"))
            if warnings:
                print("  Gate warnings:")
                for warning in warnings[:3]:
                    print(f"    - {_short_text(warning)}")

            if deepseek_pack.get("fallback"):
                print(
                    "  DeepSeek preprocess fallback: "
                    f"{_short_text(deepseek_pack.get('fallback_reason', 'unknown'))}"
                )

            corrupt_markers: List[str] = []

            for key in ("regime", "trend", "breakout", "meanrev", "bull", "bear", "synth"):
                payload = _safe_dict(res.get(key))
                if payload.get("fallback"):
                    corrupt_markers.append(
                        f"{key} fallback: {_short_text(payload.get('fallback_reason', 'unknown'))}"
                    )

            if corrupt_markers:
                print("  Module fallbacks / mogelijke output-corruptie:")
                for marker in corrupt_markers[:6]:
                    print(f"    - {marker}")

            if active_exec:
                exec_reason = active_exec.get("reason") or active_exec.get("details")
                if exec_reason:
                    print(f"  Execution note: {_short_text(exec_reason)}")

        print("\n--- RUN SAMENVATTING ---")
        total = 0
        errors = 0
        approved = 0
        waited = 0
        rejected = 0
        gate_priority = 0
        gate_analyze = 0
        gate_watch = 0
        gate_skip = 0
        executed_count = 0
        fallback_hits = 0

        for res in rows:
            if not isinstance(res, dict):
                continue
            total += 1

            if "error" in res:
                errors += 1
                continue

            analysis = _safe_dict(res.get("analysis"))
            entry_gate = _safe_dict(res.get("entry_gate"))
            execution = _safe_dict(res.get("execution"))
            position_execution = _safe_dict(res.get("position_execution"))
            deepseek_pack = _safe_dict(res.get("deepseek_pack"))

            active_exec = execution if execution else position_execution

            gate_decision = str(entry_gate.get("decision", "")).lower()
            decision = str(analysis.get("decision", "")).lower()

            if gate_decision == "priority_analyze":
                gate_priority += 1
            elif gate_decision == "analyze":
                gate_analyze += 1
            elif gate_decision == "watch":
                gate_watch += 1
            elif gate_decision == "skip":
                gate_skip += 1

            if decision == "approve_trade":
                approved += 1
            elif decision == "wait":
                waited += 1
            elif decision == "reject":
                rejected += 1

            if active_exec.get("executed"):
                executed_count += 1

            if deepseek_pack.get("fallback"):
                fallback_hits += 1

            for key in ("regime", "trend", "breakout", "meanrev", "bull", "bear", "synth"):
                payload = _safe_dict(res.get(key))
                if payload.get("fallback"):
                    fallback_hits += 1

        print(
            f"Total={total} | errors={errors} | approve_trade={approved} | "
            f"wait={waited} | reject={rejected} | executed={executed_count}"
        )
        print(
            f"Gate: priority_analyze={gate_priority} | analyze={gate_analyze} | "
            f"watch={gate_watch} | skip={gate_skip}"
        )
        print(f"Fallback/module-corruptie signalen={fallback_hits}")

        logs_dir = Path("logs")
        llm_corrupt_tail = _read_jsonl_tail(logs_dir / "llm_corrupt.jsonl", max_lines=5)
        errors_tail = _read_jsonl_tail(logs_dir / "errors.jsonl", max_lines=5)

        if llm_corrupt_tail:
            print("\n--- RECENTE llm_corrupt.jsonl ITEMS ---")
            for row in llm_corrupt_tail:
                print(
                    f"- provider={row.get('provider', '?')} | model={row.get('model', '?')} | "
                    f"ticker={row.get('ticker', '?')} | stage={row.get('stage', '?')} | "
                    f"error={_short_text(row.get('error', ''), 180)}"
                )

        if errors_tail:
            print("\n--- RECENTE errors.jsonl ITEMS ---")
            for row in errors_tail:
                print(
                    f"- ticker={row.get('ticker', '?')} | module={row.get('module', '?')} | "
                    f"error_type={row.get('error_type', '?')} | "
                    f"error={_short_text(row.get('error', ''), 180)}"
                )

        print("\nAnalyse klaar.")

    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()