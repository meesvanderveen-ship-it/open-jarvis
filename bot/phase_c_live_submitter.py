from __future__ import annotations

import json
import uuid
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from bot.amount_cap_guard import evaluate_amount_cap_guard
from bot.live_order_size_policy import live_order_size_policy_report, validate_entry_quote_size
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.phase_c_live_guard import evaluate_mode_c_market_order_guard
from bot.product_rules import canonical_product_rules, validate_limit_buy_payload

ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def build_phase_c_live_client_order_id(*, ticker: str, source_id: Optional[str] = None) -> str:
    clean = _normalize_ticker(ticker).replace("-", "")
    suffix_source = str(source_id or "").strip().replace(" ", "-")[-18:]
    suffix = suffix_source or uuid.uuid4().hex[:18]
    return f"phasec-{clean}-{suffix}-{uuid.uuid4().hex[:8]}"


def build_phase_c_live_entry_payload(
    *,
    cfg: Any,
    ticker: str,
    order_intent: Dict[str, Any],
    guard_result: Dict[str, Any],
    product_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a future Coinbase limit-entry payload without submitting it.

    Phase C.2 intentionally prepares/audits the payload only. The returned
    structure can be used by a later, explicitly-enabled submit path. It is
    conservative: entry-only, BUY-only, quote capped by Phase-C config and base
    size derived from quote/limit_price.
    """
    ticker = _normalize_ticker(ticker)
    product_rules = product_rules if isinstance(product_rules, dict) else {}
    quote = _to_decimal(order_intent.get("size_quote") or order_intent.get("quote_size"), "0")
    limit_price = _to_decimal(order_intent.get("limit_price"), "0")
    max_quote = _to_decimal(getattr(cfg, "phase_c_max_order_quote", "0"), "0")

    reject_reasons = []
    if str(order_intent.get("side") or "").upper() != "BUY":
        reject_reasons.append("phase_c_payload_builder_only_supports_buy")
    if str(order_intent.get("execution_action") or "").lower() != "place_limit_buy":
        reject_reasons.append("phase_c_payload_builder_requires_place_limit_buy")
    if quote <= ZERO:
        reject_reasons.append("missing_or_zero_quote_size")
    if limit_price <= ZERO:
        reject_reasons.append("missing_or_zero_limit_price")
    if max_quote <= ZERO:
        reject_reasons.append("phase_c_max_order_quote_not_positive")
    quote_policy = validate_entry_quote_size(quote, cfg)
    reject_reasons.extend(quote_policy["blockers"])
    if quote > max_quote:
        reject_reasons.append("quote_size_above_phase_c_max_order_quote")

    precision_report = validate_limit_buy_payload(
        ticker,
        quote,
        limit_price,
        product_rules,
        max_quote_size=max_quote,
    )
    amount_cap_guard = evaluate_amount_cap_guard(
        cfg=cfg,
        ticker=ticker,
        requested_quote=quote,
        limit_price=limit_price,
        product_rules=product_rules,
    )
    reject_reasons.extend([f"amount_cap:{reason}" for reason in amount_cap_guard.get("blockers") or []])
    product_rule_context = canonical_product_rules(ticker, product_rules)
    reject_reasons.extend([f"precision:{reason}" for reason in precision_report.get("blockers") or []])
    normalized_quote = _to_decimal(precision_report.get("normalized_quote_size") or precision_report.get("quote_size"), "0")
    estimated_quote_after_rounding = _to_decimal(precision_report.get("estimated_quote_after_rounding"), "0")
    normalized_limit_price = _to_decimal(precision_report.get("normalized_limit_price"), "0")
    base = _to_decimal(precision_report.get("raw_base_size"), "0")
    normalized_base = _to_decimal(precision_report.get("normalized_base_size"), "0")
    price_increment = _to_decimal(precision_report.get("price_increment"), "0")
    base_increment = _to_decimal(precision_report.get("base_increment"), "0")
    quote_increment = _to_decimal(precision_report.get("quote_increment"), "0")
    # Coinbase receives base_size for a limit BUY.  The executable notional is
    # therefore base_size * normalized limit_price, not merely the requested
    # quote field before base-increment rounding.
    executable_quote = estimated_quote_after_rounding if estimated_quote_after_rounding > ZERO else normalized_quote
    normalized_quote_policy = validate_entry_quote_size(executable_quote, cfg)
    if executable_quote > ZERO:
        reject_reasons.extend([f"normalized_quote:{reason}" for reason in normalized_quote_policy["blockers"]])
    elif quote > ZERO:
        reject_reasons.append("normalized_quote:missing_or_zero_quote_size")

    client_order_id = str(order_intent.get("client_order_id") or "").strip()
    if not client_order_id or client_order_id.startswith("paper-"):
        client_order_id = build_phase_c_live_client_order_id(
            ticker=ticker,
            source_id=order_intent.get("intent_id") or order_intent.get("linked_trade_plan_id"),
        )

    post_only = bool(getattr(cfg, "phase_c_live_order_post_only", True))
    coinbase_payload = {
        "client_order_id": client_order_id,
        "product_id": ticker,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": format(normalized_base, "f"),
                "limit_price": format(normalized_limit_price, "f"),
                "post_only": post_only,
            }
        },
    }

    return {
        "generated_at": _now_iso(),
        "phase": "C2_live_entry_payload_preparation",
        "ticker": ticker,
        "accepted": not reject_reasons,
        "reject_reasons": reject_reasons,
        "client_order_id": client_order_id,
        "side": "BUY",
        "order_type": "limit_limit_gtc",
        "size_quote_requested": str(quote),
        "size_quote_normalized": format(executable_quote.quantize(Decimal("0.01")), "f"),
        "size_base_estimated": str(base),
        "size_base_normalized": str(normalized_base),
        "limit_price_requested": str(limit_price) if limit_price > ZERO else None,
        "limit_price": str(normalized_limit_price) if normalized_limit_price > ZERO else None,
        "limit_price_normalized": str(normalized_limit_price),
        "base_increment_used": str(base_increment),
        "price_increment_used": str(price_increment),
        "quote_increment_used": str(quote_increment),
        "product_rules": product_rule_context,
        "execution_feasibility": {
            "can_construct_valid_limit_buy_payload": bool(precision_report.get("valid")),
            "normalized_price": precision_report.get("normalized_limit_price"),
            "normalized_base_size": precision_report.get("normalized_base_size"),
            "estimated_quote": precision_report.get("estimated_quote_after_rounding"),
            "blockers": list(precision_report.get("blockers") or []),
            "warnings": list(precision_report.get("warnings") or []),
        },
        "precision_normalization": precision_report,
        "amount_cap_guard": amount_cap_guard,
        "post_only": post_only,
        "product_rules_used": _json_safe(product_rules),
        "live_order_size_policy": live_order_size_policy_report(cfg),
        "quote_size_policy": quote_policy,
        "normalized_quote_size_policy": normalized_quote_policy,
        "dynamic_entry_sizing": order_intent.get("dynamic_entry_sizing") if isinstance(order_intent.get("dynamic_entry_sizing"), dict) else None,
        "coinbase_payload_preview": coinbase_payload,
        "guard_allows_live_submit": bool((guard_result or {}).get("guard_allows_live_submit")),
        "safety_policy": {
            "payload_preparation_only": True,
            "no_coinbase_submit_in_payload_builder": True,
            "entry_only_phase_c": True,
            "exit_limit_orders_disabled_for_phase_c": bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)),
        },
    }


def _extract_exchange_order_id(response: Dict[str, Any]) -> str:
    success = response.get("success_response") if isinstance(response.get("success_response"), dict) else {}
    nested = response.get("response") if isinstance(response.get("response"), dict) else {}
    nested_success = nested.get("success_response") if isinstance(nested.get("success_response"), dict) else {}
    return str(
        response.get("order_id")
        or response.get("id")
        or response.get("exchange_order_id")
        or success.get("order_id")
        or success.get("id")
        or nested.get("order_id")
        or nested.get("id")
        or nested_success.get("order_id")
        or nested_success.get("id")
        or ""
    ).strip()


def _normalize_limit_buy_submit_response(*, response: Any, client_order_id: str) -> Dict[str, Any]:
    safe_response = _json_safe(response)
    response_dict = safe_response if isinstance(safe_response, dict) else {}
    error_response = response_dict.get("error_response") if isinstance(response_dict.get("error_response"), dict) else {}
    success_response = response_dict.get("success_response") if isinstance(response_dict.get("success_response"), dict) else {}
    success = bool(response_dict.get("success", True))
    exchange_order_id = _extract_exchange_order_id(response_dict)
    accepted = bool(success and exchange_order_id)
    reject_reason = ""
    if not accepted:
        reject_reason = str(error_response.get("error") or ("coinbase_success_without_order_id" if success else "coinbase_success_false"))
    return {
        "success": success,
        "accepted": accepted,
        "submitted": accepted,
        "exchange_order_id": exchange_order_id,
        "client_order_id": str(
            response_dict.get("client_order_id")
            or success_response.get("client_order_id")
            or client_order_id
            or ""
        ),
        "status": "submitted" if accepted else ("rejected" if not success else "unconfirmed_no_order_id"),
        "raw_response": safe_response,
        "error": "" if success else str(error_response.get("message") or error_response.get("error") or "coinbase_success_false"),
        "reject_reason": reject_reason,
        "reject_message": str(error_response.get("message") or ""),
        "preview_failure_reason": str(error_response.get("preview_failure_reason") or ""),
    }


def submit_limit_buy_order(
    *,
    coinbase_client: Any,
    ticker: str,
    quote_size: Decimal,
    base_size: Decimal,
    limit_price: Decimal,
    client_order_id: str,
    post_only: bool = True,
) -> Dict[str, Any]:
    """Submit a BUY limit order through the canonical Coinbase adapter.

    It does not write local state and it does not relax Phase-C guards; callers
    must decide whether a live submit is allowed before invoking it. Generic
    ``place_limit_order``/``create_order`` fallbacks are intentionally not
    accepted here: they would create another execution adapter boundary.
    """
    if coinbase_client is None:
        return {
            "success": False,
            "accepted": False,
            "submitted": False,
            "exchange_order_id": "",
            "client_order_id": client_order_id,
            "status": "unsupported",
            "raw_response": {},
            "error": "coinbase_client_not_provided",
            "error_type": "MissingCoinbaseClient",
        }
    if base_size <= ZERO:
        return {
            "success": False,
            "accepted": False,
            "submitted": False,
            "exchange_order_id": "",
            "client_order_id": client_order_id,
            "status": "rejected",
            "raw_response": {},
            "error": "base_size_must_be_positive",
            "error_type": "InvalidOrderPayload",
        }

    if callable(getattr(coinbase_client, "submit_limit_buy_order", None)):
        response = coinbase_client.submit_limit_buy_order(
            ticker=ticker,
            quote_size=quote_size,
            base_size=base_size,
            limit_price=limit_price,
            client_order_id=client_order_id,
            post_only=post_only,
        )
        out = _normalize_limit_buy_submit_response(response=response, client_order_id=client_order_id)
        out["client_method"] = "submit_limit_buy_order"
        return out

    return {
        "success": False,
        "accepted": False,
        "submitted": False,
        "exchange_order_id": "",
        "client_order_id": client_order_id,
        "status": "unsupported",
        "raw_response": {},
        "error": "coinbase_client_missing_canonical_submit_limit_buy_order",
        "error_type": "MissingClientMethod",
        "supported_methods_checked": ["submit_limit_buy_order"],
    }


def _client_supports_limit_buy_submit(coinbase_client: Any) -> bool:
    return callable(getattr(coinbase_client, "submit_limit_buy_order", None))


def _phase_c_limit_payload_shape_blockers(payload: Dict[str, Any]) -> list[str]:
    preview = payload.get("coinbase_payload_preview") if isinstance(payload, dict) else {}
    preview = preview if isinstance(preview, dict) else {}
    order_configuration = preview.get("order_configuration") if isinstance(preview.get("order_configuration"), dict) else {}
    limit_gtc = order_configuration.get("limit_limit_gtc") if isinstance(order_configuration.get("limit_limit_gtc"), dict) else {}
    blockers: list[str] = []
    if "market_market_ioc" in order_configuration:
        blockers.append("phase_c_market_order_entry_blocked")
    if not limit_gtc:
        blockers.append("phase_c_limit_order_configuration_missing")
        return blockers
    if _to_decimal(limit_gtc.get("base_size"), "0") <= ZERO:
        blockers.append("phase_c_limit_order_base_size_missing")
    if _to_decimal(limit_gtc.get("limit_price"), "0") <= ZERO:
        blockers.append("phase_c_limit_order_price_missing")
    if limit_gtc.get("post_only") is not True:
        blockers.append("phase_c_limit_order_post_only_required")
    return blockers


def prepare_phase_c_live_entry_submission(
    *,
    cfg: Any,
    ticker: str,
    order_intent: Optional[Dict[str, Any]],
    guard_result: Optional[Dict[str, Any]],
    coinbase_client: Any = None,
    product_rules: Optional[Dict[str, Any]] = None,
    submit_live: bool = False,
) -> Dict[str, Any]:
    """Prepare a Phase-C live-entry submission and keep it hard-disabled.

    This is the C.2 bridge: it validates/normalizes/audits the future live limit
    order path, but does not call Coinbase unless a later patch explicitly passes
    submit_live=True *and* ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true. The current
    strategy integration passes submit_live=False.
    """
    ticker = _normalize_ticker(ticker)
    order_intent = order_intent if isinstance(order_intent, dict) else {}
    guard_result = guard_result if isinstance(guard_result, dict) else {}

    payload = build_phase_c_live_entry_payload(
        cfg=cfg,
        ticker=ticker,
        order_intent=order_intent,
        guard_result=guard_result,
        product_rules=product_rules,
    )

    hard_blocks = []
    hard_blocks.extend(_phase_c_limit_payload_shape_blockers(payload))
    if not bool(getattr(cfg, "enable_phase_c_live_submit_infrastructure", True)):
        hard_blocks.append("phase_c_live_submit_infrastructure_disabled")
    if not bool(guard_result.get("guard_allows_live_submit")):
        hard_blocks.append("phase_c_guard_did_not_allow_live_submit")
    if not payload.get("accepted"):
        hard_blocks.append("phase_c_payload_not_accepted")
    if not bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)):
        hard_blocks.append("phase_c_actual_coinbase_submit_disabled")
    runtime_ack_valid = (
        str(getattr(cfg, "phase_c43_runtime_submit_ack", "") or "").strip()
        == C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
    )
    if not runtime_ack_valid:
        hard_blocks.append("phase_c43_runtime_submit_ack_missing_or_invalid")
    if not submit_live:
        hard_blocks.append("submit_live_argument_false")
    if coinbase_client is None:
        hard_blocks.append("coinbase_client_not_provided")
    elif not _client_supports_limit_buy_submit(coinbase_client):
        hard_blocks.append("coinbase_limit_buy_submit_route_not_supported")

    can_submit = not hard_blocks
    result: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": "C2_live_entry_submit_preparation",
        "ticker": ticker,
        "status": "phase_c_live_submit_prepared_disabled" if hard_blocks else "phase_c_live_submit_ready",
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "hard_block_reasons": hard_blocks,
        "payload": payload,
        "guard_result_summary": {
            "guard_allows_live_submit": bool(guard_result.get("guard_allows_live_submit")),
            "hard_block_reasons": list(guard_result.get("hard_block_reasons") or []),
            "passed_checks": list(guard_result.get("passed_checks") or []),
        },
        "safety_policy": {
            "phase_c2_is_infrastructure_only": True,
            "strategy_engine_passes_submit_live_false": True,
            "actual_coinbase_submit_requires_extra_flag_and_future_patch": True,
            "runtime_authority_required_for_coinbase_buy_submit": True,
            "runtime_authority_valid": runtime_ack_valid,
            "pending_intent_is_not_execution_permission": True,
        },
    }

    if can_submit:
        # Present only for future C.3. Current strategy integration never reaches
        # this branch because it passes submit_live=False and the default config
        # keeps ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false.
        result["live_submission_attempted"] = True
        try:
            preview = payload.get("coinbase_payload_preview") or {}
            cfg_payload = (preview.get("order_configuration") or {}).get("limit_limit_gtc") or {}
            adapter_result = submit_limit_buy_order(
                coinbase_client=coinbase_client,
                ticker=ticker,
                quote_size=_to_decimal(payload.get("size_quote_normalized") or payload.get("size_quote_requested"), "0"),
                base_size=_to_decimal(cfg_payload.get("base_size"), "0"),
                limit_price=_to_decimal(cfg_payload.get("limit_price"), "0"),
                client_order_id=str(preview.get("client_order_id") or payload.get("client_order_id")),
                post_only=bool(cfg_payload.get("post_only", True)),
            )
            safe_response = adapter_result.get("raw_response") if isinstance(adapter_result, dict) else {}
            response_success = bool((adapter_result or {}).get("success"))
            response_order_id = str((adapter_result or {}).get("exchange_order_id") or "").strip()
            result["coinbase_submit_adapter"] = _json_safe(adapter_result)
            if response_success and response_order_id:
                result.update({
                    "status": "phase_c_live_order_submitted",
                    "live_order_submitted": True,
                    "coinbase_response": safe_response,
                    "exchange_order_id": response_order_id,
                    "client_order_id": str((adapter_result or {}).get("client_order_id") or preview.get("client_order_id") or payload.get("client_order_id") or ""),
                })
            elif response_success:
                result.update({
                    "status": "phase_c_live_order_submit_unconfirmed_no_order_id",
                    "live_order_submitted": False,
                    "coinbase_response": safe_response,
                    "reject_reason": "coinbase_success_without_order_id",
                })
            else:
                result.update({
                    "status": "phase_c_live_order_rejected_by_coinbase",
                    "live_order_submitted": False,
                    "coinbase_response": safe_response,
                    "reject_reason": str((adapter_result or {}).get("reject_reason") or "coinbase_success_false"),
                    "reject_message": str((adapter_result or {}).get("reject_message") or (adapter_result or {}).get("error") or ""),
                    "preview_failure_reason": str((adapter_result or {}).get("preview_failure_reason") or ""),
                })
        except Exception as exc:
            result.update({
                "status": "phase_c_live_order_submit_failed",
                "live_order_submitted": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    return _json_safe(result)


def build_mode_c_market_order_payload(
    *,
    ticker: str,
    side: str,
    order_intent: Dict[str, Any],
    guard_result: Dict[str, Any],
    reason: str = "",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    side_norm = str(side or "").strip().upper()
    order_intent = order_intent if isinstance(order_intent, dict) else {}
    guard_result = guard_result if isinstance(guard_result, dict) else {}
    quote = _to_decimal(order_intent.get("size_quote") or order_intent.get("quote_size"), "0")
    base = _to_decimal(order_intent.get("base_size") or order_intent.get("size_base"), "0")
    reject_reasons = []
    if side_norm not in {"BUY", "SELL"}:
        reject_reasons.append("market_order_side_not_supported")
    if side_norm == "BUY" and quote <= ZERO:
        reject_reasons.append("missing_or_zero_quote_size")
    if side_norm == "SELL" and base <= ZERO:
        reject_reasons.append("market_sell_base_missing")
    if not bool(guard_result.get("guard_allows_market_order")):
        reject_reasons.append("mode_c_market_guard_did_not_allow_order")
    client_order_id = str(order_intent.get("client_order_id") or "").strip()
    if not client_order_id or client_order_id.startswith("paper-"):
        client_order_id = build_phase_c_live_client_order_id(
            ticker=ticker,
            source_id=order_intent.get("intent_id") or order_intent.get("linked_trade_plan_id") or "modec-market",
        ).replace("phasec-", "modec-")
    order_cfg = {"quote_size": format(quote, "f")} if side_norm == "BUY" else {"base_size": format(base, "f")}
    return {
        "generated_at": _now_iso(),
        "phase": "mode_c_market_order_payload_preparation",
        "accepted": not reject_reasons,
        "reject_reasons": reject_reasons,
        "client_order_id": client_order_id,
        "ticker": ticker,
        "product_id": ticker,
        "side": side_norm,
        "order_type": "market",
        "quote_size": str(quote) if quote > ZERO else None,
        "base_size": str(base) if base > ZERO else None,
        "reason": reason or str(order_intent.get("reason") or "mode_c_market_order"),
        "approval_source": (guard_result.get("candidate_summary") or {}).get("approval_source"),
        "risk_checks": list(guard_result.get("passed_checks") or []),
        "blockers": list(guard_result.get("hard_block_reasons") or []),
        "coinbase_payload_preview": {
            "client_order_id": client_order_id,
            "product_id": ticker,
            "side": side_norm,
            "order_configuration": {"market_market_ioc": order_cfg},
        },
        "safety_policy": {
            "payload_preparation_only": True,
            "no_coinbase_submit_in_payload_builder": True,
            "mode_c_ack_required": True,
            "replication_must_be_disabled": True,
            "terminal_fill_evidence_required_before_local_apply": side_norm == "SELL",
        },
    }


def prepare_mode_c_market_order_submission(
    *,
    cfg: Any,
    ticker: str,
    side: str,
    order_intent: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[Dict[str, Any]] = None,
    live_risk_result: Optional[Dict[str, Any]] = None,
    existing_position: Optional[Dict[str, Any]] = None,
    coinbase_client: Any = None,
    submit_live: bool = False,
    open_orders_count: int = 0,
    open_positions_count: int = 0,
    new_orders_this_cycle: int = 0,
    duplicate_open_order: bool = False,
    open_d3_exit_exists: bool = False,
    reason: str = "",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    side_norm = str(side or "").strip().upper()
    order_intent = order_intent if isinstance(order_intent, dict) else {}
    guard = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker=ticker,
        side=side_norm,
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        live_risk_result=live_risk_result,
        existing_position=existing_position,
        open_orders_count=open_orders_count,
        open_positions_count=open_positions_count,
        new_orders_this_cycle=new_orders_this_cycle,
        duplicate_open_order=duplicate_open_order,
        open_d3_exit_exists=open_d3_exit_exists,
    )
    payload = build_mode_c_market_order_payload(
        ticker=ticker,
        side=side_norm,
        order_intent=order_intent,
        guard_result=guard,
        reason=reason,
    )
    hard_blocks = list(guard.get("hard_block_reasons") or [])
    if not payload.get("accepted"):
        hard_blocks.append("mode_c_market_payload_not_accepted")
    if not submit_live:
        hard_blocks.append("submit_live_argument_false")
    if coinbase_client is None:
        hard_blocks.append("coinbase_client_not_provided")
    elif not hasattr(coinbase_client, "place_market_order"):
        hard_blocks.append("market_order_route_not_supported")
    # Mode A has one BUY boundary: the governed C.4.3 resting-limit route.
    # Retire this generic market-order submitter even if old Mode-C flags are
    # present, so no configuration can create a parallel Coinbase path.
    hard_blocks.append("mode_c_market_execution_route_retired")
    result: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": "mode_c_market_order_submit_preparation",
        "status": "mode_c_market_order_retired",
        "ticker": ticker,
        "side": side_norm,
        "order_type": "market",
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "payload": payload,
        "guard_result": guard,
        "audit_log_fields": {
            "order_type": "market",
            "side": side_norm,
            "ticker": ticker,
            "quote": payload.get("quote_size"),
            "base": payload.get("base_size"),
            "reason": payload.get("reason"),
            "approval_source": payload.get("approval_source"),
            "risk_checks": payload.get("risk_checks"),
        },
        "safety_policy": {
            "no_coinbase_market_submit_from_this_route": True,
            "single_mode_a_buy_boundary_is_c43_resting_limit": True,
            "no_local_apply_without_terminal_fill_evidence": side_norm == "SELL",
            "replication_must_be_disabled": True,
            "neural_execution_not_used": True,
        },
    }
    return _json_safe(result)


def build_phase_c_dry_run_candidate(*, cfg: Any, ticker: str = "BTC-USDC") -> Dict[str, Any]:
    """Build a deterministic diagnostic candidate for submit-audit dry runs.

    The candidate is intentionally tiny and synthetic. It is only used by
    tools/tests to verify that the Phase-C submit scaffold writes safe audit
    records while actual Coinbase submission remains disabled.
    """
    ticker = _normalize_ticker(ticker)
    quote = min(_to_decimal(getattr(cfg, "phase_c_max_order_quote", "10"), "10"), Decimal("10"))
    if quote <= ZERO:
        quote = Decimal("10")
    limit_price = Decimal("50000") if ticker.startswith("BTC-") else Decimal("10")
    intent_id = f"diagnostic-phase-c21-{ticker.replace('-', '')}"
    order_intent = {
        "intent_id": intent_id,
        "client_order_id": f"paper-{intent_id}",
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": str(quote),
        "limit_price": str(limit_price),
        "diagnostic": True,
        "dry_run": True,
        "paper_only": True,
        "requires_fresh_judge_and_risk": True,
    }
    analysis = {
        "ticker": ticker,
        "judge": {
            "decision": "approve_trade",
            "side": "BUY",
            "size_quote": str(quote),
            "diagnostic": True,
        },
        "feature_pack": {
            "decision_context": {
                "pending_order_intent": {
                    "intent_id": intent_id,
                    "ticker": ticker,
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                    "diagnostic": True,
                    "dry_run": True,
                }
            }
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "read_only": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.01",
        },
        "diagnostic": True,
        "dry_run": True,
    }
    risk = {
        "accepted": True,
        "approved": True,
        "risk_approved": True,
        "mode": "live_preflight_diagnostic",
        "diagnostic": True,
    }
    product_rules = {
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "1.00",
    }
    return {
        "ticker": ticker,
        "analysis": analysis,
        "execution_plan": execution_plan,
        "order_intent": order_intent,
        "risk": risk,
        "product_rules": product_rules,
    }


def build_phase_c_dry_run_cfg(cfg: Any, *, ticker: str, simulate_ready_guard: bool) -> Any:
    """Return a shallow config copy for optional diagnostic-ready guard simulation.

    The real config is never mutated. Even in ready simulation, actual Coinbase
    submit remains disabled so the dry run cannot place an order.
    """
    cfg_copy = copy(cfg)
    if simulate_ready_guard:
        cfg_copy.execution_mode = "live"
        cfg_copy.enable_phase_c_live_small_limit_orders = True
        cfg_copy.enable_limit_order_manager = True
        cfg_copy.enable_live_limit_orders = True
        cfg_copy.enable_live_entry_orders = True
        cfg_copy.enable_live_exit_orders = False
        cfg_copy.phase_c_allowed_tickers = [_normalize_ticker(ticker)]
        cfg_copy.phase_c_max_open_entry_orders = max(1, int(getattr(cfg_copy, "phase_c_max_open_entry_orders", 1)))
        cfg_copy.phase_c_max_new_orders_per_cycle = max(1, int(getattr(cfg_copy, "phase_c_max_new_orders_per_cycle", 1)))
    else:
        # Keep the non-simulated diagnostic deterministic even when the server
        # .env is already armed for autonomous/orderbook mode. C.2.1's current
        # config dry-run must continue to prove that the Phase-C guard blocks a
        # normal, non-simulated submit attempt.
        cfg_copy.enable_phase_c_live_small_limit_orders = False
        cfg_copy.enable_live_limit_orders = False
        cfg_copy.enable_live_entry_orders = False
        cfg_copy.enable_live_exit_orders = False
        cfg_copy.phase_c_allowed_tickers = []
    cfg_copy.enable_phase_c_actual_coinbase_submit = False
    cfg_copy.enable_phase_c_live_submit_infrastructure = True
    return cfg_copy


def run_phase_c_live_submit_dry_run(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    audit_path: str | Path = "logs/phase_c_live_submit.jsonl",
    simulate_ready_guard: bool = False,
    append_audit: bool = True,
) -> Dict[str, Any]:
    """Run a deterministic C.2.1 dry-run audit without Coinbase side effects.

    This validates the integration from guard -> payload -> submit-preparation ->
    audit log. It always passes submit_live=False and never provides a Coinbase
    client, so live_submission_attempted and live_order_submitted must remain
    false even if simulate_ready_guard=True.
    """
    from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness

    ticker = _normalize_ticker(ticker)
    dry_cfg = build_phase_c_dry_run_cfg(cfg, ticker=ticker, simulate_ready_guard=simulate_ready_guard)
    candidate = build_phase_c_dry_run_candidate(cfg=dry_cfg, ticker=ticker)
    guard_result = evaluate_phase_c_live_entry_readiness(
        cfg=dry_cfg,
        ticker=ticker,
        analysis=candidate["analysis"],
        execution_plan=candidate["execution_plan"],
        order_intent=candidate["order_intent"],
        live_risk_result=candidate["risk"],
        open_live_entry_orders_count=0,
        new_live_orders_this_cycle=0,
    )
    result = prepare_phase_c_live_entry_submission(
        cfg=dry_cfg,
        ticker=ticker,
        order_intent=candidate["order_intent"],
        guard_result=guard_result,
        coinbase_client=None,
        product_rules=candidate["product_rules"],
        submit_live=False,
    )
    result.update({
        "phase": "C21_live_submit_dry_run_audit",
        "diagnostic": True,
        "dry_run": True,
        "simulate_ready_guard": bool(simulate_ready_guard),
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "guard_result_full": _json_safe(guard_result),
        "safety_policy": {
            **(result.get("safety_policy") if isinstance(result.get("safety_policy"), dict) else {}),
            "c21_dry_run_no_coinbase_client": True,
            "c21_dry_run_submit_live_false": True,
            "diagnostic_record_not_an_order": True,
        },
    })
    if append_audit:
        append_phase_c_live_order_audit(audit_path, result)
    return _json_safe(result)


def append_phase_c_live_order_audit(path: str | Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_json_safe(payload), ensure_ascii=False) + "\n")


__all__ = [
    "build_phase_c_live_client_order_id",
    "build_phase_c_live_entry_payload",
    "submit_limit_buy_order",
    "prepare_phase_c_live_entry_submission",
    "build_mode_c_market_order_payload",
    "prepare_mode_c_market_order_submission",
    "build_phase_c_dry_run_candidate",
    "build_phase_c_dry_run_cfg",
    "run_phase_c_live_submit_dry_run",
    "append_phase_c_live_order_audit",
]
