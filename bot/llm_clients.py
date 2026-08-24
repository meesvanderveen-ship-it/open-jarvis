from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised when optional SDK is absent
    OpenAI = None

try:
    import anthropic
except Exception:  # pragma: no cover - exercised when optional SDK is absent
    anthropic = None

from bot.llm_cost_ledger import record_llm_call


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


BENIGN_UNKNOWN_KEYS = {
    "reasoning",
    "analysis",
    "thoughts",
    "notes",
    "note",
    "commentary",
    "rationale",
    "explanation",
}


class LLMOutputCorruptError(ValueError):
    pass


class LLMProviderUnavailableError(RuntimeError):
    pass


FINAL_JUDGE_REQUIRED_KEYS = [
    "decision",
    "side",
    "confidence",
    "strategy",
    "setup_type",
    "objective_score",
    "expected_edge_score",
    "risk_penalty",
    "cost_penalty",
    "drawdown_risk",
    "execution_friction_penalty",
    "valid_trade_plan",
    "plan_type",
    "judge_reasons",
    "must_reject_if",
]

FINAL_JUDGE_OPTIONAL_ORDERBOOK_ENTRY_KEYS = [
    "setup_quality_score",
    "trigger_readiness",
    "orderbook_entry_candidate",
    "recommended_entry_type",
    "entry_zone_low",
    "entry_zone_high",
    "preferred_limit_price",
    "invalidation_price",
    "target_price_1",
    "target_price_2",
    "do_not_chase_above",
    "cancel_if_price_below",
    "cancel_if_price_above",
    "setup_expiry_minutes",
    "entry_reason",
    "why_not_market_order",
    "why_resting_limit_is_or_is_not_valid",
]

FINAL_JUDGE_SCHEMA_ALIASES = {
    "edge": "expected_edge_score",
    "risk": "risk_penalty",
    "cost": "cost_penalty",
    "drawdown": "drawdown_risk",
    "friction": "execution_friction_penalty",
    "objective": "objective_score",
}


def _cfg_bool(cfg: Any, name: str, default: bool = True) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        value = int(getattr(cfg, name, default))
        return value if value > 0 else default
    except Exception:
        return default


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    text = text or ""
    original_len = len(text)
    if max_chars <= 0 or original_len <= max_chars:
        return text, False, original_len
    half = max(1, max_chars // 2)
    head = text[:half]
    tail = text[-half:]
    marker = f"\n... [truncated {original_len - (len(head) + len(tail))} chars] ...\n"
    return head + marker + tail, True, original_len




def _cfg_float(cfg: Any, name: str, default: float) -> float:
    try:
        value = float(getattr(cfg, name, default))
        return value if value >= 0 else default
    except Exception:
        return default


def _dedupe_repeated_fragments(text: str, *, max_repeats: int = 3) -> tuple[str, bool, int]:
    """Collapse repeated semicolon/newline separated fragments in noisy LLM context/log text.

    D.3.2 hardening: the previous version only collapsed longer fragments. Real
    market context often repeats short indicator clauses such as ``1h ADX 30`` or
    ``1h bb_upper 10.828`` hundreds of times. This helper now collapses exact
    repeated clauses from eight normalized characters onward while preserving the
    first occurrences in order. It never changes numbers inside retained clauses.
    """
    text = text or ""
    if not text.strip():
        return text, False, 0

    max_repeats = max(1, int(max_repeats))
    parts = re.split(r"(;\s*|\n+)", text)
    out: list[str] = []
    seen: dict[str, int] = {}
    collapsed = 0

    # Recombine as fragment+separator pairs, preserving separators as much as possible.
    i = 0
    while i < len(parts):
        fragment = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        key = re.sub(r"\s+", " ", fragment.strip().lower())
        # Ignore tiny punctuation/noise fragments, but collapse repeated indicator
        # clauses aggressively enough for pre-live LLM stability.
        if len(key) < 8:
            out.append(fragment + sep)
        else:
            count = seen.get(key, 0)
            if count < max_repeats:
                out.append(fragment + sep)
            else:
                collapsed += 1
            seen[key] = count + 1
        i += 2

    if collapsed:
        out.append(f"\n... [deduplicated {collapsed} repeated fragments] ...\n")
    return "".join(out), bool(collapsed), collapsed


def _compact_text_for_llm_hygiene(text: str, cfg: Any | None = None, *, for_payload: bool = False) -> tuple[str, Dict[str, Any]]:
    """Deduplicate and truncate noisy text before LLM calls or log writes."""
    original = text or ""
    enabled = True if cfg is None else _cfg_bool(cfg, "llm_context_hygiene_enabled", True)
    max_repeats = _cfg_int(cfg, "llm_repeated_fragment_max_repeats", 3) if cfg is not None else 3
    max_chars_default = 60000 if for_payload else 12000
    max_chars = _cfg_int(cfg, "llm_payload_string_max_chars", max_chars_default) if (cfg is not None and for_payload) else max_chars_default

    compacted = original
    deduped = False
    deduped_count = 0
    if enabled:
        compacted, deduped, deduped_count = _dedupe_repeated_fragments(compacted, max_repeats=max_repeats)

    compacted, truncated, original_chars_after_dedupe = _truncate_text(compacted, max_chars)
    return compacted, {
        "hygiene_enabled": enabled,
        "deduplicated": deduped,
        "deduplicated_fragments": deduped_count,
        "truncated": truncated,
        "original_chars": len(original),
        "chars_after_dedupe": original_chars_after_dedupe,
        "final_chars": len(compacted),
    }


def compact_payload_for_llm(payload: Any, cfg: Any | None = None, *, _depth: int = 0) -> Any:
    """Return a payload copy with repeated/huge strings compacted for provider stability.

    It does not remove keys or change numeric values. It only rewrites string values
    when they are very long or contain repeated semicolon/newline fragments.
    """
    enabled = True if cfg is None else _cfg_bool(cfg, "llm_context_hygiene_enabled", True)
    if not enabled:
        return payload
    max_depth = _cfg_int(cfg, "llm_payload_hygiene_max_depth", 8) if cfg is not None else 8
    if _depth > max_depth:
        return payload
    if isinstance(payload, str):
        compacted, _ = _compact_text_for_llm_hygiene(payload, cfg, for_payload=True)
        return compacted
    if isinstance(payload, dict):
        return {k: compact_payload_for_llm(v, cfg, _depth=_depth + 1) for k, v in payload.items()}
    if isinstance(payload, list):
        return [compact_payload_for_llm(v, cfg, _depth=_depth + 1) for v in payload]
    if isinstance(payload, tuple):
        return [compact_payload_for_llm(v, cfg, _depth=_depth + 1) for v in payload]
    return payload

def _provider_error_type(error: BaseException | str) -> str | None:
    msg = str(error).lower()
    if any(token in msg for token in (
        "connection error",
        "connecterror",
        "temporary failure in name resolution",
        "name or service not known",
        "dns",
        "nodename nor servname provided",
        "network is unreachable",
        "connection refused",
        "connection reset",
        "remote protocol error",
    )):
        return "provider_network_or_connection_error"
    if any(token in msg for token in (
        "invalid api key",
        "incorrect api key",
        "unauthorized",
        "401",
    )):
        return "provider_auth_error"
    if any(token in msg for token in (
        "model_not_found",
        "model not found",
        "does not exist",
        "invalid model",
    )):
        return "provider_model_error"
    if any(token in msg for token in (
        "credit balance is too low",
        "insufficient credits",
        "billing",
        "quota",
        "payment required",
        "rate_limit",
        "overloaded_error",
        "service unavailable",
    )):
        if any(token in msg for token in ("credit balance", "insufficient credits", "billing", "payment required")):
            return "provider_billing_or_credit_error"
        if "rate_limit" in msg or "quota" in msg:
            return "provider_rate_limit_or_quota_error"
        if "overloaded" in msg or "service unavailable" in msg:
            return "provider_unavailable_or_overloaded"
    return None


def _record_llm_cost(
    *,
    provider: str,
    model: str,
    ticker: str,
    stage: str,
    attempt: int,
    usage: Any,
    latency_ms: float,
    call_outcome: str,
    decision_result: Optional[str] = None,
    error_type: Optional[str] = None,
    cfg: Any | None = None,
) -> None:
    """Best-effort cost-ledger write. Never raises -- see bot/llm_cost_ledger.py."""
    try:
        input_tokens = None
        output_tokens = None
        cached_tokens = None
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            if input_tokens is None:
                input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            if output_tokens is None:
                output_tokens = getattr(usage, "completion_tokens", None)
            input_tokens_details = getattr(usage, "input_tokens_details", None)
            if input_tokens_details is None:
                input_tokens_details = getattr(usage, "prompt_tokens_details", None)
            if input_tokens_details is not None:
                cached_tokens = getattr(input_tokens_details, "cached_tokens", None)
        record_llm_call(
            provider=provider,
            model=model,
            ticker=ticker,
            stage=stage,
            attempt=attempt,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            latency_ms=latency_ms,
            call_outcome=call_outcome,
            error_type=error_type,
            decision_result=decision_result,
            cfg=cfg,
        )
    except Exception:
        pass


def _write_llm_raw_log(provider: str, model: str, ticker: str, stage: str, text: str, cfg: Any | None = None) -> None:
    if cfg is not None and not _cfg_bool(cfg, "llm_raw_logging_enabled", True):
        return
    text, hygiene = _compact_text_for_llm_hygiene(text, cfg, for_payload=False)
    max_chars = _cfg_int(cfg, "llm_max_raw_chars", 12000) if cfg is not None else 12000
    safe_text, truncated, original_chars = _truncate_text(text, max_chars)
    payload = {
        "generated_at": _now_iso(),
        "provider": provider,
        "model": model,
        "ticker": ticker,
        "stage": stage,
        "raw_text": safe_text,
        "raw_text_truncated": truncated,
        "raw_text_original_chars": original_chars,
        "hygiene": hygiene,
    }
    path = LOGS_DIR / "llm_raw.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_llm_corrupt_log(
    provider: str,
    model: str,
    ticker: str,
    stage: str,
    text: str,
    error: str,
    cfg: Any | None = None,
    *,
    error_type: str = "llm_output_corrupt",
) -> None:
    if cfg is not None and not _cfg_bool(cfg, "llm_corrupt_logging_enabled", True):
        return
    text, hygiene = _compact_text_for_llm_hygiene(text, cfg, for_payload=False)
    max_chars = _cfg_int(cfg, "llm_corrupt_max_raw_chars", 6000) if cfg is not None else 6000
    safe_text, truncated, original_chars = _truncate_text(text, max_chars)
    payload = {
        "generated_at": _now_iso(),
        "provider": provider,
        "model": model,
        "ticker": ticker,
        "stage": stage,
        "error_type": error_type,
        "error": error,
        "raw_text": safe_text,
        "raw_text_truncated": truncated,
        "raw_text_original_chars": original_chars,
        "hygiene": hygiene,
    }
    path = LOGS_DIR / "llm_corrupt.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_llm_schema_drift_log(
    provider: str,
    model: str,
    ticker: str,
    stage: str,
    unknown_keys: Sequence[str],
    cfg: Any | None = None,
) -> None:
    if cfg is not None and not _cfg_bool(cfg, "llm_corrupt_logging_enabled", True):
        return
    payload = {
        "generated_at": _now_iso(),
        "provider": provider,
        "model": model,
        "ticker": ticker,
        "stage": stage,
        "error_type": "extra_schema_keys_ignored",
        "unknown_keys": list(unknown_keys),
        "fatal_provider_error": False,
        "counts_as_corrupt": False,
    }
    path = LOGS_DIR / "llm_schema_drift.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_llm_provider_error_log(
    provider: str,
    model: str,
    ticker: str,
    stage: str,
    error: str,
    error_type: str,
    cfg: Any | None = None,
) -> None:
    if cfg is not None and not _cfg_bool(cfg, "llm_provider_error_logging_enabled", True):
        return
    payload = {
        "generated_at": _now_iso(),
        "provider": provider,
        "model": model,
        "ticker": ticker,
        "stage": stage,
        "error_type": error_type,
        "fatal_provider_error": error_type in {"provider_billing_or_credit_error", "provider_rate_limit_or_quota_error", "provider_unavailable_or_overloaded"},
        "error": error,
        "raw_text": "",
    }
    if error_type in {"provider_network_or_connection_error", "provider_auth_error", "provider_model_error"}:
        payload["fatal_provider_error"] = True
    path = LOGS_DIR / "llm_provider_errors.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _balance_json_suffix(candidate: str) -> Optional[str]:
    """Conservatively repair outputs that are valid JSON except for missing closing braces/brackets.

    Some model outputs in production were complete objects with the final `]}` or `}`
    truncated. We only append closers when all strings are closed and the imbalance is
    small; otherwise the output remains corrupt and falls back safely.
    """
    stack = []
    in_string = False
    escape = False

    for ch in candidate:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return None
            stack.pop()

    if in_string or not stack or len(stack) > 4:
        return None

    return candidate + "".join(reversed(stack))


def _try_decode_json_object(candidate: str) -> Optional[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:
        repaired = _balance_json_suffix(candidate)
        if repaired:
            try:
                obj, _ = decoder.raw_decode(repaired)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return None
    return None


def _extract_first_json_object(text: str) -> Dict[str, Any]:
    if not text or not text.strip():
        raise LLMOutputCorruptError("empty_model_output")

    stripped = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        stripped = fence_match.group(1).strip()

    direct = _try_decode_json_object(stripped)
    if direct is not None:
        return direct

    for idx, ch in enumerate(stripped):
        if ch != "{":
            continue
        obj = _try_decode_json_object(stripped[idx:])
        if obj is not None:
            return obj

    raise LLMOutputCorruptError("no_valid_json_object_found")


def _ensure_only_allowed_keys(
    payload: Dict[str, Any],
    allowed_keys: Sequence[str],
    require_all: bool = False,
    drop_unknown_keys: bool = False,
    required_keys: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise LLMOutputCorruptError("payload_not_dict")

    allowed = set(allowed_keys)
    actual = set(payload.keys())

    extra = sorted(actual - allowed)
    required = set(required_keys or allowed_keys)
    missing = sorted(required - actual) if require_all else []

    if missing:
        raise LLMOutputCorruptError(f"missing_required_keys: {missing}")

    if extra:
        return {k: payload[k] for k in allowed_keys if k in payload}

    return payload


def _numeric_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def normalize_final_judge_schema_aliases(payload: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
    """Map known final-judge aliases before strict schema validation.

    This intentionally does not invent decision fields or valid_trade_plan. It
    only maps known score aliases when numeric and maps reason(s) to
    judge_reasons when list/string-shaped.
    """
    if not isinstance(payload, dict):
        return payload, []

    out = dict(payload)
    normalized: list[str] = []
    for alias, target in FINAL_JUDGE_SCHEMA_ALIASES.items():
        if target in out or alias not in out:
            continue
        numeric = _numeric_or_none(out.get(alias))
        if numeric is None:
            continue
        out[target] = numeric
        normalized.append(alias)

    if "judge_reasons" not in out:
        for alias in ("reason", "reasons"):
            if alias not in out:
                continue
            value = out.get(alias)
            if isinstance(value, list):
                out["judge_reasons"] = [str(item) for item in value]
                normalized.append(alias)
                break
            if isinstance(value, str) and value.strip():
                out["judge_reasons"] = [value.strip()]
                normalized.append(alias)
                break

    return out, normalized


def _unknown_schema_keys(payload: Dict[str, Any], allowed_keys: Sequence[str]) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return sorted(set(payload.keys()) - set(allowed_keys) - BENIGN_UNKNOWN_KEYS)


class ResilientLLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        self.client = OpenAI(api_key=cfg.openai_api_key)

    def json_response(
        self,
        system_prompt: str,
        payload: Dict[str, Any],
        model: Optional[str] = None,
        max_retries: int = 3,
        *,
        ticker: str = "UNKNOWN",
        stage: str = "unknown",
        allowed_keys: Optional[Sequence[str]] = None,
        require_all_keys: bool = False,
        drop_unknown_keys: bool = False,
        required_keys: Optional[Sequence[str]] = None,
        normalize_final_judge_aliases: bool = False,
        payload_first: bool = False,
    ) -> Dict[str, Any]:
        model_name = model or self.cfg.openai_model

        last_error = None
        for attempt in range(max_retries):
            text = ""
            attempt_started = time.monotonic()
            try:
                payload_content = json.dumps(compact_payload_for_llm(payload, self.cfg), ensure_ascii=False)
                if payload_first:
                    # Stable/shared content first so it forms a reusable cache prefix;
                    # the small call-specific instruction goes last so only that tail
                    # varies across calls that share the same payload (see specialist
                    # calls in strategy_engine._safe_module_response).
                    input_messages = [
                        {"role": "user", "content": payload_content},
                        {"role": "system", "content": system_prompt},
                    ]
                else:
                    input_messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": payload_content},
                    ]
                response = self.client.responses.create(
                    model=model_name,
                    input=input_messages,
                )

                text = getattr(response, "output_text", None) or ""
                if not text:
                    raise LLMOutputCorruptError("openai_missing_output_text")

                _write_llm_raw_log("openai", model_name, ticker, stage, text, self.cfg)

                obj = _extract_first_json_object(text)
                normalized_aliases: list[str] = []
                if normalize_final_judge_aliases:
                    obj, normalized_aliases = normalize_final_judge_schema_aliases(obj)
                if allowed_keys:
                    unknown = _unknown_schema_keys(obj, allowed_keys)
                    if unknown:
                        _write_llm_schema_drift_log("openai", model_name, ticker, stage, unknown, self.cfg)
                    obj = _ensure_only_allowed_keys(
                        obj,
                        allowed_keys=allowed_keys,
                        require_all=require_all_keys,
                        drop_unknown_keys=drop_unknown_keys,
                        required_keys=required_keys,
                    )
                if normalized_aliases:
                    obj["normalized_aliases"] = normalized_aliases
                _record_llm_cost(
                    provider="openai",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=getattr(response, "usage", None),
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="success",
                    decision_result=obj.get("decision") if isinstance(obj, dict) else None,
                    cfg=self.cfg,
                )
                return obj

            except Exception as e:
                last_error = e
                provider_error_type = _provider_error_type(e)
                try:
                    if provider_error_type:
                        _write_llm_provider_error_log("openai", model_name, ticker, stage, str(e), provider_error_type, self.cfg)
                    else:
                        _write_llm_corrupt_log("openai", model_name, ticker, stage, text, str(e), self.cfg)
                except Exception:
                    pass
                _record_llm_cost(
                    provider="openai",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=None,
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="provider_error" if provider_error_type else "corrupt_output",
                    error_type=provider_error_type or "llm_output_corrupt",
                    cfg=self.cfg,
                )

                if provider_error_type == "provider_billing_or_credit_error":
                    raise LLMProviderUnavailableError(f"OpenAI provider unavailable: {provider_error_type}: {e}") from e

                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"OpenAI json_response mislukt: {e}") from e

        raise RuntimeError(f"OpenAI json_response mislukt: {last_error}")

    @staticmethod
    def _extract_json_object(text: str) -> Dict[str, Any]:
        return _extract_first_json_object(text)


class AnthropicClient:
    def __init__(self, cfg):
        self.cfg = cfg
        if anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        if not getattr(cfg, "anthropic_api_key", ""):
            raise ValueError("ANTHROPIC_API_KEY is leeg; Anthropic fallback is uitgeschakeld")
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    def json_message(
        self,
        system_prompt: str,
        payload: Dict[str, Any],
        model: Optional[str] = None,
        max_retries: int = 3,
        *,
        ticker: str = "UNKNOWN",
        stage: str = "unknown",
        allowed_keys: Optional[Sequence[str]] = None,
        require_all_keys: bool = False,
        drop_unknown_keys: bool = False,
        required_keys: Optional[Sequence[str]] = None,
        normalize_final_judge_aliases: bool = False,
    ) -> Dict[str, Any]:
        model_name = model or self.cfg.anthropic_model

        last_error = None
        for attempt in range(max_retries):
            text = ""
            attempt_started = time.monotonic()
            try:
                response = self.client.messages.create(
                    model=model_name,
                    max_tokens=4000,
                    system=system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": json.dumps(compact_payload_for_llm(payload, self.cfg), ensure_ascii=False),
                        }
                    ],
                )

                text_parts = []
                for block in response.content:
                    if getattr(block, "type", None) == "text":
                        text_parts.append(block.text)

                text = "\n".join(text_parts).strip()
                if not text:
                    raise LLMOutputCorruptError("anthropic_missing_text")

                _write_llm_raw_log("anthropic", model_name, ticker, stage, text, self.cfg)

                obj = _extract_first_json_object(text)
                normalized_aliases: list[str] = []
                if normalize_final_judge_aliases:
                    obj, normalized_aliases = normalize_final_judge_schema_aliases(obj)
                if allowed_keys:
                    unknown = _unknown_schema_keys(obj, allowed_keys)
                    if unknown:
                        _write_llm_schema_drift_log("anthropic", model_name, ticker, stage, unknown, self.cfg)
                    obj = _ensure_only_allowed_keys(
                        obj,
                        allowed_keys=allowed_keys,
                        require_all=require_all_keys,
                        drop_unknown_keys=drop_unknown_keys,
                        required_keys=required_keys,
                    )
                if normalized_aliases:
                    obj["normalized_aliases"] = normalized_aliases
                _record_llm_cost(
                    provider="anthropic",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=getattr(response, "usage", None),
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="success",
                    decision_result=obj.get("decision") if isinstance(obj, dict) else None,
                    cfg=self.cfg,
                )
                return obj

            except Exception as e:
                last_error = e
                provider_error_type = _provider_error_type(e)
                try:
                    if provider_error_type:
                        _write_llm_provider_error_log("anthropic", model_name, ticker, stage, str(e), provider_error_type, self.cfg)
                    else:
                        _write_llm_corrupt_log("anthropic", model_name, ticker, stage, text, str(e), self.cfg)
                except Exception:
                    pass
                _record_llm_cost(
                    provider="anthropic",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=None,
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="provider_error" if provider_error_type else "corrupt_output",
                    error_type=provider_error_type or "llm_output_corrupt",
                    cfg=self.cfg,
                )

                if provider_error_type:
                    raise LLMProviderUnavailableError(f"Anthropic provider unavailable: {provider_error_type}: {e}") from e

                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"Anthropic json_message mislukt: {e}") from e

        raise RuntimeError(f"Anthropic json_message mislukt: {last_error}")


class DeepSeekClient:
    DEEPSEEK_PREPROCESS_REQUIRED_KEYS = [
        "regime_hints",
        "trend_hints",
        "breakout_hints",
        "meanrev_hints",
        "risk_hints",
        "concise_evidence",
        "raw_pattern_hints",
        "news_sentiment_hints",
        "uncertainties",
    ]

    def __init__(self, cfg):
        self.cfg = cfg
        if not getattr(cfg, "deepseek_api_key", ""):
            raise ValueError("DEEPSEEK_API_KEY ontbreekt terwijl DeepSeekClient wordt geïnstantieerd")
        self.client = OpenAI(
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_base_url,
        )

    def json_chat(
        self,
        system_prompt: str,
        payload: Dict[str, Any],
        model: Optional[str] = None,
        max_retries: int = 3,
        *,
        ticker: str = "UNKNOWN",
        stage: str = "unknown",
        allowed_keys: Optional[Sequence[str]] = None,
        require_all_keys: bool = False,
        drop_unknown_keys: bool = False,
    ) -> Dict[str, Any]:
        model_name = model or self.cfg.deepseek_model

        last_error = None
        for attempt in range(max_retries):
            text = ""
            attempt_started = time.monotonic()
            try:
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(compact_payload_for_llm(payload, self.cfg), ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    max_tokens=1200,
                )

                text = response.choices[0].message.content if response.choices else ""
                if not text:
                    raise LLMOutputCorruptError("deepseek_missing_content")

                _write_llm_raw_log("deepseek", model_name, ticker, stage, text, self.cfg)

                obj = self._parse_deepseek_json(text)

                if stage == "deepseek_preprocess":
                    obj = self._normalize_deepseek_preprocess_payload(obj)

                if allowed_keys:
                    unknown = _unknown_schema_keys(obj, allowed_keys)
                    if unknown:
                        _write_llm_schema_drift_log("deepseek", model_name, ticker, stage, unknown, self.cfg)
                    obj = _ensure_only_allowed_keys(
                        obj,
                        allowed_keys=allowed_keys,
                        require_all=require_all_keys,
                        drop_unknown_keys=drop_unknown_keys,
                    )
                _record_llm_cost(
                    provider="deepseek",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=getattr(response, "usage", None),
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="success",
                    decision_result=obj.get("decision") if isinstance(obj, dict) else None,
                    cfg=self.cfg,
                )
                return obj

            except Exception as e:
                last_error = e
                provider_error_type = _provider_error_type(e)
                try:
                    if provider_error_type:
                        _write_llm_provider_error_log("deepseek", model_name, ticker, stage, str(e), provider_error_type, self.cfg)
                    else:
                        _write_llm_corrupt_log("deepseek", model_name, ticker, stage, text, str(e), self.cfg)
                except Exception:
                    pass
                _record_llm_cost(
                    provider="deepseek",
                    model=model_name,
                    ticker=ticker,
                    stage=stage,
                    attempt=attempt + 1,
                    usage=None,
                    latency_ms=(time.monotonic() - attempt_started) * 1000.0,
                    call_outcome="provider_error" if provider_error_type else "corrupt_output",
                    error_type=provider_error_type or "llm_output_corrupt",
                    cfg=self.cfg,
                )

                if provider_error_type == "provider_billing_or_credit_error":
                    raise LLMProviderUnavailableError(f"DeepSeek provider unavailable: {provider_error_type}: {e}") from e

                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"DeepSeek gaf geen geldige JSON terug: {e}") from e

        raise RuntimeError(f"DeepSeek gaf geen geldige JSON terug: {last_error}")

    def _parse_deepseek_json(self, text: str) -> Dict[str, Any]:
        candidate = text.strip()

        try:
            return _extract_first_json_object(candidate)
        except Exception:
            pass

        sanitized = self._sanitize_json_like(candidate)

        try:
            return _extract_first_json_object(sanitized)
        except Exception as e:
            raise LLMOutputCorruptError(
                f"deepseek_json_parse_failed_after_sanitize: {e}"
            ) from e

    def _normalize_deepseek_preprocess_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        DeepSeek houdt zich soms niet aan het gevraagde top-level schema voor preprocess
        en geeft dan compacte buckets terug zoals:
        - trend
        - momentum
        - compression
        - range
        - volatility
        - conflict
        - strength
        - trend_score
        - range_score
        - range_fit_score
        - trend_fit_score

        Deze functie probeert zulke alternatieve keys veilig onder te brengen
        in het verwachte preprocess-schema, zodat bruikbare inhoud niet onnodig
        wordt weggegooid.
        """
        if not isinstance(payload, dict):
            raise LLMOutputCorruptError("deepseek_preprocess_payload_not_dict")

        required = set(self.DEEPSEEK_PREPROCESS_REQUIRED_KEYS)
        actual = set(payload.keys())

        if actual.issubset(required):
            normalized = dict(payload)
            for key in self.DEEPSEEK_PREPROCESS_REQUIRED_KEYS:
                normalized.setdefault(key, {})
            return normalized

        normalized: Dict[str, Any] = {
            "regime_hints": {},
            "trend_hints": {},
            "breakout_hints": {},
            "meanrev_hints": {},
            "risk_hints": {},
            "concise_evidence": {},
            "raw_pattern_hints": {},
            "news_sentiment_hints": {},
            "uncertainties": {},
        }

        passthrough_keys = required.intersection(actual)
        for key in passthrough_keys:
            normalized[key] = payload.get(key, {})

        unknown_items = {k: payload[k] for k in payload.keys() if k not in required}

        trend_bucket: Dict[str, Any] = {}
        regime_bucket: Dict[str, Any] = {}
        meanrev_bucket: Dict[str, Any] = {}
        breakout_bucket: Dict[str, Any] = {}
        risk_bucket: Dict[str, Any] = {}
        evidence_bucket: Dict[str, Any] = {}
        raw_bucket: Dict[str, Any] = {}
        uncertainty_bucket: Dict[str, Any] = normalized["uncertainties"]

        for key, value in unknown_items.items():
            k = str(key).lower()

            if k in {"trend", "trend_score", "trend_fit_score", "strength"}:
                trend_bucket[key] = value
                continue

            if k in {"compression", "range", "range_score", "range_fit_score"}:
                breakout_bucket[key] = value
                meanrev_bucket[key] = value
                continue

            if k in {"momentum", "volatility"}:
                raw_bucket[key] = value
                evidence_bucket[key] = value
                continue

            if k in {"conflict"}:
                risk_bucket[key] = value
                continue

            regime_bucket[key] = value

        if trend_bucket:
            base = normalized.get("trend_hints")
            normalized["trend_hints"] = base if isinstance(base, dict) else {}
            normalized["trend_hints"].update(trend_bucket)

        if regime_bucket:
            base = normalized.get("regime_hints")
            normalized["regime_hints"] = base if isinstance(base, dict) else {}
            normalized["regime_hints"].update(regime_bucket)

        if breakout_bucket:
            base = normalized.get("breakout_hints")
            normalized["breakout_hints"] = base if isinstance(base, dict) else {}
            normalized["breakout_hints"].update(breakout_bucket)

        if meanrev_bucket:
            base = normalized.get("meanrev_hints")
            normalized["meanrev_hints"] = base if isinstance(base, dict) else {}
            normalized["meanrev_hints"].update(meanrev_bucket)

        if risk_bucket:
            base = normalized.get("risk_hints")
            normalized["risk_hints"] = base if isinstance(base, dict) else {}
            normalized["risk_hints"].update(risk_bucket)

        if evidence_bucket:
            base = normalized.get("concise_evidence")
            normalized["concise_evidence"] = base if isinstance(base, dict) else {}
            normalized["concise_evidence"].update(evidence_bucket)

        if raw_bucket:
            base = normalized.get("raw_pattern_hints")
            normalized["raw_pattern_hints"] = base if isinstance(base, dict) else {}
            normalized["raw_pattern_hints"].update(raw_bucket)

        if not isinstance(uncertainty_bucket, dict):
            uncertainty_bucket = {}

        uncertainty_bucket.setdefault(
            "normalized_unknown_top_level_keys",
            sorted(list(unknown_items.keys())),
        )
        normalized["uncertainties"] = uncertainty_bucket

        for key in self.DEEPSEEK_PREPROCESS_REQUIRED_KEYS:
            if not isinstance(normalized.get(key), dict):
                normalized[key] = {}

        return normalized

    @staticmethod
    def _extract_candidate_json(text: str) -> str:
        text = text.strip()

        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                _, end = decoder.raw_decode(text[idx:])
                return text[idx: idx + end].strip()
            except Exception:
                continue

        return text

    @staticmethod
    def _sanitize_json_like(text: str) -> str:
        s = DeepSeekClient._extract_candidate_json(text).strip()

        s = re.sub(r",\s*([}\]])", r"\1", s)

        s = re.sub(
            r'(:\s*)(-?\d+(?:\.\d+)?%)',
            lambda m: f'{m.group(1)}"{m.group(2)}"',
            s,
        )

        s = re.sub(
            r'(:\s*)(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?%)',
            lambda m: f'{m.group(1)}"{m.group(2)}"',
            s,
            flags=re.IGNORECASE,
        )

        s = re.sub(r'(?<!["\w])NaN(?!["\w])', "null", s)
        s = re.sub(r'(?<!["\w])Infinity(?!["\w])', "null", s)
        s = re.sub(r'(?<!["\w])-Infinity(?!["\w])', "null", s)

        return s
