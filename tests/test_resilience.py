"""Tests voor bot/resilience.py.

Draait zonder netwerk en zonder echte wachttijd: de slaapfunctie wordt
vervangen door een recorder, en de circuit breaker krijgt een handmatige klok.
Dat is bewust -- een test die `time.sleep` echt uitvoert meet niets extra en
maakt de suite alleen traag.
"""

from __future__ import annotations

import random

import pytest

from bot.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RetryExhausted,
    RetryPolicy,
    describe_failure,
    is_transient,
    policies_snapshot,
    retry_call,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Recorder:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


# --------------------------------------------------------------------------
# Classificatie
# --------------------------------------------------------------------------


class _HttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class _AuthenticationError(Exception):
    """Naam komt overeen met de klasse die openai/anthropic gebruiken."""


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_status_codes_are_retried(status: int) -> None:
    assert is_transient(_HttpError(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_errors_are_never_retried(status: int) -> None:
    assert is_transient(_HttpError(status)) is False


def test_network_level_oserror_is_transient() -> None:
    assert is_transient(ConnectionResetError("verbinding verbroken")) is True
    assert is_transient(TimeoutError("te traag")) is True
    assert is_transient(OSError("winerror 10054")) is True


def test_authentication_error_is_permanent_even_without_status_code() -> None:
    """Een ingetrokken sleutel 60 keer opnieuw proberen helpt niemand."""
    assert is_transient(_AuthenticationError("key revoked")) is False


def test_unknown_error_is_not_retried() -> None:
    """Bij twijfel niet herhalen: dubbel insturen is erger dan een foutmelding."""
    assert is_transient(ValueError("iets onbekends")) is False


# --------------------------------------------------------------------------
# RetryPolicy
# --------------------------------------------------------------------------


def test_backoff_grows_exponentially_and_is_capped() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay=1.0, multiplier=2.0, max_delay=8.0, jitter=0.0)

    waits = [policy.delay_for(n) for n in range(1, 7)]

    assert waits[0] == 0.0, "de eerste poging wacht niet"
    assert waits[1:] == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_jitter_stays_inside_the_configured_band() -> None:
    policy = RetryPolicy(base_delay=10.0, multiplier=1.0, max_delay=10.0, jitter=0.5)
    rng = random.Random(1234)

    for _ in range(200):
        wait = policy.delay_for(2, rng=rng)
        assert 5.0 <= wait <= 15.0


def test_policy_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTRETRY_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("TESTRETRY_BASE_DELAY", "3.5")
    monkeypatch.setenv("TESTRETRY_COOLDOWN", "90")

    policy = RetryPolicy.from_env("TESTRETRY")

    assert policy.max_attempts == 7
    assert policy.base_delay == pytest.approx(3.5)
    assert policy.cooldown_seconds == pytest.approx(90.0)


def test_env_beats_a_caller_supplied_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anders staat een instelling wel in .env maar doet hij niets.

    De aanroepsite geeft haar eigen standaard mee (de hoofdlus wil bijvoorbeeld
    30 seconden in plaats van 2). Die standaard mag de gebruikersinstelling
    niet overschrijven, want dan is 'de cooldown is configureerbaar' onwaar.
    """
    monkeypatch.setenv("TESTRETRY_BASE_DELAY", "5")

    policy = RetryPolicy.from_env("TESTRETRY", base_delay=30.0)

    assert policy.base_delay == pytest.approx(5.0)


def test_caller_default_applies_when_the_env_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TESTRETRY_BASE_DELAY", raising=False)

    policy = RetryPolicy.from_env("TESTRETRY", base_delay=30.0)

    assert policy.base_delay == pytest.approx(30.0)


def test_policy_from_env_falls_back_on_nonsense(monkeypatch: pytest.MonkeyPatch) -> None:
    """Een typefout in .env mag geen crash zijn, wel een waarschuwing."""
    monkeypatch.setenv("TESTRETRY_MAX_ATTEMPTS", "veel")

    policy = RetryPolicy.from_env("TESTRETRY")

    assert policy.max_attempts == RetryPolicy.max_attempts


def test_policy_rejects_impossible_configuration() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(multiplier=0.5)


# --------------------------------------------------------------------------
# retry_call
# --------------------------------------------------------------------------


def test_successful_call_does_not_sleep() -> None:
    recorder = _Recorder()

    result = retry_call(lambda: "ok", description="testactie", sleep=recorder)

    assert result == "ok"
    assert recorder.waits == []


def test_transient_failure_is_retried_until_it_succeeds() -> None:
    recorder = _Recorder()
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _HttpError(503)
        return "eindelijk"

    policy = RetryPolicy(max_attempts=5, base_delay=1.0, multiplier=2.0, jitter=0.0)
    result = retry_call(flaky, description="testactie", policy=policy, sleep=recorder)

    assert result == "eindelijk"
    assert attempts["n"] == 3
    assert recorder.waits == [1.0, 2.0], "backoff loopt op tussen de pogingen"


def test_permanent_failure_is_raised_immediately_without_waiting() -> None:
    recorder = _Recorder()
    attempts = {"n": 0}

    def rejected() -> str:
        attempts["n"] += 1
        raise _HttpError(401)

    with pytest.raises(_HttpError):
        retry_call(rejected, description="testactie", sleep=recorder)

    assert attempts["n"] == 1, "een afgewezen sleutel wordt niet herhaald"
    assert recorder.waits == []


def test_exhausted_retries_raise_retryexhausted_with_the_last_cause() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=0.0)

    def always_down() -> str:
        raise _HttpError(502)

    with pytest.raises(RetryExhausted) as excinfo:
        retry_call(always_down, description="Coinbase-saldo opvragen", policy=policy, sleep=_Recorder())

    assert excinfo.value.attempts == 3
    assert isinstance(excinfo.value.last_error, _HttpError)
    assert "Coinbase-saldo opvragen" in str(excinfo.value)


def test_keyboard_interrupt_is_never_swallowed() -> None:
    def interrupted() -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        retry_call(interrupted, description="testactie", sleep=_Recorder())


def test_retry_exhausted_message_contains_no_call_arguments() -> None:
    """Foutmeldingen belanden in logbestanden; daar horen geen sleutels in."""
    secret = "sk-geheime-sleutel-mag-nooit-in-een-log"
    policy = RetryPolicy(max_attempts=2, base_delay=0.0, jitter=0.0)

    def call_with_secret() -> str:
        raise _HttpError(503)

    with pytest.raises(RetryExhausted) as excinfo:
        retry_call(call_with_secret, description="testactie", policy=policy, sleep=_Recorder())

    assert secret not in str(excinfo.value)


# --------------------------------------------------------------------------
# CircuitBreaker
# --------------------------------------------------------------------------


def test_breaker_opens_after_threshold_and_blocks_further_calls() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker("coinbase", failure_threshold=3, cooldown_seconds=60.0, clock=clock)

    for _ in range(3):
        breaker.before_call()
        breaker.record_failure()

    assert breaker.state == CircuitBreaker.OPEN
    with pytest.raises(CircuitBreakerOpen):
        breaker.before_call()


def test_breaker_half_opens_after_cooldown_and_closes_on_success() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker("coinbase", failure_threshold=2, cooldown_seconds=60.0, clock=clock)

    for _ in range(2):
        breaker.before_call()
        breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN

    clock.advance(60.0)
    assert breaker.state == CircuitBreaker.HALF_OPEN

    breaker.before_call()
    breaker.record_success()

    assert breaker.state == CircuitBreaker.CLOSED
    breaker.before_call()  # mag weer gewoon


def test_failed_probe_reopens_the_breaker_for_a_full_cooldown() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker("coinbase", failure_threshold=1, cooldown_seconds=30.0, clock=clock)

    breaker.before_call()
    breaker.record_failure()
    clock.advance(30.0)

    breaker.before_call()
    breaker.record_failure()

    assert breaker.state == CircuitBreaker.OPEN
    assert breaker.retry_after() == pytest.approx(30.0)


def test_half_open_allows_only_one_probe_at_a_time() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker("coinbase", failure_threshold=1, cooldown_seconds=10.0, clock=clock)
    breaker.before_call()
    breaker.record_failure()
    clock.advance(10.0)

    breaker.before_call()
    with pytest.raises(CircuitBreakerOpen):
        breaker.before_call()


def test_permanent_error_does_not_open_the_breaker() -> None:
    """Een verkeerde sleutel zegt niets over de bereikbaarheid van de provider."""
    clock = _FakeClock()
    breaker = CircuitBreaker("coinbase", failure_threshold=2, cooldown_seconds=60.0, clock=clock)

    for _ in range(5):
        with pytest.raises(_HttpError):
            retry_call(
                lambda: (_ for _ in ()).throw(_HttpError(401)),
                description="testactie",
                breaker=breaker,
                sleep=_Recorder(),
            )

    assert breaker.state == CircuitBreaker.CLOSED


def test_breaker_snapshot_is_json_safe_and_has_no_secrets() -> None:
    breaker = CircuitBreaker("coinbase", failure_threshold=2, cooldown_seconds=15.0)

    snapshot = breaker.snapshot()

    assert snapshot["name"] == "coinbase"
    assert snapshot["state"] == CircuitBreaker.CLOSED
    assert set(snapshot) == {
        "name",
        "state",
        "failures",
        "failure_threshold",
        "cooldown_seconds",
        "retry_after_seconds",
    }


# --------------------------------------------------------------------------
# Mensvriendelijke uitleg
# --------------------------------------------------------------------------


def test_describe_failure_distinguishes_rejected_from_unreachable() -> None:
    rejected = describe_failure(_HttpError(401))
    unreachable = describe_failure(ConnectionResetError("weg"))

    assert "afgewezen" in rejected.lower()
    assert "niet bereikbaar" in unreachable.lower()
    assert rejected != unreachable


def test_describe_failure_never_calls_a_network_problem_a_wrong_key() -> None:
    """De regel uit de opdracht: onbereikbaar is geen verkeerde sleutel."""
    message = describe_failure(TimeoutError("timeout"))

    assert "sleutel" not in message.lower()


def test_describe_failure_explains_rate_limit_and_provider_outage() -> None:
    assert "rate limit" in describe_failure(_HttpError(429)).lower()
    assert "storing" in describe_failure(_HttpError(503)).lower()


def test_policies_snapshot_is_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_RETRY_MAX_ATTEMPTS", raising=False)

    snapshot = policies_snapshot(RetryPolicy(max_attempts=3, base_delay=2.0, multiplier=2.0, jitter=0.0))

    assert snapshot["max_attempts"] == 3
    assert snapshot["example_waits_seconds"] == [0.0, 2.0, 4.0]
