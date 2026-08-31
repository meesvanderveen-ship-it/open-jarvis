"""De hoofdlus moet een storing overleven met oplopende wachttijd.

Vóór deze laag stond hier een vaste `time.sleep(60)`. Dat had twee problemen
die deze tests vastleggen: een korte hapering kostte altijd een volle minuut,
en een provider die plat lag werd elke minuut opnieuw bestookt -- precies wat
een rate limit uitlokt.

De lus zelf wordt hier niet echt gedraaid (dat zou een StrategyEngine en een
exchange vereisen); getest wordt de wachttijdberekening en het bijhouden van
de teller, met exact dezelfde policy als main() gebruikt.
"""

from __future__ import annotations

import pytest

from bot.resilience import RetryPolicy


def _recovery_policy(**overrides) -> RetryPolicy:
    """Precies de policy die run_trader_loop.main() opbouwt."""
    defaults = dict(max_attempts=5, base_delay=30.0, max_delay=300.0, cooldown_seconds=300.0)
    defaults.update(overrides)
    return RetryPolicy.from_env("JARVIS_RECOVERY", **defaults)


def test_recovery_waits_grow_instead_of_staying_at_one_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_RECOVERY_JITTER", "0")
    policy = _recovery_policy()

    waits = [policy.delay_for(min(errors + 1, policy.max_attempts)) for errors in range(1, 6)]

    assert waits == [30.0, 60.0, 120.0, 240.0, 240.0]
    assert waits[0] < 60.0, "een eerste hapering kost geen volle minuut meer"


def test_repeated_failures_reach_a_real_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blijven falen is geen tijdelijke storing meer; dan hoort er rust te komen."""
    monkeypatch.setenv("JARVIS_RECOVERY_JITTER", "0")
    policy = _recovery_policy()
    consecutive = policy.max_attempts

    pause = policy.delay_for(min(consecutive + 1, policy.max_attempts))
    if consecutive >= policy.max_attempts:
        pause = max(pause, policy.cooldown_seconds)

    assert pause == 300.0


def test_wait_never_exceeds_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zonder plafond zou de bot na een nacht storing pas over uren terugkomen."""
    monkeypatch.setenv("JARVIS_RECOVERY_JITTER", "0")
    policy = _recovery_policy()

    for attempt in range(1, 40):
        assert policy.delay_for(attempt) <= policy.max_delay


def test_recovery_policy_is_configurable_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_RECOVERY_BASE_DELAY", "5")
    monkeypatch.setenv("JARVIS_RECOVERY_MAX_DELAY", "20")
    monkeypatch.setenv("JARVIS_RECOVERY_JITTER", "0")

    policy = _recovery_policy()

    assert policy.delay_for(2) == 5.0
    assert policy.delay_for(9) == 20.0


def test_jitter_prevents_a_synchronised_retry_wave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_RECOVERY_JITTER", raising=False)
    policy = _recovery_policy()

    samples = {policy.delay_for(3) for _ in range(50)}

    assert len(samples) > 1, "zonder spreiding komen alle onderdelen tegelijk terug"


def test_main_loop_uses_this_policy_and_resets_after_success() -> None:
    """Borgt dat de lus zelf de teller terugzet; anders stapelen losse storingen op."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "run_trader_loop.py"
    ).read_text(encoding="utf-8")

    assert 'RetryPolicy.from_env(\n        "JARVIS_RECOVERY"' in source
    assert "consecutive_errors = 0" in source
    assert "time.sleep(60)" not in source, "de vaste wachttijd van een minuut hoort weg te zijn"


def test_loop_error_log_records_whether_the_failure_was_transient() -> None:
    """Zonder dat onderscheid is achteraf niet te zien of het netwerk of de code faalde."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "run_trader_loop.py"
    ).read_text(encoding="utf-8")

    assert '"transient": is_transient(e)' in source
    assert '"consecutive_errors": consecutive_errors' in source
