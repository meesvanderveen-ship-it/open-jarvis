from __future__ import annotations

from typing import Any, Callable

from dashboard.backend.services.live_status import get_live_status
from dashboard.backend.services.pipeline_health import get_pipeline_health
from dashboard.backend.services.util import dig

_BOOL_TRUE_IS_DANGER: Callable[[Any], bool] = lambda v: v is True
_BOOL_FALSE_IS_DANGER: Callable[[Any], bool] = lambda v: v is False
_TRUTHY_IS_DANGER: Callable[[Any], bool] = lambda v: bool(v)
_NONEMPTY_LIST_IS_DANGER: Callable[[Any], bool] = lambda v: isinstance(v, list) and len(v) > 0

_TONE_RANK = {"safe": 0, "info": 0, "warning": 1, "danger": 2}


def _max_tone(a: str, b: str) -> str:
    return a if _TONE_RANK.get(a, 0) >= _TONE_RANK.get(b, 0) else b


# (label, dotted-path-in-source, source, is_danger predicate, category)
# NOTE: `state/runtime_mutation.lock` ("Stale lock likely") and the
# restart-readiness verdicts ("Do not run bot yet" / "Safe to restart") are
# intentionally NOT driven by a blind truthy/falsy predicate here — see
# `_assess_runtime_lock()` and `_operational_health()` below. Those fields
# answer "is it safe to restart/do maintenance right now", which is a
# different question from "is the bot healthy", and a healthy, actively
# running bot will *always* hold its own runtime mutation lock and *always*
# report "not safe to restart" — that is expected, not a danger signal.
_GUARD_DEFS: list[tuple[str, str, str, Callable[[Any], bool], str]] = [
    ("Stale lock detected (process lock)", "stale_lock_detected", "live", _TRUTHY_IS_DANGER, "process"),
    ("PID consistent (systemd vs lock)", "pid_consistent", "live", _BOOL_FALSE_IS_DANGER, "process"),
    ("Service restart attempted by dashboard tooling", "service_restart_attempted", "live", _TRUTHY_IS_DANGER, "process"),
    ("Coinbase call attempted by dashboard tooling", "coinbase_call_attempted", "live", _TRUTHY_IS_DANGER, "coinbase"),
    ("State write performed by dashboard tooling", "state_write_performed", "live", _TRUTHY_IS_DANGER, "process"),
    (".env write performed by dashboard tooling", "env_write_performed", "live", _TRUTHY_IS_DANGER, "process"),
    ("Read-only mode confirmed (live status tool)", "read_only", "live", _BOOL_FALSE_IS_DANGER, "process"),
    ("Read-only mode confirmed (pipeline health tool)", "read_only", "pipeline", _BOOL_FALSE_IS_DANGER, "process"),
    ("Market order flags enabled", "market_order_flags_enabled", "pipeline", _NONEMPTY_LIST_IS_DANGER, "danger-zone"),
    ("Operator ACK required", "ack_required", "pipeline", _TRUTHY_IS_DANGER, "operator"),
    ("Positions with risk incomplete", "positions_risk_incomplete", "pipeline", _NONEMPTY_LIST_IS_DANGER, "danger-zone"),
    ("Approved profile hash valid", "approved_profile_status.hash_valid", "live", _BOOL_FALSE_IS_DANGER, "config"),
    ("Approved profile loaded", "approved_profile_status.loaded", "live", _BOOL_FALSE_IS_DANGER, "config"),
]

# Known restart/maintenance blockers from show_full_pipeline_health.py that
# have a context-aware interpretation. Anything not listed here defaults to
# "danger" — an unrecognised blocker is never silently downgraded.
_BLOCKER_EXPLAINERS: dict[str, str] = {
    "runtime_mutation_lock_held": (
        "state/runtime_mutation.lock is held — expected while the main loop "
        "is actively running. Only a real problem if the holder is not the "
        "live, PID-consistent service."
    ),
}


def _service_looks_active(live: dict) -> bool:
    systemd_status = str(live.get("systemd_service_status") or "")
    return systemd_status.lower().startswith("active") and bool(live.get("pid_consistent"))


def _assess_runtime_lock(live: dict, pipeline: dict) -> dict:
    """Correlate state/runtime_mutation.lock's hold-state with whether the
    actively running, PID-consistent service plausibly explains it.

    `pre_live_current_state.py`'s lock check is a real-time, non-blocking
    flock() probe — never stale data — but "held" alone does not mean
    "stale" or "dangerous": the bot's own main loop holds this lock for the
    entire duration it runs. Only treat it as dangerous when held *without*
    a live, PID-consistent service to explain it.
    """
    runtime_lock = dig(pipeline, "current_state.runtime_lock", {}) or {}
    held = runtime_lock.get("held")
    verifiable = runtime_lock.get("verifiable")
    service_active = _service_looks_active(live)

    if held and service_active:
        return {
            "status": "held_by_running_service",
            "tone": "info",
            "detail": (
                "Lock is held, and systemd reports the service active with a "
                "PID-consistent process — this is the expected state while "
                "the bot is running, not a stale lock."
            ),
            "path": runtime_lock.get("path"),
        }
    if held:
        return {
            "status": "held_possibly_stale",
            "tone": "danger",
            "detail": (
                "Lock is held, but the service does not look consistently "
                "active right now (systemd status or PID mismatch) — this "
                "needs operator review before assuming it is benign."
            ),
            "path": runtime_lock.get("path"),
        }
    if verifiable is False:
        return {
            "status": "unverifiable",
            "tone": "warning",
            "detail": "Could not verify the runtime mutation lock state.",
            "path": runtime_lock.get("path"),
        }
    return {
        "status": "not_held",
        "tone": "safe",
        "detail": "Runtime mutation lock is free.",
        "path": runtime_lock.get("path"),
    }


def _annotate_blockers(blockers: list, live: dict, pipeline: dict, runtime_lock_assessment: dict) -> list[dict]:
    annotated = []
    for blocker in blockers:
        if blocker == "runtime_mutation_lock_held":
            annotated.append(
                {
                    "blocker": blocker,
                    "tone": runtime_lock_assessment["tone"],
                    "detail": runtime_lock_assessment["detail"],
                }
            )
            continue
        annotated.append(
            {
                "blocker": blocker,
                "tone": "danger",
                "detail": _BLOCKER_EXPLAINERS.get(
                    blocker,
                    "Reported by show_full_pipeline_health.py as a restart/maintenance "
                    "blocker; not yet correlated by the dashboard, treat as real.",
                ),
            }
        )
    return annotated


def _operational_health(live: dict, pipeline: dict) -> dict:
    """Is the bot healthy and running right now? Deliberately independent of
    show_full_pipeline_health.py's restart-readiness verdict
    (`pipeline_health`/`safe_to_restart`/`do_not_run_bot_yet`), which answers
    a different question and is expected to say "not safe to restart" any
    time the bot is legitimately running.
    """
    tone = "safe"
    reasons: list[str] = []

    run_health = str(live.get("run_health") or "").lower()
    if run_health == "critical":
        tone = _max_tone(tone, "danger")
        reasons.append(f"run_health={run_health}")
    elif run_health == "warning":
        tone = _max_tone(tone, "warning")
        reasons.append(f"run_health={run_health}")

    systemd_status = str(live.get("systemd_service_status") or "")
    if not systemd_status.lower().startswith("active"):
        tone = _max_tone(tone, "danger")
        reasons.append(f"systemd_service_status={systemd_status!r}")

    if live.get("pid_consistent") is False:
        tone = _max_tone(tone, "danger")
        reasons.append("pid_consistent=false")

    if live.get("stale_lock_detected"):
        tone = _max_tone(tone, "danger")
        reasons.append("stale_lock_detected=true (process lock)")

    errors_by_type = live.get("errors_by_type") or {}
    if errors_by_type:
        tone = _max_tone(tone, "warning")
        reasons.append(f"errors_by_type={errors_by_type}")

    risk_incomplete = dig(pipeline, "current_state.risk_incomplete_positions", []) or []
    if risk_incomplete:
        tone = _max_tone(tone, "danger")
        reasons.append(f"risk_incomplete_positions={risk_incomplete}")

    unrecognised = dig(pipeline, "current_state.unrecognised_position_tickers", []) or []
    if unrecognised:
        tone = _max_tone(tone, "warning")
        reasons.append(f"unrecognised_position_tickers={unrecognised}")

    if not reasons:
        reasons.append("no operational issues detected")

    return {"tone": tone, "reasons": reasons}


def _status_for(value: Any, is_danger: Callable[[Any], bool]) -> str:
    if value is None:
        return "info"
    return "danger" if is_danger(value) else "safe"


def get_risk_guards() -> dict:
    live = get_live_status()
    pipeline = get_pipeline_health()
    sources = {"live": live, "pipeline": pipeline}

    guards = []
    for label, path, source_name, is_danger, category in _GUARD_DEFS:
        source = sources[source_name]
        value = dig(source, path)
        guards.append(
            {
                "guard": label,
                "category": category,
                "value": value,
                "status": _status_for(value, is_danger),
                "source": source_name,
            }
        )

    runtime_lock_assessment = _assess_runtime_lock(live, pipeline)
    guards.append(
        {
            "guard": "Runtime mutation lock (state/runtime_mutation.lock)",
            "category": "process",
            "value": runtime_lock_assessment["status"],
            "status": runtime_lock_assessment["tone"],
            "source": "pipeline+live",
            "note": runtime_lock_assessment["detail"],
        }
    )
    guards.append(
        {
            "guard": "Do not run bot yet (restart-readiness verdict)",
            "category": "danger-zone",
            "value": pipeline.get("do_not_run_bot_yet"),
            "status": "info",
            "source": "pipeline",
            "note": (
                "This answers 'is it safe to restart/do maintenance right now', "
                "not 'is the bot healthy'. A healthy, running bot normally shows "
                "true here because it is already running."
            ),
        }
    )
    guards.append(
        {
            "guard": "Safe to restart (restart-readiness verdict)",
            "category": "danger-zone",
            "value": pipeline.get("safe_to_restart"),
            "status": "info",
            "source": "pipeline",
            "note": "See note on 'Do not run bot yet' above — same restart-readiness axis.",
        }
    )

    danger_count = sum(1 for g in guards if g["status"] == "danger")

    raw_blockers = pipeline.get("blockers", []) or []
    annotated_blockers = _annotate_blockers(raw_blockers, live, pipeline, runtime_lock_assessment)
    operational_health = _operational_health(live, pipeline)

    return {
        "guards": guards,
        "danger_count": danger_count,
        "operational_health": operational_health,
        "pipeline_health": pipeline.get("pipeline_health"),
        "blockers": raw_blockers,
        "annotated_blockers": annotated_blockers,
        "runtime_lock_assessment": runtime_lock_assessment,
        "operator_checklist": pipeline.get("operator_checklist", []),
        "operator_action": pipeline.get("operator_action"),
        "readiness": live.get("readiness"),
        "latest_readiness_recommendation": live.get("latest_readiness_recommendation"),
        "market_order_flags_enabled": pipeline.get("market_order_flags_enabled"),
        "replication_status": live.get("replication_status"),
    }
