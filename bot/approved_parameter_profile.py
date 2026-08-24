from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping


APPROVED_PARAMETER_PROFILE_PATH = Path("state/approved_parameter_profile.json")
ENABLE_APPROVED_PARAMETER_PROFILE_ENV = "ENABLE_APPROVED_PARAMETER_PROFILE"
APPROVED_PARAMETER_PROFILE_HASH_ENV = "APPROVED_PARAMETER_PROFILE_HASH"

APPROVED_PARAMETER_PROFILE_WHITELIST = {
    "MAX_SPREAD_PCT",
    "DEFAULT_QUOTE_SIZE_USDC",
    "MAX_NOTIONAL_USD",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "AUTONOMOUS_MAX_OPEN_ORDERS",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
    "MAX_OPEN_POSITIONS",
    "PHASE_C_MAX_ORDER_QUOTE",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "STOP_DISTANCE_PCT",
    "PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT",
    "PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT",
    "JUDGE_MIN_GATE_CONFIDENCE",
    "SMALL_PROBE_MAX_BEAR_BULL_GAP",
    "SMALL_PROBE_REQUIRE_HTF_BOTH_TIMEFRAMES",
    "SMALL_PROBE_TC_SYNTH_MIN",
    "SMALL_PROBE_TC_BULL_MIN",
    "SMALL_PROBE_TC_BREAKOUT_CONFIRMATION_MIN",
    "SMALL_PROBE_TC_VOL_15M_MIN",
    "SMALL_PROBE_TC_VOL_1H_MIN",
    "SMALL_PROBE_RC_SYNTH_MIN",
    "SMALL_PROBE_RC_BULL_MIN",
    "SMALL_PROBE_RC_BREAKOUT_CONFIRMATION_MIN",
    "SMALL_PROBE_RC_VOL_15M_MIN",
    "SMALL_PROBE_RC_VOL_1H_MIN",
}

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovedParameterProfileResult:
    status: str
    path: str
    values: Dict[str, str]
    reason: str = ""
    actual_hash: str = ""
    expected_hash: str = ""


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_parameters(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("approved_parameter_profile must be a JSON object")
    if "parameters" in payload:
        params = payload.get("parameters")
        if not isinstance(params, dict):
            raise ValueError("approved_parameter_profile.parameters must be an object")
        return dict(params)
    return dict(payload)


def load_approved_parameter_profile(
    *,
    path: str | Path = APPROVED_PARAMETER_PROFILE_PATH,
    env: Mapping[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> ApprovedParameterProfileResult:
    env_map = env if env is not None else os.environ
    log = logger if logger is not None else LOGGER
    profile_path = Path(path)

    enabled = str(env_map.get(ENABLE_APPROVED_PARAMETER_PROFILE_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        result = ApprovedParameterProfileResult(status="skipped", path=str(profile_path), values={}, reason="disabled")
        log.info("approved_parameter_profile skipped: disabled")
        return result

    # Every rejection below returns status="rejected" with a reason instead of
    # raising. This profile is an optional, whitelisted enhancement layer on top
    # of already-functional .env defaults -- __post_init__ falls back to those
    # defaults whenever status != "loaded". Raising here previously took down
    # BotConfig() construction entirely, which takes down the whole trading bot
    # (including position monitoring and exit logic) over a rejected *optional*
    # layer. Confirmed live 2026-07-08: the autonomous_parameter_governor wrote a
    # new approved profile without anyone updating .env's pinned hash to match
    # (nothing in this codebase does that automatically -- see
    # bot/autonomous_parameter_governor.py, which deliberately never touches
    # .env, since the hash pin is supposed to represent a human approving the
    # governor's own proposed change). The very next unrelated restart then
    # crash-looped indefinitely instead of just running on baseline .env values,
    # leaving a stop-breached position with zero monitoring for hours. The other
    # two callers of this function (bot/live_learning_orchestrator.py,
    # tools/show_full_autonomous_run_readiness.py) already only ever read
    # result.status/result.reason expecting exactly this graceful contract --
    # config.py was the one caller that didn't defend against a raise.
    expected_hash = str(env_map.get(APPROVED_PARAMETER_PROFILE_HASH_ENV, "")).strip().lower()
    if not expected_hash:
        log.error("approved_parameter_profile rejected: missing expected hash")
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="missing_expected_hash")

    if not profile_path.exists():
        log.error("approved_parameter_profile rejected: profile file missing")
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="profile_file_missing", expected_hash=expected_hash)

    actual_hash = sha256_file(profile_path)
    if actual_hash.lower() != expected_hash:
        log.error("approved_parameter_profile rejected: hash mismatch")
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="hash_mismatch", actual_hash=actual_hash, expected_hash=expected_hash)

    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.error("approved_parameter_profile rejected: invalid json")
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="invalid_json", actual_hash=actual_hash, expected_hash=expected_hash)

    try:
        params = _extract_parameters(payload)
    except ValueError as exc:
        log.error("approved_parameter_profile rejected: %s", exc)
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason=f"malformed_payload:{exc}", actual_hash=actual_hash, expected_hash=expected_hash)
    unknown = sorted(set(params) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        log.error("approved_parameter_profile rejected: unknown keys %s", ",".join(unknown))
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="unknown_keys:" + ",".join(unknown), actual_hash=actual_hash, expected_hash=expected_hash)

    values = {str(key): str(value).strip() for key, value in params.items()}
    empty = sorted(key for key, value in values.items() if value == "")
    if empty:
        log.error("approved_parameter_profile rejected: empty values %s", ",".join(empty))
        return ApprovedParameterProfileResult(status="rejected", path=str(profile_path), values={}, reason="empty_values:" + ",".join(empty), actual_hash=actual_hash, expected_hash=expected_hash)

    result = ApprovedParameterProfileResult(
        status="loaded",
        path=str(profile_path),
        values=values,
        actual_hash=actual_hash,
        expected_hash=expected_hash,
    )
    log.info("approved_parameter_profile loaded: %s", ",".join(sorted(values)))
    return result


__all__ = [
    "APPROVED_PARAMETER_PROFILE_HASH_ENV",
    "APPROVED_PARAMETER_PROFILE_PATH",
    "APPROVED_PARAMETER_PROFILE_WHITELIST",
    "ENABLE_APPROVED_PARAMETER_PROFILE_ENV",
    "ApprovedParameterProfileResult",
    "load_approved_parameter_profile",
    "sha256_file",
]
