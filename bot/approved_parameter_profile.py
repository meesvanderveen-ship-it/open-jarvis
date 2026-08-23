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

    expected_hash = str(env_map.get(APPROVED_PARAMETER_PROFILE_HASH_ENV, "")).strip().lower()
    if not expected_hash:
        log.error("approved_parameter_profile rejected: missing expected hash")
        raise ValueError("APPROVED_PARAMETER_PROFILE_HASH ontbreekt terwijl ENABLE_APPROVED_PARAMETER_PROFILE=true")

    if not profile_path.exists():
        log.error("approved_parameter_profile rejected: profile file missing")
        raise ValueError("state/approved_parameter_profile.json ontbreekt terwijl ENABLE_APPROVED_PARAMETER_PROFILE=true")

    actual_hash = sha256_file(profile_path)
    if actual_hash.lower() != expected_hash:
        log.error("approved_parameter_profile rejected: hash mismatch")
        raise ValueError("APPROVED_PARAMETER_PROFILE_HASH mismatch voor state/approved_parameter_profile.json")

    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("approved_parameter_profile rejected: invalid json")
        raise ValueError("state/approved_parameter_profile.json bevat ongeldige JSON") from exc

    params = _extract_parameters(payload)
    unknown = sorted(set(params) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        log.error("approved_parameter_profile rejected: unknown keys %s", ",".join(unknown))
        raise ValueError("approved_parameter_profile bevat niet-whitelisted keys: " + ",".join(unknown))

    values = {str(key): str(value).strip() for key, value in params.items()}
    empty = sorted(key for key, value in values.items() if value == "")
    if empty:
        log.error("approved_parameter_profile rejected: empty values %s", ",".join(empty))
        raise ValueError("approved_parameter_profile bevat lege waarden: " + ",".join(empty))

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
