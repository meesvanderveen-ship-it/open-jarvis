from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bot.approved_parameter_profile import load_approved_parameter_profile
from bot.governance_constants import (
    C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_ENV,
    C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
    D3_CONTROLLED_LIVE_EXIT_ACK_ENV,
    D3_CONTROLLED_LIVE_EXIT_ACK_VALUE,
    MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV,
    MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
    MODE_C_MARKET_ORDER_ACK_ENV,
    MODE_C_MARKET_ORDER_ACK_VALUE,
)
from bot.live_order_size_policy import (
    EXPLORATION_MAX_ORDER_QUOTE_USDC,
    EXPLORATION_MIN_ORDER_QUOTE_USDC,
    MAX_LIVE_EXIT_ORDER_QUOTE_USDC,
    MAX_LIVE_ORDER_QUOTE_USDC,
    MIN_LIVE_ORDER_QUOTE_USDC,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency on production hosts
    load_dotenv = None


def _load_project_dotenv() -> None:
    """
    Laad expliciet het .env-bestand vanuit de projectroot.

    Waarom:
    - systemd kan EnvironmentFile anders interpreteren dan python-dotenv
    - load_dotenv() zonder override laat bestaande (mogelijk corrupte) env-vars staan
    - expliciet pad + override=True maakt handmatige runs en systemd-runs consistent

    Testbaarheid:
    - BOT_CONFIG_SKIP_DOTENV=true laat pytest/diagnostische tools een volledig
      geïsoleerde omgeving bouwen zonder dat de echte server-.env de monkeypatch
      of tijdelijke testconfig overschrijft. Gebruik dit niet in productie.
    """
    if os.getenv("BOT_CONFIG_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return

    if load_dotenv is None:
        return

    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        # Fallback: behoud oud gedrag als .env onverwacht niet op projectroot staat
        load_dotenv(override=True)


_load_project_dotenv()


def _split_csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _normalize_tickers(values: list[str]) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()

    for value in values:
        t = value.upper().strip()
        if not t:
            continue
        if "-" not in t:
            raise ValueError(f"Ongeldig tickerformaat: {value}. Verwacht bv. BTC-USDC")
        if t in seen:
            continue
        seen.add(t)
        tickers.append(t)

    return tickers


def _unique_ticker_universe(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for ticker in _normalize_tickers(list(group or [])):
            if ticker in seen:
                continue
            seen.add(ticker)
            out.append(ticker)
    return out


def configured_ticker_universe(cfg: object) -> list[str]:
    """Return the normal workflow ticker universe from configured ticker lists.

    Incident-scoped tools may still use their own exact ticker lists. The normal
    entry/fill/D2/D3 workflow should use this broader configured universe.
    """
    return _unique_ticker_universe(
        list(getattr(cfg, "allowed_tickers", []) or []),
        list(getattr(cfg, "phase_c_allowed_tickers", []) or []),
        list(getattr(cfg, "autonomous_allowed_tickers", []) or []),
    )


def effective_phase_c_allowed_tickers(cfg: object) -> list[str]:
    return configured_ticker_universe(cfg)


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"{name} ontbreekt")

    value = value.strip()
    if not value:
        raise ValueError(f"{name} ontbreekt")

    return value


def _get_optional_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _get_optional_secret_env(name: str, default: str = "") -> str:
    """Return an optional secret without forcing it to be present.

    Used for providers that are no longer part of the primary routing. This keeps
    BotConfig usable when ANTHROPIC_API_KEY is intentionally blank/removed.
    """
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _get_int_env(name: str, default: str) -> int:
    raw = _get_optional_env(name, default)
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} moet een integer zijn, ontvangen: {raw}") from e


def _get_decimal_env(name: str, default: str) -> Decimal:
    raw = _get_optional_env(name, default)
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"{name} moet een decimaal getal zijn, ontvangen: {raw}") from e


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class BotConfig:
    execution_mode: str = field(default_factory=lambda: _get_optional_env("EXECUTION_MODE", "paper").lower())

    allowed_tickers: list[str] = field(default_factory=lambda: _normalize_tickers(
        _split_csv(_get_optional_env(
            "ALLOWED_TICKERS",
            (
                "BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,ADA-USDC,LINK-USDC,AVAX-USDC,"
                "DOGE-USDC,SUI-USDC,LTC-USDC,HBAR-USDC,ATOM-USDC,NEAR-USDC,APT-USDC,"
                "INJ-USDC,ARB-USDC,OP-USDC,UNI-USDC"
            ),
        ))
    ))

    primary_interval_hours: int = field(default_factory=lambda: _get_int_env("PRIMARY_INTERVAL_HOURS", "4"))
    cooldown_minutes: int = field(default_factory=lambda: _get_int_env("COOLDOWN_MINUTES", "240"))
    max_open_positions: int = field(default_factory=lambda: _get_int_env("MAX_OPEN_POSITIONS", "3"))

    max_daily_loss_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_DAILY_LOSS_USDC", "30.00"))
    min_live_order_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("MIN_LIVE_ORDER_QUOTE_USDC", str(MIN_LIVE_ORDER_QUOTE_USDC)))
    max_live_order_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_LIVE_ORDER_QUOTE_USDC", str(MAX_LIVE_ORDER_QUOTE_USDC)))
    default_quote_size_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("DEFAULT_QUOTE_SIZE_USDC", "50.00"))
    max_notional_usd: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_NOTIONAL_USD", "100.00"))
    enable_dynamic_entry_sizing: bool = field(default_factory=lambda: _get_bool_env("ENABLE_DYNAMIC_ENTRY_SIZING", True))
    min_dynamic_entry_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("MIN_DYNAMIC_ENTRY_QUOTE_USDC", str(MIN_LIVE_ORDER_QUOTE_USDC)))
    max_dynamic_entry_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_DYNAMIC_ENTRY_QUOTE_USDC", str(MAX_LIVE_ORDER_QUOTE_USDC)))
    max_spread_pct: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_SPREAD_PCT", "0.0100"))

    coinbase_api_host: str = field(default_factory=lambda: _get_optional_env("COINBASE_API_HOST", "api.coinbase.com"))
    coinbase_timeout_seconds: int = field(default_factory=lambda: _get_int_env("COINBASE_TIMEOUT_SECONDS", "15"))

    # DeepSeek is optional from C.1.1 onward. GPT nano remains the primary cheap gate/watch layer.
    # If DeepSeek is disabled, no DeepSeek API key is required and no DeepSeek calls are made.
    enable_deepseek_preprocess: bool = field(default_factory=lambda: _get_bool_env("ENABLE_DEEPSEEK_PREPROCESS", False))
    deepseek_api_key: str = field(default_factory=lambda: _get_optional_secret_env("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: _get_optional_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"))
    deepseek_model: str = field(default_factory=lambda: _get_optional_env("DEEPSEEK_MODEL", "deepseek-chat"))

    openai_api_key: str = field(default_factory=lambda: _get_required_env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _get_optional_env("OPENAI_MODEL", "gpt-5.4-mini"))
    openai_analyst_model: str = field(default_factory=lambda: _get_optional_env("OPENAI_ANALYST_MODEL", _get_optional_env("OPENAI_MODEL", "gpt-5.4-mini")))
    openai_judge_model: str = field(default_factory=lambda: _get_optional_env("OPENAI_JUDGE_MODEL", "gpt-5.5"))
    openai_trade_planner_model: str = field(default_factory=lambda: _get_optional_env("OPENAI_TRADE_PLANNER_MODEL", _get_optional_env("OPENAI_JUDGE_MODEL", "gpt-5.5")))
    openai_execution_planner_model: str = field(default_factory=lambda: _get_optional_env("OPENAI_EXECUTION_PLANNER_MODEL", _get_optional_env("OPENAI_JUDGE_MODEL", "gpt-5.5")))

    # Claude/Anthropic is no longer required. From C.1.1 it is also explicitly gated
    # by ENABLE_ANTHROPIC_FALLBACK so an old key in .env cannot cause repeated billing errors.
    enable_anthropic_fallback: bool = field(default_factory=lambda: _get_bool_env("ENABLE_ANTHROPIC_FALLBACK", False))
    anthropic_api_key: str = field(default_factory=lambda: _get_optional_secret_env("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: _get_optional_env("ANTHROPIC_MODEL", "claude-opus-4-6"))

    news_enabled: bool = field(default_factory=lambda: _get_bool_env("NEWS_ENABLED", True))
    news_timeout_seconds: int = field(default_factory=lambda: _get_int_env("NEWS_TIMEOUT_SECONDS", "12"))
    news_lookback_hours: int = field(default_factory=lambda: _get_int_env("NEWS_LOOKBACK_HOURS", "48"))
    news_max_items_per_feed: int = field(default_factory=lambda: _get_int_env("NEWS_MAX_ITEMS_PER_FEED", "15"))
    news_max_headlines: int = field(default_factory=lambda: _get_int_env("NEWS_MAX_HEADLINES", "8"))
    fng_enabled: bool = field(default_factory=lambda: _get_bool_env("FNG_ENABLED", True))
    fng_api_url: str = field(default_factory=lambda: _get_optional_env("FNG_API_URL", "https://api.alternative.me/fng/"))
    news_rss_feeds: str = field(default_factory=lambda: _get_optional_env(
        "NEWS_RSS_FEEDS",
        "https://www.coindesk.com/arc/outboundfeeds/rss/,https://cointelegraph.com/rss",
    ))

    log_level: str = field(default_factory=lambda: _get_optional_env("LOG_LEVEL", "INFO").upper())

    # Nieuwe configuratie voor selectie / triage / ranking
    max_candidates_for_deep_analysis: int = field(default_factory=lambda: _get_int_env("MAX_CANDIDATES_FOR_DEEP_ANALYSIS", "5"))
    max_candidates_for_deepseek_gate: int = field(default_factory=lambda: _get_int_env("MAX_CANDIDATES_FOR_DEEPSEEK_GATE", "10"))
    max_priority_candidates: int = field(default_factory=lambda: _get_int_env("MAX_PRIORITY_CANDIDATES", "3"))
    enable_candidate_ranking: bool = field(default_factory=lambda: _get_bool_env("ENABLE_CANDIDATE_RANKING", True))
    enable_strict_meanrev_postfilter: bool = field(default_factory=lambda: _get_bool_env("ENABLE_STRICT_MEANREV_POSTFILTER", True))
    enable_market_breadth_relaxation: bool = field(default_factory=lambda: _get_bool_env("ENABLE_MARKET_BREADTH_RELAXATION", True))
    breadth_relaxation_min_tickers: int = field(default_factory=lambda: _get_int_env("BREADTH_RELAXATION_MIN_TICKERS", "3"))
    watch_promotion_memory_cycles: int = field(default_factory=lambda: _get_int_env("WATCH_PROMOTION_MEMORY_CYCLES", "2"))

    # Nieuwe configuratie voor LLM output hygiene / logging
    llm_raw_logging_enabled: bool = field(default_factory=lambda: _get_bool_env("LLM_RAW_LOGGING_ENABLED", True))
    llm_corrupt_logging_enabled: bool = field(default_factory=lambda: _get_bool_env("LLM_CORRUPT_LOGGING_ENABLED", True))
    llm_max_raw_chars: int = field(default_factory=lambda: _get_int_env("LLM_MAX_RAW_CHARS", "12000"))
    llm_corrupt_max_raw_chars: int = field(default_factory=lambda: _get_int_env("LLM_CORRUPT_MAX_RAW_CHARS", "6000"))
    llm_provider_error_logging_enabled: bool = field(default_factory=lambda: _get_bool_env("LLM_PROVIDER_ERROR_LOGGING_ENABLED", True))
    # D.2.1 / pre-D.3 hygiene: reduce repeated indicator payloads and log explosions
    llm_context_hygiene_enabled: bool = field(default_factory=lambda: _get_bool_env("LLM_CONTEXT_HYGIENE_ENABLED", True))
    llm_payload_string_max_chars: int = field(default_factory=lambda: _get_int_env("LLM_PAYLOAD_STRING_MAX_CHARS", "60000"))
    llm_payload_hygiene_max_depth: int = field(default_factory=lambda: _get_int_env("LLM_PAYLOAD_HYGIENE_MAX_DEPTH", "8"))
    llm_repeated_fragment_max_repeats: int = field(default_factory=lambda: _get_int_env("LLM_REPEATED_FRAGMENT_MAX_REPEATS", "3"))
    # Read-only LLM cost/usage ledger (logs/llm_cost_ledger.jsonl) -- metadata only,
    # never prompt/completion content. See bot/llm_cost_ledger.py.
    llm_cost_ledger_enabled: bool = field(default_factory=lambda: _get_bool_env("LLM_COST_LEDGER_ENABLED", True))
    enable_phase_d32_llm_pre_live_health: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_D32_LLM_PRE_LIVE_HEALTH", True))
    phase_d32_llm_health_window_minutes: int = field(default_factory=lambda: _get_int_env("PHASE_D32_LLM_HEALTH_WINDOW_MINUTES", "240"))
    phase_d32_block_on_recent_llm_corrupt: bool = field(default_factory=lambda: _get_bool_env("PHASE_D32_BLOCK_ON_RECENT_LLM_CORRUPT", True))
    phase_d32_block_on_recent_provider_errors: bool = field(default_factory=lambda: _get_bool_env("PHASE_D32_BLOCK_ON_RECENT_PROVIDER_ERRORS", True))

    # Optionele guardrails voor veilig gedrag
    enforce_judge_ticker_match: bool = field(default_factory=lambda: _get_bool_env("ENFORCE_JUDGE_TICKER_MATCH", True))
    reject_unknown_llm_keys: bool = field(default_factory=lambda: _get_bool_env("REJECT_UNKNOWN_LLM_KEYS", True))

    # Cost-aware expensive-judge gate. Keep the expensive GPT-5.5 judge for
    # strong setups and position management, but skip it for weak mini-analysis
    # candidates. This reduces API costs without weakening the final decision
    # layer for promising trades.
    enable_expensive_judge_gate: bool = field(default_factory=lambda: _get_bool_env("ENABLE_EXPENSIVE_JUDGE_GATE", True))
    judge_min_gate_confidence: int = field(default_factory=lambda: _get_int_env("JUDGE_MIN_GATE_CONFIDENCE", "62"))
    judge_min_synth_confidence: int = field(default_factory=lambda: _get_int_env("JUDGE_MIN_SYNTH_CONFIDENCE", "60"))
    judge_min_bull_score: int = field(default_factory=lambda: _get_int_env("JUDGE_MIN_BULL_SCORE", "56"))
    judge_max_bear_score: int = field(default_factory=lambda: _get_int_env("JUDGE_MAX_BEAR_SCORE", "72"))

    # Judge-led runner management / soft-rule override.
    # These settings give the GPT judge limited strategic authority over soft
    # profit-management exits, while hard exchange/risk safety rails remain absolute.
    judge_soft_override_enabled: bool = field(default_factory=lambda: _get_bool_env("JUDGE_SOFT_OVERRIDE_ENABLED", True))
    judge_soft_override_min_confidence: int = field(default_factory=lambda: _get_int_env("JUDGE_SOFT_OVERRIDE_MIN_CONFIDENCE", "65"))
    judge_soft_override_min_adx: Decimal = field(default_factory=lambda: _get_decimal_env("JUDGE_SOFT_OVERRIDE_MIN_ADX", "25"))
    judge_soft_override_require_profit: bool = field(default_factory=lambda: _get_bool_env("JUDGE_SOFT_OVERRIDE_REQUIRE_PROFIT", True))
    judge_soft_override_max_count: int = field(default_factory=lambda: _get_int_env("JUDGE_SOFT_OVERRIDE_MAX_COUNT", "1"))
    judge_runner_partial_fraction: Decimal = field(default_factory=lambda: _get_decimal_env("JUDGE_RUNNER_PARTIAL_FRACTION", "0.25"))
    judge_runner_trailing_distance_pct: Decimal = field(default_factory=lambda: _get_decimal_env("JUDGE_RUNNER_TRAILING_DISTANCE_PCT", "0.045"))
    judge_runner_require_candle_close: bool = field(default_factory=lambda: _get_bool_env("JUDGE_RUNNER_REQUIRE_CANDLE_CLOSE", True))
    judge_conflict_logging_enabled: bool = field(default_factory=lambda: _get_bool_env("JUDGE_CONFLICT_LOGGING_ENABLED", True))

    # Entry escalation is deliberately conservative: the current ranked selector
    # already promotes strong watch candidates to full analysis. These flags make
    # the intended next phase explicit without bypassing hard entry gates.
    judge_entry_escalation_enabled: bool = field(default_factory=lambda: _get_bool_env("JUDGE_ENTRY_ESCALATION_ENABLED", False))
    judge_entry_escalation_min_score: int = field(default_factory=lambda: _get_int_env("JUDGE_ENTRY_ESCALATION_MIN_SCORE", "58"))
    judge_entry_escalation_max_per_cycle: int = field(default_factory=lambda: _get_int_env("JUDGE_ENTRY_ESCALATION_MAX_PER_CYCLE", "2"))
    judge_entry_allow_soft_gate_override: bool = field(default_factory=lambda: _get_bool_env("JUDGE_ENTRY_ALLOW_SOFT_GATE_OVERRIDE", False))
    judge_entry_starter_size_fraction: Decimal = field(default_factory=lambda: _get_decimal_env("JUDGE_ENTRY_STARTER_SIZE_FRACTION", "0.50"))
    judge_entry_max_override_size_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("JUDGE_ENTRY_MAX_OVERRIDE_SIZE_USDC", "60"))


    # Deterministic post-trade reflection memory. This stores compact lessons from
    # closed positions and feeds them back as context to the trade planner/judge.
    # It never authorizes orders and must remain safe if the state file is corrupt.
    enable_trade_reflection_memory: bool = field(default_factory=lambda: _get_bool_env("ENABLE_TRADE_REFLECTION_MEMORY", True))
    trade_reflection_max_records: int = field(default_factory=lambda: _get_int_env("TRADE_REFLECTION_MAX_RECORDS", "500"))
    trade_reflection_recent_limit: int = field(default_factory=lambda: _get_int_env("TRADE_REFLECTION_RECENT_LIMIT", "12"))
    trade_reflection_min_samples_for_signal: int = field(default_factory=lambda: _get_int_env("TRADE_REFLECTION_MIN_SAMPLES_FOR_SIGNAL", "3"))
    trade_reflection_analytics_limit: int = field(default_factory=lambda: _get_int_env("TRADE_REFLECTION_ANALYTICS_LIMIT", "200"))


    # Decision outcome tracking. This learns from wait/skip/pending/plan decisions
    # by evaluating later price-path outcomes. It is read-only learning context:
    # no thresholds, sizing or risk rules are changed automatically.
    enable_decision_outcome_tracking: bool = field(default_factory=lambda: _get_bool_env("ENABLE_DECISION_OUTCOME_TRACKING", True))
    decision_outcome_max_records: int = field(default_factory=lambda: _get_int_env("DECISION_OUTCOME_MAX_RECORDS", "2000"))
    decision_outcome_horizons_hours: str = field(default_factory=lambda: _get_optional_env("DECISION_OUTCOME_HORIZONS_HOURS", "4,12,24"))
    decision_outcome_min_move_pct: Decimal = field(default_factory=lambda: _get_decimal_env("DECISION_OUTCOME_MIN_MOVE_PCT", "0.0250"))
    decision_outcome_adverse_move_pct: Decimal = field(default_factory=lambda: _get_decimal_env("DECISION_OUTCOME_ADVERSE_MOVE_PCT", "0.0200"))
    decision_outcome_summary_limit: int = field(default_factory=lambda: _get_int_env("DECISION_OUTCOME_SUMMARY_LIMIT", "100"))
    # Shadow Outcome Accelerator. Captures all full-cycle decisions for hypothetical
    # 1h/4h/24h evaluation using local price/candle data. Evidence-only — no live
    # orders, no Coinbase calls, no parameter mutation.
    enable_shadow_outcome_accelerator: bool = field(default_factory=lambda: _get_bool_env("ENABLE_SHADOW_OUTCOME_ACCELERATOR", True))

    # Pending trade plans. These plans are monitoring context only: a triggered
    # plan can promote a ticker to fresh full analysis, but it can never execute
    # without a new final judge decision and deterministic risk/firewall checks.
    enable_pending_trade_plans: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PENDING_TRADE_PLANS", True))
    pending_trade_plan_ttl_hours: int = field(default_factory=lambda: _get_int_env("PENDING_TRADE_PLAN_TTL_HOURS", "24"))
    pending_trade_plan_max_records: int = field(default_factory=lambda: _get_int_env("PENDING_TRADE_PLAN_MAX_RECORDS", "200"))
    pending_trade_plan_min_confidence: int = field(default_factory=lambda: _get_int_env("PENDING_TRADE_PLAN_MIN_CONFIDENCE", "60"))
    pending_trade_plan_trigger_score: int = field(default_factory=lambda: _get_int_env("PENDING_TRADE_PLAN_TRIGGER_SCORE", "88"))
    pending_trade_plan_max_chase_distance_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PENDING_TRADE_PLAN_MAX_CHASE_DISTANCE_PCT", "0.0200"))

    # Phase A: read-only execution planner / future master-only limit-order manager.
    # These settings are intentionally safe by default: the new layer only logs
    # execution suggestions and all live limit-order switches remain disabled.
    enable_read_only_execution_planner: bool = field(default_factory=lambda: _get_bool_env("ENABLE_READ_ONLY_EXECUTION_PLANNER", True))
    execution_planner_call_on_wait: bool = field(default_factory=lambda: _get_bool_env("EXECUTION_PLANNER_CALL_ON_WAIT", False))
    allow_gpt_dynamic_order_expiry: bool = field(default_factory=lambda: _get_bool_env("ALLOW_GPT_DYNAMIC_ORDER_EXPIRY", True))
    order_review_interval_hours: int = field(default_factory=lambda: _get_int_env("ORDER_REVIEW_INTERVAL_HOURS", "1"))

    entry_limit_order_min_expiry_hours: int = field(default_factory=lambda: _get_int_env("ENTRY_LIMIT_ORDER_MIN_EXPIRY_HOURS", "1"))
    entry_limit_order_default_expiry_hours: int = field(default_factory=lambda: _get_int_env("ENTRY_LIMIT_ORDER_DEFAULT_EXPIRY_HOURS", "6"))
    entry_limit_order_max_expiry_hours: int = field(default_factory=lambda: _get_int_env("ENTRY_LIMIT_ORDER_MAX_EXPIRY_HOURS", "12"))

    exit_limit_order_min_expiry_hours: int = field(default_factory=lambda: _get_int_env("EXIT_LIMIT_ORDER_MIN_EXPIRY_HOURS", "1"))
    exit_limit_order_default_expiry_hours: int = field(default_factory=lambda: _get_int_env("EXIT_LIMIT_ORDER_DEFAULT_EXPIRY_HOURS", "24"))
    exit_limit_order_max_expiry_hours: int = field(default_factory=lambda: _get_int_env("EXIT_LIMIT_ORDER_MAX_EXPIRY_HOURS", "72"))

    add_to_position_order_min_expiry_hours: int = field(default_factory=lambda: _get_int_env("ADD_TO_POSITION_ORDER_MIN_EXPIRY_HOURS", "1"))
    add_to_position_order_default_expiry_hours: int = field(default_factory=lambda: _get_int_env("ADD_TO_POSITION_ORDER_DEFAULT_EXPIRY_HOURS", "4"))
    add_to_position_order_max_expiry_hours: int = field(default_factory=lambda: _get_int_env("ADD_TO_POSITION_ORDER_MAX_EXPIRY_HOURS", "8"))

    max_order_replaces_per_ticker_per_hour: int = field(default_factory=lambda: _get_int_env("MAX_ORDER_REPLACES_PER_TICKER_PER_HOUR", "1"))
    disallow_unreviewed_gtc_orders: bool = field(default_factory=lambda: _get_bool_env("DISALLOW_UNREVIEWED_GTC_ORDERS", True))

    max_order_actions_per_cycle: int = field(default_factory=lambda: _get_int_env("MAX_ORDER_ACTIONS_PER_CYCLE", "5"))
    max_new_orders_per_cycle: int = field(default_factory=lambda: _get_int_env("MAX_NEW_ORDERS_PER_CYCLE", "2"))
    max_cancels_per_cycle: int = field(default_factory=lambda: _get_int_env("MAX_CANCELS_PER_CYCLE", "3"))
    max_replaces_per_cycle: int = field(default_factory=lambda: _get_int_env("MAX_REPLACES_PER_CYCLE", "2"))

    enable_limit_order_manager: bool = field(default_factory=lambda: _get_bool_env("ENABLE_LIMIT_ORDER_MANAGER", False))
    enable_live_limit_orders: bool = field(default_factory=lambda: _get_bool_env("ENABLE_LIVE_LIMIT_ORDERS", False))
    enable_live_entry_orders: bool = field(default_factory=lambda: _get_bool_env("ENABLE_LIVE_ENTRY_ORDERS", False))
    enable_live_exit_orders: bool = field(default_factory=lambda: _get_bool_env("ENABLE_LIVE_EXIT_ORDERS", False))
    enable_full_workflow_live_mode: bool = field(default_factory=lambda: _get_bool_env("ENABLE_FULL_WORKFLOW_LIVE_MODE", False))

    # Phase C.0/C.1: master-only live-entry limit-order safety scaffold.
    # Default is fully disabled. These settings only prepare deterministic guard
    # checks; no Coinbase live limit submit path is introduced by Phase C.0.
    enable_phase_c_live_small_limit_orders: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS", False))
    phase_c_allowed_tickers: list[str] = field(default_factory=lambda: _normalize_tickers(_split_csv(_get_optional_env("PHASE_C_ALLOWED_TICKERS", ""))))
    autonomous_allowed_tickers: list[str] = field(default_factory=lambda: _normalize_tickers(_split_csv(_get_optional_env("AUTONOMOUS_ALLOWED_TICKERS", ""))))
    phase_c_max_order_quote: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_C_MAX_ORDER_QUOTE", "100.00"))
    phase_c_max_open_entry_orders: int = field(default_factory=lambda: _get_int_env("PHASE_C_MAX_OPEN_ENTRY_ORDERS", "1"))
    phase_c_max_new_orders_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_C_MAX_NEW_ORDERS_PER_CYCLE", "1"))
    phase_c_max_cancels_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_C_MAX_CANCELS_PER_CYCLE", "1"))
    phase_c_max_replaces_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_C_MAX_REPLACES_PER_CYCLE", "0"))
    phase_c_require_pending_intent: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_REQUIRE_PENDING_INTENT", True))
    phase_c_require_promotion_ready: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_REQUIRE_PROMOTION_READY", True))
    phase_c_require_fresh_judge: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_REQUIRE_FRESH_JUDGE", True))
    phase_c_require_risk_approval: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_REQUIRE_RISK_APPROVAL", True))
    phase_c_require_orderbook_freshness: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_REQUIRE_ORDERBOOK_FRESHNESS", True))
    phase_c_entry_order_min_expiry_minutes: int = field(default_factory=lambda: _get_int_env("PHASE_C_ENTRY_ORDER_MIN_EXPIRY_MINUTES", "15"))
    phase_c_entry_order_default_expiry_minutes: int = field(default_factory=lambda: _get_int_env("PHASE_C_ENTRY_ORDER_DEFAULT_EXPIRY_MINUTES", "60"))
    phase_c_entry_order_max_expiry_hours: int = field(default_factory=lambda: _get_int_env("PHASE_C_ENTRY_ORDER_MAX_EXPIRY_HOURS", "6"))
    phase_c_disable_exit_limit_orders: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", True))
    phase_c_paper_shadow_log: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_PAPER_SHADOW_LOG", True))

    # Phase C.2: live limit-submit infrastructure scaffold. This prepares and
    # audits the future submit payload, but actual Coinbase submit remains hard
    # disabled unless a later phase explicitly enables the extra submit flag.
    enable_phase_c_live_submit_infrastructure: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE", True))
    enable_phase_c_actual_coinbase_submit: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT", False))
    phase_c_live_order_post_only: bool = field(default_factory=lambda: _get_bool_env("PHASE_C_LIVE_ORDER_POST_ONLY", True))

    # Mode C: ACK-gated market order mode for the 20-100 USDC POC run.
    # All three flags and the exact ACK are required. Replication must remain
    # disabled; this mode is not a learning/neural execution bridge.
    market_order_enabled: bool = field(default_factory=lambda: _get_bool_env("MARKET_ORDER_ENABLED", False))
    enable_market_orders: bool = field(default_factory=lambda: _get_bool_env("ENABLE_MARKET_ORDERS", False))
    allow_market_orders: bool = field(default_factory=lambda: _get_bool_env("ALLOW_MARKET_ORDERS", False))
    mode_c_market_order_ack: str = field(default_factory=lambda: _get_optional_env(MODE_C_MARKET_ORDER_ACK_ENV, ""))
    replication_enabled: bool = field(default_factory=lambda: _get_bool_env("REPLICATION_ENABLED", False))
    replication_lifecycle_enabled: bool = field(default_factory=lambda: _get_bool_env("REPLICATION_LIFECYCLE_ENABLED", False))
    replication_lifecycle_http_enabled: bool = field(default_factory=lambda: _get_bool_env("REPLICATION_LIFECYCLE_HTTP_ENABLED", False))

    # Phase C.4.2: final pre-live bridge for later autonomous small-live orderbook mode.
    # Defaults remain disabled. These fields define hard caps for the first autonomous
    # live orderbook phase; they do not by themselves place or cancel orders.
    enable_autonomous_small_live_orderbook_mode: bool = field(default_factory=lambda: _get_bool_env("ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE", False))
    autonomous_max_order_quote: Decimal = field(default_factory=lambda: _get_decimal_env("AUTONOMOUS_MAX_ORDER_QUOTE", "100.00"))
    autonomous_max_open_orders: int = field(default_factory=lambda: _get_int_env("AUTONOMOUS_MAX_OPEN_ORDERS", "4"))
    autonomous_max_new_orders_per_cycle: int = field(default_factory=lambda: _get_int_env("AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE", "1"))
    autonomous_max_cancels_per_cycle: int = field(default_factory=lambda: _get_int_env("AUTONOMOUS_MAX_CANCELS_PER_CYCLE", "2"))
    autonomous_max_replaces_per_cycle: int = field(default_factory=lambda: _get_int_env("AUTONOMOUS_MAX_REPLACES_PER_CYCLE", "1"))
    autonomous_require_post_only: bool = field(default_factory=lambda: _get_bool_env("AUTONOMOUS_REQUIRE_POST_ONLY", True))
    autonomous_entry_only_first: bool = field(default_factory=lambda: _get_bool_env("AUTONOMOUS_ENTRY_ONLY_FIRST", True))
    autonomous_allow_exits: bool = field(default_factory=lambda: _get_bool_env("AUTONOMOUS_ALLOW_EXITS", False))
    # C.4.3: runtime bridge that can submit entry-only autonomous live orders
    # when all Phase-C guardrails, risk checks and submit flags are green.
    enable_phase_c43_autonomous_entry_submitter: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_C43_AUTONOMOUS_ENTRY_SUBMITTER", True))
    # Never synthesize this authority in application code. C.4.3 must receive
    # the exact operator-supplied runtime value before it may submit a BUY.
    phase_c43_runtime_submit_ack: str = field(default_factory=lambda: _get_optional_env(C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_ENV, ""))
    enable_orderbook_entry_planner: bool = field(default_factory=lambda: _get_bool_env("ENABLE_ORDERBOOK_ENTRY_PLANNER", True))
    enable_resting_limit_entry_preview: bool = field(default_factory=lambda: _get_bool_env("ENABLE_RESTING_LIMIT_ENTRY_PREVIEW", True))
    enable_resting_limit_entry_live_submit: bool = field(default_factory=lambda: _get_bool_env("ENABLE_RESTING_LIMIT_ENTRY_LIVE_SUBMIT", False))
    enable_pending_entry_lifecycle: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PENDING_ENTRY_LIFECYCLE", True))
    enable_pending_entry_cancel_preview: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PENDING_ENTRY_CANCEL_PREVIEW", True))
    enable_pending_entry_live_cancel: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PENDING_ENTRY_LIVE_CANCEL", False))
    orderbook_entry_require_post_only: bool = field(default_factory=lambda: _get_bool_env("ORDERBOOK_ENTRY_REQUIRE_POST_ONLY", True))
    orderbook_entry_max_distance_from_mid_pct: Decimal = field(default_factory=lambda: _get_decimal_env("ORDERBOOK_ENTRY_MAX_DISTANCE_FROM_MID_PCT", "0.0030"))
    orderbook_entry_max_ttl_minutes: int = field(default_factory=lambda: _get_int_env("ORDERBOOK_ENTRY_MAX_TTL_MINUTES", "60"))
    orderbook_entry_cancel_if_setup_invalidated: bool = field(default_factory=lambda: _get_bool_env("ORDERBOOK_ENTRY_CANCEL_IF_SETUP_INVALIDATED", True))
    orderbook_entry_block_with_open_position_same_ticker: bool = field(default_factory=lambda: _get_bool_env("ORDERBOOK_ENTRY_BLOCK_WITH_OPEN_POSITION_SAME_TICKER", True))
    orderbook_entry_max_replaces_per_order: int = field(default_factory=lambda: _get_int_env("ORDERBOOK_ENTRY_MAX_REPLACES_PER_ORDER", "1"))

    # C.4.4 / D.3.3: lifecycle orchestrator service hook.
    # The hook is safe by default: it only previews local C.4.3 order lifecycle
    # state after each bot cycle. Coinbase polling, local state mutation and
    # D.2/D.3 build steps require separate explicit flags.
    enable_phase_c43_lifecycle_orchestrator: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_C43_LIFECYCLE_ORCHESTRATOR", True))
    phase_c43_lifecycle_allow_coinbase_poll: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL", False))
    phase_c43_lifecycle_apply_local: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_APPLY_LOCAL", False))
    phase_c43_lifecycle_build_d2_plan: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_BUILD_D2_PLAN", False))
    phase_c43_lifecycle_persist_d2_plan: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_PERSIST_D2_PLAN", False))
    phase_c43_lifecycle_build_d3_preview: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW", False))
    # C.4.4.2 controlled poll/apply governance. These limits make later
    # lifecycle arming explicit and bounded: polling/apply-local degrade to
    # preview/no-op if too many open C.4.3 orders exist or if unsafe flags are on.
    phase_c43_lifecycle_max_poll_orders_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_C43_LIFECYCLE_MAX_POLL_ORDERS_PER_CYCLE", "4"))
    phase_c43_lifecycle_max_apply_actions_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_C43_LIFECYCLE_MAX_APPLY_ACTIONS_PER_CYCLE", "4"))
    phase_c43_lifecycle_apply_requires_coinbase_poll: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_APPLY_REQUIRES_COINBASE_POLL", True))
    phase_c43_lifecycle_block_apply_when_live_exits_enabled: bool = field(default_factory=lambda: _get_bool_env("PHASE_C43_LIFECYCLE_BLOCK_APPLY_WHEN_LIVE_EXITS_ENABLED", True))
    phase_c43_lifecycle_order_store_path: str = field(default_factory=lambda: _get_optional_env("PHASE_C43_LIFECYCLE_ORDER_STORE_PATH", "state/open_orders.json"))
    phase_c43_lifecycle_order_events_path: str = field(default_factory=lambda: _get_optional_env("PHASE_C43_LIFECYCLE_ORDER_EVENTS_PATH", "logs/order_events.jsonl"))
    # Inventory reconciliation can mutate local positions. It stays disabled
    # until an operator deliberately arms that separate state-repair route.
    enable_exchange_inventory_sync: bool = field(default_factory=lambda: _get_bool_env("ENABLE_EXCHANGE_INVENTORY_SYNC", False))

    # Phase D.2: position-executor / bracket-lite scaffold.
    # D.2 creates stateful exit plans after a filled entry, but it does not
    # submit live SELL orders. Controlled live reduce-only exits belong to D.3.
    enable_phase_d2_position_executor: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_D2_POSITION_EXECUTOR", True))
    phase_d2_min_expected_net_edge_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "0.0125"))
    phase_d2_min_reward_to_fee_ratio: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "3.0"))
    phase_d2_min_reward_to_risk_ratio: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "1.5"))
    phase_d2_estimated_entry_fee_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_ESTIMATED_ENTRY_FEE_PCT", "0.0040"))
    phase_d2_estimated_exit_fee_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_ESTIMATED_EXIT_FEE_PCT", "0.0040"))
    phase_d2_estimated_spread_slippage_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_ESTIMATED_SPREAD_SLIPPAGE_PCT", "0.0020"))
    phase_d2_fee_safety_buffer_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_FEE_SAFETY_BUFFER_PCT", "0.0025"))
    phase_d2_max_tp_orders_per_position: int = field(default_factory=lambda: _get_int_env("PHASE_D2_MAX_TP_ORDERS_PER_POSITION", "2"))
    phase_d2_default_time_limit_hours: int = field(default_factory=lambda: _get_int_env("PHASE_D2_DEFAULT_TIME_LIMIT_HOURS", "48"))
    phase_d2_default_trailing_activation_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT", "0.0250"))
    phase_d2_default_trailing_distance_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT", "0.0180"))
    phase_d2_allow_add_to_winner: bool = field(default_factory=lambda: _get_bool_env("PHASE_D2_ALLOW_ADD_TO_WINNER", False))
    phase_d2_max_adds_to_winner: int = field(default_factory=lambda: _get_int_env("PHASE_D2_MAX_ADDS_TO_WINNER", "0"))
    phase_d2_allow_averaging_down: bool = field(default_factory=lambda: _get_bool_env("PHASE_D2_ALLOW_AVERAGING_DOWN", False))

    # Small-probe promotion gate (_maybe_promote_wait_to_small_probe in strategy_engine.py).
    # Recalibrated 2026-07-02 against 72h of live judge output: the original thresholds
    # (bear/bull gap<4, bull>=64, breakout_confirmation>=60, synth>=78, OR-based HTF filter)
    # were fit to a different score distribution and blocked 64/64 valid prepare_* plans
    # over 72h of a broad +2% to +8% uptrend. See reports/audits/entry-funnel-72h-latest.md.
    small_probe_max_bear_bull_gap: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_MAX_BEAR_BULL_GAP", "32"))
    small_probe_require_htf_both_timeframes: bool = field(default_factory=lambda: _get_bool_env("SMALL_PROBE_REQUIRE_HTF_BOTH_TIMEFRAMES", True))
    small_probe_tc_synth_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_TC_SYNTH_MIN", "68"))
    small_probe_tc_bull_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_TC_BULL_MIN", "55"))
    small_probe_tc_breakout_confirmation_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_TC_BREAKOUT_CONFIRMATION_MIN", "42"))
    small_probe_tc_vol_15m_min: Decimal = field(default_factory=lambda: _get_decimal_env("SMALL_PROBE_TC_VOL_15M_MIN", "0.55"))
    small_probe_tc_vol_1h_min: Decimal = field(default_factory=lambda: _get_decimal_env("SMALL_PROBE_TC_VOL_1H_MIN", "0.45"))
    small_probe_rc_synth_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_RC_SYNTH_MIN", "65"))
    small_probe_rc_bull_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_RC_BULL_MIN", "52"))
    small_probe_rc_breakout_confirmation_min: int = field(default_factory=lambda: _get_int_env("SMALL_PROBE_RC_BREAKOUT_CONFIRMATION_MIN", "36"))
    small_probe_rc_vol_15m_min: Decimal = field(default_factory=lambda: _get_decimal_env("SMALL_PROBE_RC_VOL_15M_MIN", "0.50"))
    small_probe_rc_vol_1h_min: Decimal = field(default_factory=lambda: _get_decimal_env("SMALL_PROBE_RC_VOL_1H_MIN", "0.40"))

    # Phase D.3: controlled live reduce-only exits.
    # Defaults prepare/readiness only. Actual live SELL submit additionally requires
    # ENABLE_LIVE_EXIT_ORDERS=true, AUTONOMOUS_ALLOW_EXITS=true,
    # PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false, --submit-live and D3_ACK.
    enable_phase_d3_controlled_live_exits: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS", True))
    enable_phase_d3_actual_exit_submit: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", False))
    # Never synthesize this authority in application code. The runtime bridge
    # must receive the exact operator-supplied value before it may submit D3.
    phase_d3_runtime_submit_ack: str = field(default_factory=lambda: _get_optional_env(D3_CONTROLLED_LIVE_EXIT_ACK_ENV, ""))
    phase_d3_max_exit_order_quote: Decimal = field(default_factory=lambda: _get_decimal_env("PHASE_D3_MAX_EXIT_ORDER_QUOTE", "120.00"))
    phase_d3_max_open_exit_orders: int = field(default_factory=lambda: _get_int_env("PHASE_D3_MAX_OPEN_EXIT_ORDERS", "4"))
    phase_d3_max_new_exit_orders_per_cycle: int = field(default_factory=lambda: _get_int_env("PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE", "1"))
    phase_d3_exit_order_post_only: bool = field(default_factory=lambda: _get_bool_env("PHASE_D3_EXIT_ORDER_POST_ONLY", True))
    phase_d3_require_reduce_only_local: bool = field(default_factory=lambda: _get_bool_env("PHASE_D3_REQUIRE_REDUCE_ONLY_LOCAL", True))

    # Controlled autonomous stop-exit route. Disabled by default. When enabled,
    # the route must still cancel and verify an existing D.3 TP first and must
    # stay inside the small quote cap before any stop SELL can be submitted.
    enable_controlled_stop_market_exits: bool = field(default_factory=lambda: _get_bool_env("ENABLE_CONTROLLED_STOP_MARKET_EXITS", False))
    enable_autonomous_stop_exit_cancel: bool = field(default_factory=lambda: _get_bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL", False))
    enable_autonomous_stop_exit_submit: bool = field(default_factory=lambda: _get_bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT", False))
    enable_autonomous_stop_exit_apply: bool = field(default_factory=lambda: _get_bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY", False))
    mode_b_controlled_stop_exit_ack: str = field(default_factory=lambda: _get_optional_env(MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV, ""))
    controlled_stop_exit_max_quote_usd: Decimal = field(default_factory=lambda: _get_decimal_env("CONTROLLED_STOP_EXIT_MAX_QUOTE_USD", "120.00"))
    controlled_stop_exit_require_open_tp_cancel_first: bool = field(default_factory=lambda: _get_bool_env("CONTROLLED_STOP_EXIT_REQUIRE_OPEN_TP_CANCEL_FIRST", True))
    controlled_stop_exit_order_type: str = field(default_factory=lambda: _get_optional_env("CONTROLLED_STOP_EXIT_ORDER_TYPE", "near_market_limit_ioc").lower())
    controlled_stop_exit_max_slippage_pct: Decimal = field(default_factory=lambda: _get_decimal_env("CONTROLLED_STOP_EXIT_MAX_SLIPPAGE_PCT", "0.0100"))

    enable_bounded_exploration_mode: bool = field(default_factory=lambda: _get_bool_env("ENABLE_BOUNDED_EXPLORATION_MODE", False))
    exploration_min_order_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("EXPLORATION_MIN_ORDER_QUOTE_USDC", str(EXPLORATION_MIN_ORDER_QUOTE_USDC)))
    exploration_max_order_quote_usdc: Decimal = field(default_factory=lambda: _get_decimal_env("EXPLORATION_MAX_ORDER_QUOTE_USDC", str(EXPLORATION_MAX_ORDER_QUOTE_USDC)))
    exploration_max_open_probes: int = field(default_factory=lambda: _get_int_env("EXPLORATION_MAX_OPEN_PROBES", "1"))
    exploration_max_probes_per_day: int = field(default_factory=lambda: _get_int_env("EXPLORATION_MAX_PROBES_PER_DAY", "2"))
    exploration_allowed_tickers: list[str] = field(default_factory=lambda: _normalize_tickers(_split_csv(_get_optional_env("EXPLORATION_ALLOWED_TICKERS", ""))))
    exploration_allow_market_orders: bool = field(default_factory=lambda: _get_bool_env("EXPLORATION_ALLOW_MARKET_ORDERS", False))
    exploration_require_hard_risk_green: bool = field(default_factory=lambda: _get_bool_env("EXPLORATION_REQUIRE_HARD_RISK_GREEN", True))
    exploration_require_fresh_trigger: bool = field(default_factory=lambda: _get_bool_env("EXPLORATION_REQUIRE_FRESH_TRIGGER", True))
    exploration_require_no_chase: bool = field(default_factory=lambda: _get_bool_env("EXPLORATION_REQUIRE_NO_CHASE", True))
    exploration_max_spread_pct: Decimal = field(default_factory=lambda: _get_decimal_env("EXPLORATION_MAX_SPREAD_PCT", "0.0040"))
    exploration_require_orderbook_snapshot: bool = field(default_factory=lambda: _get_bool_env("EXPLORATION_REQUIRE_ORDERBOOK_SNAPSHOT", True))

    exit_target_max_distance_from_mid_pct: Decimal = field(default_factory=lambda: _get_decimal_env("EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT", "0.0350"))
    exit_target_allow_far_tp_with_resistance_confirmation: bool = field(default_factory=lambda: _get_bool_env("EXIT_TARGET_ALLOW_FAR_TP_WITH_RESISTANCE_CONFIRMATION", True))
    exit_target_require_fresh_context_when_stop_breached: bool = field(default_factory=lambda: _get_bool_env("EXIT_TARGET_REQUIRE_FRESH_CONTEXT_WHEN_STOP_BREACHED", True))
    exit_target_stale_if_stop_breached: bool = field(default_factory=lambda: _get_bool_env("EXIT_TARGET_STALE_IF_STOP_BREACHED", True))

    order_store_max_records: int = field(default_factory=lambda: _get_int_env("ORDER_STORE_MAX_RECORDS", "2000"))
    enable_paper_no_fill_followup_analysis: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PAPER_NO_FILL_FOLLOWUP_ANALYSIS", True))
    paper_no_fill_followup_min_move_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PAPER_NO_FILL_FOLLOWUP_MIN_MOVE_PCT", "0.0050"))
    enable_paper_reserved_balance_checks: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PAPER_RESERVED_BALANCE_CHECKS", True))
    enable_paper_order_budget_enforcement: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PAPER_ORDER_BUDGET_ENFORCEMENT", True))
    max_open_paper_orders_total: int = field(default_factory=lambda: _get_int_env("MAX_OPEN_PAPER_ORDERS_TOTAL", "3"))
    max_open_paper_entry_orders_per_ticker: int = field(default_factory=lambda: _get_int_env("MAX_OPEN_PAPER_ENTRY_ORDERS_PER_TICKER", "1"))
    max_open_paper_exit_orders_per_ticker: int = field(default_factory=lambda: _get_int_env("MAX_OPEN_PAPER_EXIT_ORDERS_PER_TICKER", "2"))

    # Phase B.6: paper pending/waitlist order-intents. These are not orders,
    # reserve no balance and cannot execute. They only preserve useful watch/
    # pending-plan context for fresh future analysis.
    enable_paper_pending_order_intents: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PAPER_PENDING_ORDER_INTENTS", True))
    enable_paper_watchlist_intents_from_gate_watch: bool = field(default_factory=lambda: _get_bool_env("ENABLE_PAPER_WATCHLIST_INTENTS_FROM_GATE_WATCH", True))
    paper_pending_intent_ttl_hours: int = field(default_factory=lambda: _get_int_env("PAPER_PENDING_INTENT_TTL_HOURS", "12"))
    paper_pending_intent_max_records: int = field(default_factory=lambda: _get_int_env("PAPER_PENDING_INTENT_MAX_RECORDS", "500"))
    paper_pending_intent_min_gate_confidence: int = field(default_factory=lambda: _get_int_env("PAPER_PENDING_INTENT_MIN_GATE_CONFIDENCE", "50"))
    paper_pending_intent_mark_needs_fresh_analysis_status: bool = field(default_factory=lambda: _get_bool_env("PAPER_PENDING_INTENT_MARK_NEEDS_FRESH_ANALYSIS_STATUS", True))
    paper_pending_intent_max_replaced_per_ticker: int = field(default_factory=lambda: _get_int_env("PAPER_PENDING_INTENT_MAX_REPLACED_PER_TICKER", "8"))
    paper_pending_intent_final_retention_hours: int = field(default_factory=lambda: _get_int_env("PAPER_PENDING_INTENT_FINAL_RETENTION_HOURS", "72"))
    paper_pending_intent_dedupe_tolerance_pct: Decimal = field(default_factory=lambda: _get_decimal_env("PAPER_PENDING_INTENT_DEDUPE_TOLERANCE_PCT", "0.0025"))
    paper_pending_intent_enable_dedupe_refresh: bool = field(default_factory=lambda: _get_bool_env("PAPER_PENDING_INTENT_ENABLE_DEDUPE_REFRESH", True))

    # GrowBot-style neural shadow learning. This layer can add compact learned
    # context to decisions, but v1 cannot submit orders or mutate parameters.
    neural_shadow_policy_enabled: bool = field(default_factory=lambda: _get_bool_env("NEURAL_SHADOW_POLICY_ENABLED", True))
    neural_shadow_policy_training_enabled: bool = field(default_factory=lambda: _get_bool_env("NEURAL_SHADOW_POLICY_TRAINING_ENABLED", True))
    neural_shadow_policy_execution_allowed: bool = field(default_factory=lambda: _get_bool_env("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED", False))
    neural_shadow_policy_agreement_required: bool = field(default_factory=lambda: _get_bool_env("NEURAL_SHADOW_POLICY_AGREEMENT_REQUIRED", False))
    neural_shadow_policy_model_path: str = field(default_factory=lambda: _get_optional_env("NEURAL_SHADOW_POLICY_MODEL_PATH", "state/neural_shadow_policy.json"))
    neural_shadow_policy_min_samples: int = field(default_factory=lambda: _get_int_env("NEURAL_SHADOW_POLICY_MIN_SAMPLES", "50"))
    neural_shadow_policy_min_confidence: Decimal = field(default_factory=lambda: _get_decimal_env("NEURAL_SHADOW_POLICY_MIN_CONFIDENCE", "0.65"))
    neural_shadow_policy_report_path: str = field(default_factory=lambda: _get_optional_env("NEURAL_SHADOW_POLICY_REPORT_PATH", "reports/live_learning/neural-shadow-policy-latest.json"))

    allow_add_to_winners: bool = field(default_factory=lambda: _get_bool_env("ALLOW_ADD_TO_WINNERS", True))
    allow_averaging_down: bool = field(default_factory=lambda: _get_bool_env("ALLOW_AVERAGING_DOWN", False))
    max_adds_per_position: int = field(default_factory=lambda: _get_int_env("MAX_ADDS_PER_POSITION", "1"))
    max_position_scale_factor: Decimal = field(default_factory=lambda: _get_decimal_env("MAX_POSITION_SCALE_FACTOR", "1.5"))

    # Inventory-aware selling
    inventory_sell_enabled: bool = field(default_factory=lambda: _get_bool_env("INVENTORY_SELL_ENABLED", False))
    inventory_sell_mode: str = field(default_factory=lambda: _get_optional_env("INVENTORY_SELL_MODE", "bot_only").lower())
    inventory_max_extra_sell_fraction: Decimal = field(default_factory=lambda: _get_decimal_env("INVENTORY_MAX_EXTRA_SELL_FRACTION", "0.33"))
    inventory_severe_risk_only: bool = field(default_factory=lambda: _get_bool_env("INVENTORY_SEVERE_RISK_ONLY", True))
    inventory_min_residual_base: Decimal = field(default_factory=lambda: _get_decimal_env("INVENTORY_MIN_RESIDUAL_BASE", "0"))
    inventory_reduce_fraction_on_severe: Decimal = field(default_factory=lambda: _get_decimal_env("INVENTORY_REDUCE_FRACTION_ON_SEVERE", "0.50"))

    def __post_init__(self) -> None:
        result = load_approved_parameter_profile()
        if result.status != "loaded":
            return

        decimal_fields = {
            "MAX_SPREAD_PCT": "max_spread_pct",
            "DEFAULT_QUOTE_SIZE_USDC": "default_quote_size_usdc",
            "MAX_NOTIONAL_USD": "max_notional_usd",
            "AUTONOMOUS_MAX_ORDER_QUOTE": "autonomous_max_order_quote",
            "PHASE_C_MAX_ORDER_QUOTE": "phase_c_max_order_quote",
            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "phase_d3_max_exit_order_quote",
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "phase_d2_min_expected_net_edge_pct",
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "phase_d2_min_reward_to_fee_ratio",
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "phase_d2_min_reward_to_risk_ratio",
            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "exit_target_max_distance_from_mid_pct",
            "SMALL_PROBE_TC_VOL_15M_MIN": "small_probe_tc_vol_15m_min",
            "SMALL_PROBE_TC_VOL_1H_MIN": "small_probe_tc_vol_1h_min",
            "SMALL_PROBE_RC_VOL_15M_MIN": "small_probe_rc_vol_15m_min",
            "SMALL_PROBE_RC_VOL_1H_MIN": "small_probe_rc_vol_1h_min",
        }
        int_fields = {
            "AUTONOMOUS_MAX_OPEN_ORDERS": "autonomous_max_open_orders",
            "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "autonomous_max_new_orders_per_cycle",
            # MAX_OPEN_POSITIONS was whitelisted but never mapped here, making it a
            # silent no-op via the approved-profile route (only .env had effect). Fixed 2026-07-02.
            "MAX_OPEN_POSITIONS": "max_open_positions",
            "JUDGE_MIN_GATE_CONFIDENCE": "judge_min_gate_confidence",
            "SMALL_PROBE_MAX_BEAR_BULL_GAP": "small_probe_max_bear_bull_gap",
            "SMALL_PROBE_TC_SYNTH_MIN": "small_probe_tc_synth_min",
            "SMALL_PROBE_TC_BULL_MIN": "small_probe_tc_bull_min",
            "SMALL_PROBE_TC_BREAKOUT_CONFIRMATION_MIN": "small_probe_tc_breakout_confirmation_min",
            "SMALL_PROBE_RC_SYNTH_MIN": "small_probe_rc_synth_min",
            "SMALL_PROBE_RC_BULL_MIN": "small_probe_rc_bull_min",
            "SMALL_PROBE_RC_BREAKOUT_CONFIRMATION_MIN": "small_probe_rc_breakout_confirmation_min",
        }
        bool_fields = {
            "SMALL_PROBE_REQUIRE_HTF_BOTH_TIMEFRAMES": "small_probe_require_htf_both_timeframes",
        }
        for key, attr in decimal_fields.items():
            if key in result.values:
                try:
                    setattr(self, attr, Decimal(result.values[key]))
                except InvalidOperation as exc:
                    raise ValueError(f"{key} moet een decimaal getal zijn, ontvangen: {result.values[key]}") from exc
        for key, attr in int_fields.items():
            if key in result.values:
                try:
                    setattr(self, attr, int(result.values[key]))
                except ValueError as exc:
                    raise ValueError(f"{key} moet een integer zijn, ontvangen: {result.values[key]}") from exc
        for key, attr in bool_fields.items():
            if key in result.values:
                setattr(self, attr, str(result.values[key]).strip().lower() in {"1", "true", "yes", "on"})

    def validate(self) -> None:
        if self.execution_mode not in {"paper", "live"}:
            raise ValueError("EXECUTION_MODE moet 'paper' of 'live' zijn")

        if not self.allowed_tickers:
            raise ValueError("ALLOWED_TICKERS mag niet leeg zijn")

        if self.primary_interval_hours <= 0:
            raise ValueError("PRIMARY_INTERVAL_HOURS moet > 0 zijn")

        if self.cooldown_minutes < 0:
            raise ValueError("COOLDOWN_MINUTES moet >= 0 zijn")

        if self.max_open_positions <= 0:
            raise ValueError("MAX_OPEN_POSITIONS moet > 0 zijn")

        if self.max_daily_loss_usdc <= Decimal("0"):
            raise ValueError("MAX_DAILY_LOSS_USDC moet > 0 zijn")

        if self.default_quote_size_usdc <= Decimal("0"):
            raise ValueError("DEFAULT_QUOTE_SIZE_USDC moet > 0 zijn")

        if self.max_notional_usd <= Decimal("0"):
            raise ValueError("MAX_NOTIONAL_USD moet > 0 zijn")

        if self.min_live_order_quote_usdc < MIN_LIVE_ORDER_QUOTE_USDC:
            raise ValueError("MIN_LIVE_ORDER_QUOTE_USDC moet >= 50.00 zijn")
        if self.max_live_order_quote_usdc > MAX_LIVE_ORDER_QUOTE_USDC:
            raise ValueError("MAX_LIVE_ORDER_QUOTE_USDC moet <= 100.00 zijn")
        if self.min_live_order_quote_usdc > self.max_live_order_quote_usdc:
            raise ValueError("MIN_LIVE_ORDER_QUOTE_USDC moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")
        if self.default_quote_size_usdc < self.min_live_order_quote_usdc:
            raise ValueError("DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn")
        if self.default_quote_size_usdc > self.max_live_order_quote_usdc:
            raise ValueError("DEFAULT_QUOTE_SIZE_USDC moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")
        if self.max_notional_usd > self.max_live_order_quote_usdc:
            raise ValueError("MAX_NOTIONAL_USD moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")
        if self.min_dynamic_entry_quote_usdc < MIN_LIVE_ORDER_QUOTE_USDC:
            raise ValueError("MIN_DYNAMIC_ENTRY_QUOTE_USDC moet >= 50.00 zijn")
        if self.max_dynamic_entry_quote_usdc > MAX_LIVE_ORDER_QUOTE_USDC:
            raise ValueError("MAX_DYNAMIC_ENTRY_QUOTE_USDC moet <= 100.00 zijn")
        if self.min_dynamic_entry_quote_usdc > self.max_dynamic_entry_quote_usdc:
            raise ValueError("MIN_DYNAMIC_ENTRY_QUOTE_USDC moet <= MAX_DYNAMIC_ENTRY_QUOTE_USDC zijn")
        if self.min_dynamic_entry_quote_usdc < self.min_live_order_quote_usdc:
            raise ValueError("MIN_DYNAMIC_ENTRY_QUOTE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn")
        if self.max_dynamic_entry_quote_usdc > self.max_live_order_quote_usdc:
            raise ValueError("MAX_DYNAMIC_ENTRY_QUOTE_USDC moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")

        if self.max_spread_pct <= Decimal("0"):
            raise ValueError("MAX_SPREAD_PCT moet > 0 zijn")

        if self.coinbase_timeout_seconds <= 0:
            raise ValueError("COINBASE_TIMEOUT_SECONDS moet > 0 zijn")

        if not self.coinbase_api_host:
            raise ValueError("COINBASE_API_HOST mag niet leeg zijn")

        if self.enable_deepseek_preprocess:
            if not self.deepseek_api_key:
                raise ValueError("ENABLE_DEEPSEEK_PREPROCESS vereist DEEPSEEK_API_KEY")
            if not self.deepseek_base_url.startswith("http"):
                raise ValueError("DEEPSEEK_BASE_URL moet met http of https beginnen")
            if not self.deepseek_model:
                raise ValueError("DEEPSEEK_MODEL mag niet leeg zijn")

        if not self.openai_model:
            raise ValueError("OPENAI_MODEL mag niet leeg zijn")

        if not self.openai_analyst_model:
            raise ValueError("OPENAI_ANALYST_MODEL mag niet leeg zijn")

        if not self.openai_judge_model:
            raise ValueError("OPENAI_JUDGE_MODEL mag niet leeg zijn")

        if not self.openai_trade_planner_model:
            raise ValueError("OPENAI_TRADE_PLANNER_MODEL mag niet leeg zijn")

        if not self.openai_execution_planner_model:
            raise ValueError("OPENAI_EXECUTION_PLANNER_MODEL mag niet leeg zijn")

        if self.enable_anthropic_fallback:
            if not self.anthropic_api_key:
                raise ValueError("ENABLE_ANTHROPIC_FALLBACK vereist ANTHROPIC_API_KEY")
            if not self.anthropic_model:
                raise ValueError("ANTHROPIC_MODEL mag niet leeg zijn als ENABLE_ANTHROPIC_FALLBACK=true")

        if self.news_timeout_seconds <= 0:
            raise ValueError("NEWS_TIMEOUT_SECONDS moet > 0 zijn")

        if self.news_lookback_hours <= 0:
            raise ValueError("NEWS_LOOKBACK_HOURS moet > 0 zijn")

        if self.news_max_items_per_feed <= 0:
            raise ValueError("NEWS_MAX_ITEMS_PER_FEED moet > 0 zijn")

        if self.news_max_headlines <= 0:
            raise ValueError("NEWS_MAX_HEADLINES moet > 0 zijn")

        if not self.fng_api_url.startswith("http"):
            raise ValueError("FNG_API_URL moet met http of https beginnen")

        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL moet een geldige loggingwaarde zijn")

        if self.max_candidates_for_deep_analysis <= 0:
            raise ValueError("MAX_CANDIDATES_FOR_DEEP_ANALYSIS moet > 0 zijn")

        if self.max_candidates_for_deepseek_gate <= 0:
            raise ValueError("MAX_CANDIDATES_FOR_DEEPSEEK_GATE moet > 0 zijn")

        if self.max_candidates_for_deepseek_gate < self.max_candidates_for_deep_analysis:
            raise ValueError("MAX_CANDIDATES_FOR_DEEPSEEK_GATE mag niet kleiner zijn dan MAX_CANDIDATES_FOR_DEEP_ANALYSIS")

        if self.max_priority_candidates <= 0:
            raise ValueError("MAX_PRIORITY_CANDIDATES moet > 0 zijn")

        if self.max_priority_candidates > self.max_candidates_for_deep_analysis:
            raise ValueError("MAX_PRIORITY_CANDIDATES mag niet groter zijn dan MAX_CANDIDATES_FOR_DEEP_ANALYSIS")

        if self.breadth_relaxation_min_tickers <= 0:
            raise ValueError("BREADTH_RELAXATION_MIN_TICKERS moet > 0 zijn")

        if self.watch_promotion_memory_cycles <= 0:
            raise ValueError("WATCH_PROMOTION_MEMORY_CYCLES moet > 0 zijn")

        if self.llm_max_raw_chars <= 0:
            raise ValueError("LLM_MAX_RAW_CHARS moet > 0 zijn")
        if self.llm_corrupt_max_raw_chars <= 0:
            raise ValueError("LLM_CORRUPT_MAX_RAW_CHARS moet > 0 zijn")

        for name, value in {
            "JUDGE_MIN_GATE_CONFIDENCE": self.judge_min_gate_confidence,
            "JUDGE_MIN_SYNTH_CONFIDENCE": self.judge_min_synth_confidence,
            "JUDGE_MIN_BULL_SCORE": self.judge_min_bull_score,
            "JUDGE_MAX_BEAR_SCORE": self.judge_max_bear_score,
        }.items():
            if value < 0 or value > 100:
                raise ValueError(f"{name} moet tussen 0 en 100 liggen")

        for name, value in {
            "JUDGE_SOFT_OVERRIDE_MIN_CONFIDENCE": self.judge_soft_override_min_confidence,
            "JUDGE_ENTRY_ESCALATION_MIN_SCORE": self.judge_entry_escalation_min_score,
        }.items():
            if value < 0 or value > 100:
                raise ValueError(f"{name} moet tussen 0 en 100 liggen")

        if self.judge_soft_override_min_adx < Decimal("0") or self.judge_soft_override_min_adx > Decimal("100"):
            raise ValueError("JUDGE_SOFT_OVERRIDE_MIN_ADX moet tussen 0 en 100 liggen")

        if self.judge_soft_override_max_count < 0:
            raise ValueError("JUDGE_SOFT_OVERRIDE_MAX_COUNT moet >= 0 zijn")

        if self.judge_runner_partial_fraction <= Decimal("0") or self.judge_runner_partial_fraction >= Decimal("1"):
            raise ValueError("JUDGE_RUNNER_PARTIAL_FRACTION moet > 0 en < 1 zijn")

        if self.judge_runner_trailing_distance_pct <= Decimal("0") or self.judge_runner_trailing_distance_pct > Decimal("0.20"):
            raise ValueError("JUDGE_RUNNER_TRAILING_DISTANCE_PCT moet > 0 en <= 0.20 zijn")

        if self.judge_entry_escalation_max_per_cycle < 0:
            raise ValueError("JUDGE_ENTRY_ESCALATION_MAX_PER_CYCLE moet >= 0 zijn")

        if self.judge_entry_starter_size_fraction <= Decimal("0") or self.judge_entry_starter_size_fraction > Decimal("1"):
            raise ValueError("JUDGE_ENTRY_STARTER_SIZE_FRACTION moet > 0 en <= 1 zijn")

        if self.judge_entry_max_override_size_usdc < Decimal("0"):
            raise ValueError("JUDGE_ENTRY_MAX_OVERRIDE_SIZE_USDC moet >= 0 zijn")

        if self.default_quote_size_usdc > MAX_LIVE_ORDER_QUOTE_USDC:
            raise ValueError("DEFAULT_QUOTE_SIZE_USDC hoort voor deze bot niet boven 100 te liggen")

        if self.trade_reflection_max_records <= 0:
            raise ValueError("TRADE_REFLECTION_MAX_RECORDS moet > 0 zijn")

        if self.trade_reflection_recent_limit <= 0:
            raise ValueError("TRADE_REFLECTION_RECENT_LIMIT moet > 0 zijn")

        if self.trade_reflection_min_samples_for_signal < 2:
            raise ValueError("TRADE_REFLECTION_MIN_SAMPLES_FOR_SIGNAL moet >= 2 zijn")

        if self.trade_reflection_analytics_limit <= 0:
            raise ValueError("TRADE_REFLECTION_ANALYTICS_LIMIT moet > 0 zijn")

        if self.decision_outcome_max_records <= 0:
            raise ValueError("DECISION_OUTCOME_MAX_RECORDS moet > 0 zijn")

        if self.decision_outcome_summary_limit <= 0:
            raise ValueError("DECISION_OUTCOME_SUMMARY_LIMIT moet > 0 zijn")

        if self.decision_outcome_min_move_pct < Decimal("0") or self.decision_outcome_min_move_pct > Decimal("0.50"):
            raise ValueError("DECISION_OUTCOME_MIN_MOVE_PCT moet tussen 0 en 0.50 liggen")

        if self.decision_outcome_adverse_move_pct < Decimal("0") or self.decision_outcome_adverse_move_pct > Decimal("0.50"):
            raise ValueError("DECISION_OUTCOME_ADVERSE_MOVE_PCT moet tussen 0 en 0.50 liggen")

        for raw_horizon in str(self.decision_outcome_horizons_hours).split(","):
            raw_horizon = raw_horizon.strip()
            if not raw_horizon:
                continue
            try:
                horizon = int(raw_horizon)
            except ValueError as exc:
                raise ValueError("DECISION_OUTCOME_HORIZONS_HOURS moet komma-gescheiden integers bevatten") from exc
            if horizon <= 0:
                raise ValueError("DECISION_OUTCOME_HORIZONS_HOURS mag alleen waarden > 0 bevatten")

        if self.pending_trade_plan_ttl_hours <= 0:
            raise ValueError("PENDING_TRADE_PLAN_TTL_HOURS moet > 0 zijn")

        if self.pending_trade_plan_max_records <= 0:
            raise ValueError("PENDING_TRADE_PLAN_MAX_RECORDS moet > 0 zijn")

        if self.pending_trade_plan_min_confidence < 0 or self.pending_trade_plan_min_confidence > 100:
            raise ValueError("PENDING_TRADE_PLAN_MIN_CONFIDENCE moet tussen 0 en 100 liggen")

        if self.pending_trade_plan_trigger_score < 0 or self.pending_trade_plan_trigger_score > 100:
            raise ValueError("PENDING_TRADE_PLAN_TRIGGER_SCORE moet tussen 0 en 100 liggen")

        if self.pending_trade_plan_max_chase_distance_pct < Decimal("0") or self.pending_trade_plan_max_chase_distance_pct > Decimal("0.20"):
            raise ValueError("PENDING_TRADE_PLAN_MAX_CHASE_DISTANCE_PCT moet tussen 0 en 0.20 liggen")

        if self.order_review_interval_hours <= 0:
            raise ValueError("ORDER_REVIEW_INTERVAL_HOURS moet > 0 zijn")

        expiry_groups = {
            "ENTRY_LIMIT_ORDER": (self.entry_limit_order_min_expiry_hours, self.entry_limit_order_default_expiry_hours, self.entry_limit_order_max_expiry_hours),
            "EXIT_LIMIT_ORDER": (self.exit_limit_order_min_expiry_hours, self.exit_limit_order_default_expiry_hours, self.exit_limit_order_max_expiry_hours),
            "ADD_TO_POSITION_ORDER": (self.add_to_position_order_min_expiry_hours, self.add_to_position_order_default_expiry_hours, self.add_to_position_order_max_expiry_hours),
        }
        for prefix, (min_hours, default_hours, max_hours) in expiry_groups.items():
            if min_hours < 0 or default_hours < 0 or max_hours < 0:
                raise ValueError(f"{prefix}_EXPIRY_HOURS waarden moeten >= 0 zijn")
            if min_hours > default_hours or default_hours > max_hours:
                raise ValueError(f"{prefix}_MIN/DEFAULT/MAX_EXPIRY_HOURS moeten oplopend zijn")

        for name, value in {
            "MAX_ORDER_REPLACES_PER_TICKER_PER_HOUR": self.max_order_replaces_per_ticker_per_hour,
            "MAX_ORDER_ACTIONS_PER_CYCLE": self.max_order_actions_per_cycle,
            "MAX_NEW_ORDERS_PER_CYCLE": self.max_new_orders_per_cycle,
            "MAX_CANCELS_PER_CYCLE": self.max_cancels_per_cycle,
            "MAX_REPLACES_PER_CYCLE": self.max_replaces_per_cycle,
            "MAX_ADDS_PER_POSITION": self.max_adds_per_position,
        }.items():
            if value < 0:
                raise ValueError(f"{name} moet >= 0 zijn")

        if self.order_store_max_records <= 0:
            raise ValueError("ORDER_STORE_MAX_RECORDS moet > 0 zijn")

        if self.paper_no_fill_followup_min_move_pct < Decimal("0") or self.paper_no_fill_followup_min_move_pct > Decimal("0.20"):
            raise ValueError("PAPER_NO_FILL_FOLLOWUP_MIN_MOVE_PCT moet tussen 0 en 0.20 liggen")

        for name, value in {
            "MAX_OPEN_PAPER_ORDERS_TOTAL": self.max_open_paper_orders_total,
            "MAX_OPEN_PAPER_ENTRY_ORDERS_PER_TICKER": self.max_open_paper_entry_orders_per_ticker,
            "MAX_OPEN_PAPER_EXIT_ORDERS_PER_TICKER": self.max_open_paper_exit_orders_per_ticker,
            "PAPER_PENDING_INTENT_TTL_HOURS": self.paper_pending_intent_ttl_hours,
            "PAPER_PENDING_INTENT_MAX_RECORDS": self.paper_pending_intent_max_records,
            "PAPER_PENDING_INTENT_MAX_REPLACED_PER_TICKER": self.paper_pending_intent_max_replaced_per_ticker,
            "PAPER_PENDING_INTENT_FINAL_RETENTION_HOURS": self.paper_pending_intent_final_retention_hours,
        }.items():
            if value < 0:
                raise ValueError(f"{name} moet >= 0 zijn")

        if self.paper_pending_intent_ttl_hours <= 0:
            raise ValueError("PAPER_PENDING_INTENT_TTL_HOURS moet > 0 zijn")

        if self.paper_pending_intent_max_records <= 0:
            raise ValueError("PAPER_PENDING_INTENT_MAX_RECORDS moet > 0 zijn")

        if self.paper_pending_intent_min_gate_confidence < 0 or self.paper_pending_intent_min_gate_confidence > 100:
            raise ValueError("PAPER_PENDING_INTENT_MIN_GATE_CONFIDENCE moet tussen 0 en 100 liggen")

        if self.paper_pending_intent_dedupe_tolerance_pct < Decimal("0") or self.paper_pending_intent_dedupe_tolerance_pct > Decimal("0.10"):
            raise ValueError("PAPER_PENDING_INTENT_DEDUPE_TOLERANCE_PCT moet tussen 0 en 0.10 liggen")

        if self.neural_shadow_policy_min_samples < 1:
            raise ValueError("NEURAL_SHADOW_POLICY_MIN_SAMPLES moet >= 1 zijn")
        if self.neural_shadow_policy_min_confidence < Decimal("0") or self.neural_shadow_policy_min_confidence > Decimal("1"):
            raise ValueError("NEURAL_SHADOW_POLICY_MIN_CONFIDENCE moet tussen 0 en 1 liggen")
        if self.neural_shadow_policy_execution_allowed:
            raise ValueError("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=true is geblokkeerd: v1 is shadow-only en vereist later een hash-gated approval route")

        # Validate the most dangerous live-submit switch first.  This keeps
        # operator/test feedback explicit: if actual Coinbase submit is enabled
        # without the Phase-C master switch, the error must name
        # ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT rather than the broader paper-only
        # live-limit-order warning below.
        if self.enable_phase_c_actual_coinbase_submit and not self.enable_phase_c_live_submit_infrastructure:
            raise ValueError("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT vereist ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true")
        if self.enable_phase_c_actual_coinbase_submit and not self.enable_phase_c_live_small_limit_orders:
            raise ValueError("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT vereist ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true")

        live_limit_flags_enabled = self.enable_live_limit_orders or self.enable_live_entry_orders or self.enable_live_exit_orders
        if self.enable_limit_order_manager and live_limit_flags_enabled and not self.enable_phase_c_live_small_limit_orders:
            raise ValueError(
                "Fase B is paper-only: zet ENABLE_LIVE_LIMIT_ORDERS, "
                "ENABLE_LIVE_ENTRY_ORDERS en ENABLE_LIVE_EXIT_ORDERS op false, "
                "of ontwerp/activeer expliciet ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS"
            )

        if self.enable_full_workflow_live_mode:
            if self.phase_c_max_order_quote > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_ORDER_QUOTE<=MAX_LIVE_ORDER_QUOTE_USDC")
            if self.autonomous_max_order_quote > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist AUTONOMOUS_MAX_ORDER_QUOTE<=MAX_LIVE_ORDER_QUOTE_USDC")
            if not self.enable_phase_d3_actual_exit_submit:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=true")

        if self.phase_c_max_order_quote <= Decimal("0"):
            raise ValueError("PHASE_C_MAX_ORDER_QUOTE moet > 0 zijn")
        if self.phase_c_max_order_quote > self.max_notional_usd:
            raise ValueError("PHASE_C_MAX_ORDER_QUOTE mag niet groter zijn dan MAX_NOTIONAL_USD")
        for name, value in {
            "PHASE_C_MAX_OPEN_ENTRY_ORDERS": self.phase_c_max_open_entry_orders,
            "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": self.phase_c_max_new_orders_per_cycle,
            "PHASE_C_MAX_CANCELS_PER_CYCLE": self.phase_c_max_cancels_per_cycle,
            "PHASE_C_MAX_REPLACES_PER_CYCLE": self.phase_c_max_replaces_per_cycle,
            "PHASE_C_ENTRY_ORDER_MIN_EXPIRY_MINUTES": self.phase_c_entry_order_min_expiry_minutes,
            "PHASE_C_ENTRY_ORDER_DEFAULT_EXPIRY_MINUTES": self.phase_c_entry_order_default_expiry_minutes,
            "PHASE_C_ENTRY_ORDER_MAX_EXPIRY_HOURS": self.phase_c_entry_order_max_expiry_hours,
        }.items():
            if value < 0:
                raise ValueError(f"{name} moet >= 0 zijn")
        if self.phase_c_entry_order_min_expiry_minutes > self.phase_c_entry_order_default_expiry_minutes:
            raise ValueError("PHASE_C_ENTRY_ORDER_MIN_EXPIRY_MINUTES moet <= PHASE_C_ENTRY_ORDER_DEFAULT_EXPIRY_MINUTES zijn")
        if self.phase_c_entry_order_default_expiry_minutes > self.phase_c_entry_order_max_expiry_hours * 60:
            raise ValueError("PHASE_C_ENTRY_ORDER_DEFAULT_EXPIRY_MINUTES moet <= PHASE_C_ENTRY_ORDER_MAX_EXPIRY_HOURS*60 zijn")

        if self.enable_autonomous_small_live_orderbook_mode:
            if self.autonomous_max_order_quote <= Decimal("0"):
                raise ValueError("AUTONOMOUS_MAX_ORDER_QUOTE moet > 0 zijn")
            if self.autonomous_max_order_quote > self.max_live_order_quote_usdc:
                raise ValueError("AUTONOMOUS_MAX_ORDER_QUOTE mag niet boven MAX_LIVE_ORDER_QUOTE_USDC liggen")
            if self.autonomous_max_open_orders < 1 or self.autonomous_max_open_orders > 5:
                raise ValueError("AUTONOMOUS_MAX_OPEN_ORDERS moet tussen 1 en 5 liggen")
            if self.autonomous_max_new_orders_per_cycle < 1 or self.autonomous_max_new_orders_per_cycle > 2:
                raise ValueError("AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE moet tussen 1 en 2 liggen in de eerste full maker-BUY fase")
            if self.autonomous_max_cancels_per_cycle < 0 or self.autonomous_max_cancels_per_cycle > 2:
                raise ValueError("AUTONOMOUS_MAX_CANCELS_PER_CYCLE moet tussen 0 en 2 liggen")
            if self.autonomous_max_replaces_per_cycle < 0 or self.autonomous_max_replaces_per_cycle > 1:
                raise ValueError("AUTONOMOUS_MAX_REPLACES_PER_CYCLE moet tussen 0 en 1 liggen")
            if not self.autonomous_require_post_only:
                raise ValueError("AUTONOMOUS_REQUIRE_POST_ONLY moet true blijven in de eerste autonome fase")
            if not self.autonomous_entry_only_first and not self.enable_phase_d3_actual_exit_submit:
                raise ValueError("AUTONOMOUS_ENTRY_ONLY_FIRST moet true blijven tot D.3 actual exits expliciet actief zijn")
            if (self.autonomous_allow_exits or self.enable_live_exit_orders) and not self.enable_phase_d3_controlled_live_exits:
                raise ValueError("Autonomous small-live fase start entry-only: exits moeten uit blijven, tenzij D.3 controlled exits expliciet actief is")
            if self.enable_phase_d3_actual_exit_submit and self.autonomous_entry_only_first:
                raise ValueError("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist AUTONOMOUS_ENTRY_ONLY_FIRST=false")
            if self.phase_c_max_order_quote > self.autonomous_max_order_quote:
                raise ValueError("PHASE_C_MAX_ORDER_QUOTE mag niet groter zijn dan AUTONOMOUS_MAX_ORDER_QUOTE")
            if self.phase_c_max_open_entry_orders > self.autonomous_max_open_orders:
                raise ValueError("PHASE_C_MAX_OPEN_ENTRY_ORDERS mag niet groter zijn dan AUTONOMOUS_MAX_OPEN_ORDERS")
            if self.enable_phase_c43_autonomous_entry_submitter and not self.autonomous_entry_only_first and not self.enable_phase_d3_actual_exit_submit:
                raise ValueError("ENABLE_PHASE_C43_AUTONOMOUS_ENTRY_SUBMITTER vereist AUTONOMOUS_ENTRY_ONLY_FIRST=true tot D.3 actual exits expliciet actief zijn")

        if self.enable_full_workflow_live_mode:
            if self.execution_mode != "live":
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist EXECUTION_MODE=live")
            if self.min_live_order_quote_usdc < MIN_LIVE_ORDER_QUOTE_USDC:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MIN_LIVE_ORDER_QUOTE_USDC>=50.00")
            if self.max_live_order_quote_usdc > MAX_LIVE_ORDER_QUOTE_USDC:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MAX_LIVE_ORDER_QUOTE_USDC<=100.00")
            if self.max_open_positions != 3:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MAX_OPEN_POSITIONS=3")
            if self.autonomous_max_open_orders != 3:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist AUTONOMOUS_MAX_OPEN_ORDERS=3")
            if self.phase_c_max_open_entry_orders != 3:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_OPEN_ENTRY_ORDERS=3")
            if self.max_new_orders_per_cycle != 1:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MAX_NEW_ORDERS_PER_CYCLE=1")
            if self.autonomous_max_new_orders_per_cycle != 1:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1")
            if self.phase_c_max_new_orders_per_cycle != 1:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1")
            if self.default_quote_size_usdc < self.min_live_order_quote_usdc or self.default_quote_size_usdc > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist DEFAULT_QUOTE_SIZE_USDC binnen live min/max")
            if self.max_notional_usd > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MAX_NOTIONAL_USD<=100.00")
            if self.phase_c_max_order_quote > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_ORDER_QUOTE<=100.00")
            if self.autonomous_max_order_quote > self.max_live_order_quote_usdc:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist AUTONOMOUS_MAX_ORDER_QUOTE<=100.00")
            if not self.enable_dynamic_entry_sizing:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist ENABLE_DYNAMIC_ENTRY_SIZING=true")
            if self.min_dynamic_entry_quote_usdc != Decimal("50.00") or self.max_dynamic_entry_quote_usdc != Decimal("100.00"):
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist MIN/MAX_DYNAMIC_ENTRY_QUOTE_USDC=50/100")
            required_true = {
                "ENABLE_LIVE_ENTRY_ORDERS": self.enable_live_entry_orders,
                "ENABLE_LIVE_LIMIT_ORDERS": self.enable_live_limit_orders,
                "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": self.enable_phase_c_live_small_limit_orders,
                "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": self.enable_autonomous_small_live_orderbook_mode,
                "ENABLE_LIMIT_ORDER_MANAGER": self.enable_limit_order_manager,
                "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": self.enable_phase_c_live_submit_infrastructure,
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": self.enable_phase_c_actual_coinbase_submit,
                "ENABLE_LIVE_EXIT_ORDERS": self.enable_live_exit_orders,
                "AUTONOMOUS_ALLOW_EXITS": self.autonomous_allow_exits,
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": self.enable_phase_d3_actual_exit_submit,
            }
            missing = [name for name, ok in required_true.items() if not ok]
            if missing:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE mist vereiste true flags: " + ",".join(sorted(missing)))
            if self.phase_c_disable_exit_limit_orders:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false zodat D.3 exits niet door Phase-C entry-only guard worden geblokkeerd")
            if self.autonomous_entry_only_first:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist AUTONOMOUS_ENTRY_ONLY_FIRST=false zodat D.3 exits na fills toegestaan zijn")
            if self.phase_d3_max_exit_order_quote > MAX_LIVE_EXIT_ORDER_QUOTE_USDC:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_D3_MAX_EXIT_ORDER_QUOTE<=120.00")
            if self.phase_d3_max_open_exit_orders > 3:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_D3_MAX_OPEN_EXIT_ORDERS<=3")
            replication_flags = {
                "REPLICATION_ENABLED": self.replication_enabled,
                "REPLICATION_LIFECYCLE_ENABLED": self.replication_lifecycle_enabled,
                "REPLICATION_LIFECYCLE_HTTP_ENABLED": self.replication_lifecycle_http_enabled,
            }
            enabled_replication = [name for name, ok in replication_flags.items() if ok]
            if enabled_replication:
                raise ValueError(
                    "ENABLE_FULL_WORKFLOW_LIVE_MODE verbiedt replication flags: "
                    + ",".join(sorted(enabled_replication))
                )

            disabled_env_flags = [
                "LEARNING_TO_EXECUTION_READY",
                "LEARNING_TO_EXECUTION_ALLOWED",
                "LIVE_LEARNING_ALLOWED",
                "PARAMETER_CHANGE_ALLOWED",
                "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED",
            ]
            enabled_forbidden = [name for name in disabled_env_flags if _get_bool_env(name, False)]
            if enabled_forbidden:
                raise ValueError("ENABLE_FULL_WORKFLOW_LIVE_MODE verbiedt flags: " + ",".join(sorted(enabled_forbidden)))
            market_flags = {
                "MARKET_ORDER_ENABLED": self.market_order_enabled,
                "ENABLE_MARKET_ORDERS": self.enable_market_orders,
                "ALLOW_MARKET_ORDERS": self.allow_market_orders,
            }
            market_any = any(market_flags.values())
            if market_any:
                enabled = [name for name, ok in market_flags.items() if ok]
                raise ValueError(
                    "ENABLE_FULL_WORKFLOW_LIVE_MODE is orderbook-only en vereist market-order flags false: "
                    + ",".join(sorted(enabled))
                )

        if self.enable_phase_c_live_small_limit_orders:
            if self.execution_mode != "live":
                raise ValueError("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS vereist EXECUTION_MODE=live")
            if not self.enable_limit_order_manager:
                raise ValueError("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS vereist ENABLE_LIMIT_ORDER_MANAGER=true")
            if not self.enable_live_limit_orders or not self.enable_live_entry_orders:
                raise ValueError("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS vereist ENABLE_LIVE_LIMIT_ORDERS=true en ENABLE_LIVE_ENTRY_ORDERS=true")
            if self.phase_c_disable_exit_limit_orders and self.enable_live_exit_orders and not self.enable_phase_d3_actual_exit_submit:
                raise ValueError("Fase C is entry-only: zet ENABLE_LIVE_EXIT_ORDERS=false, tenzij D.3 actual exit submit expliciet actief is")
            allowed_set = set(self.allowed_tickers)
            for ticker in self.phase_c_allowed_tickers:
                if ticker not in allowed_set:
                    raise ValueError(f"PHASE_C_ALLOWED_TICKERS bevat ticker buiten ALLOWED_TICKERS: {ticker}")
            for ticker in self.autonomous_allowed_tickers:
                if ticker not in allowed_set:
                    raise ValueError(f"AUTONOMOUS_ALLOWED_TICKERS bevat ticker buiten ALLOWED_TICKERS: {ticker}")
            if not effective_phase_c_allowed_tickers(self):
                raise ValueError("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS vereist configured ticker universe")
            if self.phase_c_max_open_entry_orders < 1:
                raise ValueError("PHASE_C_MAX_OPEN_ENTRY_ORDERS moet >= 1 zijn als fase C actief is")
            if self.phase_c_max_new_orders_per_cycle < 1:
                raise ValueError("PHASE_C_MAX_NEW_ORDERS_PER_CYCLE moet >= 1 zijn als fase C actief is")

        if self.phase_c_max_order_quote > self.max_live_order_quote_usdc:
            raise ValueError("PHASE_C_MAX_ORDER_QUOTE moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")
        if self.autonomous_max_order_quote > self.max_live_order_quote_usdc:
            raise ValueError("AUTONOMOUS_MAX_ORDER_QUOTE moet <= MAX_LIVE_ORDER_QUOTE_USDC zijn")

        if self.enable_phase_d2_position_executor:
            if self.phase_d2_min_expected_net_edge_pct <= Decimal("0"):
                raise ValueError("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT moet > 0 zijn")
            if self.phase_d2_min_expected_net_edge_pct > Decimal("0.20"):
                raise ValueError("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT hoort <= 0.20 te blijven")
            if self.phase_d2_min_reward_to_fee_ratio < Decimal("1"):
                raise ValueError("PHASE_D2_MIN_REWARD_TO_FEE_RATIO moet >= 1 zijn")
            if self.phase_d2_min_reward_to_risk_ratio <= Decimal("0"):
                raise ValueError("PHASE_D2_MIN_REWARD_TO_RISK_RATIO moet > 0 zijn")
            for name, value in {
                "PHASE_D2_ESTIMATED_ENTRY_FEE_PCT": self.phase_d2_estimated_entry_fee_pct,
                "PHASE_D2_ESTIMATED_EXIT_FEE_PCT": self.phase_d2_estimated_exit_fee_pct,
                "PHASE_D2_ESTIMATED_SPREAD_SLIPPAGE_PCT": self.phase_d2_estimated_spread_slippage_pct,
                "PHASE_D2_FEE_SAFETY_BUFFER_PCT": self.phase_d2_fee_safety_buffer_pct,
                "PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT": self.phase_d2_default_trailing_activation_pct,
                "PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT": self.phase_d2_default_trailing_distance_pct,
            }.items():
                if value < Decimal("0") or value > Decimal("0.50"):
                    raise ValueError(f"{name} moet tussen 0 en 0.50 liggen")
            if self.phase_d2_max_tp_orders_per_position < 0 or self.phase_d2_max_tp_orders_per_position > 2:
                raise ValueError("PHASE_D2_MAX_TP_ORDERS_PER_POSITION mag in D.2 maximaal 2 zijn")
            if self.phase_d2_default_time_limit_hours <= 0:
                raise ValueError("PHASE_D2_DEFAULT_TIME_LIMIT_HOURS moet > 0 zijn")
            if self.phase_d2_allow_averaging_down:
                raise ValueError("PHASE_D2_ALLOW_AVERAGING_DOWN moet in D.2 false blijven")
            if self.phase_d2_max_adds_to_winner < 0 or self.phase_d2_max_adds_to_winner > 1:
                raise ValueError("PHASE_D2_MAX_ADDS_TO_WINNER mag maximaal 1 zijn")
            if self.phase_d2_max_adds_to_winner > 0 and not self.phase_d2_allow_add_to_winner:
                raise ValueError("PHASE_D2_MAX_ADDS_TO_WINNER vereist PHASE_D2_ALLOW_ADD_TO_WINNER=true")


        if self.enable_phase_d3_controlled_live_exits:
            if self.phase_d3_max_exit_order_quote <= Decimal("0") or self.phase_d3_max_exit_order_quote > MAX_LIVE_EXIT_ORDER_QUOTE_USDC:
                raise ValueError("PHASE_D3_MAX_EXIT_ORDER_QUOTE moet > 0 en <= 120.00 zijn")
            if self.phase_d3_max_open_exit_orders < 1 or self.phase_d3_max_open_exit_orders > 4:
                raise ValueError("PHASE_D3_MAX_OPEN_EXIT_ORDERS moet tussen 1 en 4 blijven")
            if self.phase_d3_max_new_exit_orders_per_cycle != 1:
                raise ValueError("PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE moet 1 zijn in de eerste D.3 fase")
            if not self.phase_d3_exit_order_post_only:
                raise ValueError("PHASE_D3_EXIT_ORDER_POST_ONLY moet true blijven")
            if not self.phase_d3_require_reduce_only_local:
                raise ValueError("PHASE_D3_REQUIRE_REDUCE_ONLY_LOCAL moet true blijven")
            if self.enable_phase_d3_actual_exit_submit:
                if self.phase_d3_runtime_submit_ack != D3_CONTROLLED_LIVE_EXIT_ACK_VALUE:
                    raise ValueError(
                        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist exacte "
                        f"{D3_CONTROLLED_LIVE_EXIT_ACK_ENV} ACK"
                    )
                if not self.enable_live_exit_orders:
                    raise ValueError("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist ENABLE_LIVE_EXIT_ORDERS=true")
                if not self.autonomous_allow_exits:
                    raise ValueError("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist AUTONOMOUS_ALLOW_EXITS=true")
                if self.phase_c_disable_exit_limit_orders:
                    raise ValueError("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false")
                if self.autonomous_entry_only_first:
                    raise ValueError("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist AUTONOMOUS_ENTRY_ONLY_FIRST=false")

        if self.controlled_stop_exit_order_type not in {"near_market_limit_ioc"}:
            raise ValueError("CONTROLLED_STOP_EXIT_ORDER_TYPE moet near_market_limit_ioc zijn voor Mode B controlled stop-exit")
        if self.controlled_stop_exit_max_quote_usd <= Decimal("0") or self.controlled_stop_exit_max_quote_usd > MAX_LIVE_EXIT_ORDER_QUOTE_USDC:
            raise ValueError("CONTROLLED_STOP_EXIT_MAX_QUOTE_USD moet > 0 en <= 120.00 zijn")
        if self.controlled_stop_exit_max_slippage_pct < Decimal("0") or self.controlled_stop_exit_max_slippage_pct > Decimal("0.0500"):
            raise ValueError("CONTROLLED_STOP_EXIT_MAX_SLIPPAGE_PCT moet tussen 0 en 0.0500 liggen")
        if self.enable_autonomous_stop_exit_apply and not self.enable_controlled_stop_market_exits:
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY vereist ENABLE_CONTROLLED_STOP_MARKET_EXITS=true")
        if self.enable_autonomous_stop_exit_cancel and not self.enable_controlled_stop_market_exits:
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL vereist ENABLE_CONTROLLED_STOP_MARKET_EXITS=true")
        if self.enable_autonomous_stop_exit_submit and not self.enable_controlled_stop_market_exits:
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT vereist ENABLE_CONTROLLED_STOP_MARKET_EXITS=true")
        if (
            (self.enable_autonomous_stop_exit_cancel or self.enable_autonomous_stop_exit_submit or self.enable_autonomous_stop_exit_apply)
            and self.mode_b_controlled_stop_exit_ack != MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
        ):
            raise ValueError(
                "Autonomous controlled stop-exit vereist exacte "
                f"{MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV} ACK voor Mode B"
            )
        if self.enable_autonomous_stop_exit_submit and not self.enable_autonomous_stop_exit_cancel:
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT vereist ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL=true")
        if self.enable_autonomous_stop_exit_apply and not (self.enable_autonomous_stop_exit_cancel and self.enable_autonomous_stop_exit_submit):
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY vereist ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL=true en ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT=true")
        if self.enable_autonomous_stop_exit_apply and not self.controlled_stop_exit_require_open_tp_cancel_first:
            raise ValueError("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY vereist CONTROLLED_STOP_EXIT_REQUIRE_OPEN_TP_CANCEL_FIRST=true")
        market_flags = {
            "MARKET_ORDER_ENABLED": self.market_order_enabled,
            "ENABLE_MARKET_ORDERS": self.enable_market_orders,
            "ALLOW_MARKET_ORDERS": self.allow_market_orders,
        }
        market_any = any(market_flags.values())
        market_all = all(market_flags.values())
        if market_any and not market_all:
            missing = [name for name, ok in market_flags.items() if not ok]
            raise ValueError("Mode C market orders vereisen alle drie flags true; mist: " + ",".join(sorted(missing)))
        if market_any and self.mode_c_market_order_ack != MODE_C_MARKET_ORDER_ACK_VALUE:
            raise ValueError(f"Mode C market orders vereisen exacte {MODE_C_MARKET_ORDER_ACK_ENV}")
        if market_any and (self.replication_enabled or self.replication_lifecycle_enabled or self.replication_lifecycle_http_enabled):
            raise ValueError("Mode C market orders vereisen REPLICATION_ENABLED=false, REPLICATION_LIFECYCLE_ENABLED=false en REPLICATION_LIFECYCLE_HTTP_ENABLED=false")

        if self.enable_bounded_exploration_mode:
            if self.exploration_allow_market_orders:
                raise ValueError("ENABLE_BOUNDED_EXPLORATION_MODE verbiedt EXPLORATION_ALLOW_MARKET_ORDERS=true")
            if self.exploration_min_order_quote_usdc < MIN_LIVE_ORDER_QUOTE_USDC:
                raise ValueError("EXPLORATION_MIN_ORDER_QUOTE_USDC moet >= 50.00 zijn")
            if self.exploration_max_order_quote_usdc > EXPLORATION_MAX_ORDER_QUOTE_USDC:
                raise ValueError("EXPLORATION_MAX_ORDER_QUOTE_USDC moet <= 35.00 zijn")
            if self.exploration_min_order_quote_usdc > self.exploration_max_order_quote_usdc:
                raise ValueError("EXPLORATION_MIN_ORDER_QUOTE_USDC moet <= EXPLORATION_MAX_ORDER_QUOTE_USDC zijn")
            if self.exploration_max_open_probes < 1:
                raise ValueError("EXPLORATION_MAX_OPEN_PROBES moet >= 1 zijn")
            if self.exploration_max_probes_per_day < 1:
                raise ValueError("EXPLORATION_MAX_PROBES_PER_DAY moet >= 1 zijn")
            if not self.exploration_require_hard_risk_green:
                raise ValueError("EXPLORATION_REQUIRE_HARD_RISK_GREEN moet true blijven")
            if not self.exploration_require_fresh_trigger:
                raise ValueError("EXPLORATION_REQUIRE_FRESH_TRIGGER moet true blijven")
            if not self.exploration_require_no_chase:
                raise ValueError("EXPLORATION_REQUIRE_NO_CHASE moet true blijven")
            if not self.exploration_require_orderbook_snapshot:
                raise ValueError("EXPLORATION_REQUIRE_ORDERBOOK_SNAPSHOT moet true blijven")
            if self.exploration_max_spread_pct <= Decimal("0") or self.exploration_max_spread_pct > Decimal("0.0040"):
                raise ValueError("EXPLORATION_MAX_SPREAD_PCT moet > 0 en <= 0.0040 zijn")

        if self.llm_payload_string_max_chars < 1000:
            raise ValueError("LLM_PAYLOAD_STRING_MAX_CHARS moet >= 1000 zijn")
        if self.llm_payload_hygiene_max_depth < 1:
            raise ValueError("LLM_PAYLOAD_HYGIENE_MAX_DEPTH moet >= 1 zijn")
        if self.llm_repeated_fragment_max_repeats < 1 or self.llm_repeated_fragment_max_repeats > 20:
            raise ValueError("LLM_REPEATED_FRAGMENT_MAX_REPEATS moet tussen 1 en 20 liggen")
        if self.phase_d32_llm_health_window_minutes < 1:
            raise ValueError("PHASE_D32_LLM_HEALTH_WINDOW_MINUTES moet >= 1 zijn")

        if self.max_position_scale_factor < Decimal("1"):
            raise ValueError("MAX_POSITION_SCALE_FACTOR moet >= 1 zijn")

        if self.inventory_sell_mode not in {
            "bot_only",
            "bot_plus_inventory_partial",
            "full_inventory_allowed",
        }:
            raise ValueError(
                "INVENTORY_SELL_MODE moet 'bot_only', 'bot_plus_inventory_partial' of 'full_inventory_allowed' zijn"
            )

        if self.inventory_max_extra_sell_fraction < Decimal("0") or self.inventory_max_extra_sell_fraction > Decimal("1"):
            raise ValueError("INVENTORY_MAX_EXTRA_SELL_FRACTION moet tussen 0 en 1 liggen")

        if self.inventory_reduce_fraction_on_severe < Decimal("0") or self.inventory_reduce_fraction_on_severe > Decimal("1"):
            raise ValueError("INVENTORY_REDUCE_FRACTION_ON_SEVERE moet tussen 0 en 1 liggen")

        if self.inventory_min_residual_base < Decimal("0"):
            raise ValueError("INVENTORY_MIN_RESIDUAL_BASE moet >= 0 zijn")

    def to_dict(self) -> dict:
        return {
            "execution_mode": self.execution_mode,
            "allowed_tickers": self.allowed_tickers,
            "primary_interval_hours": self.primary_interval_hours,
            "cooldown_minutes": self.cooldown_minutes,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss_usdc": str(self.max_daily_loss_usdc),
            "default_quote_size_usdc": str(self.default_quote_size_usdc),
            "max_notional_usd": str(self.max_notional_usd),
            "max_spread_pct": str(self.max_spread_pct),
            "coinbase_api_host": self.coinbase_api_host,
            "coinbase_timeout_seconds": self.coinbase_timeout_seconds,
            "enable_deepseek_preprocess": self.enable_deepseek_preprocess,
            "deepseek_base_url": self.deepseek_base_url,
            "deepseek_model": self.deepseek_model,
            "openai_model": self.openai_model,
            "openai_analyst_model": self.openai_analyst_model,
            "openai_judge_model": self.openai_judge_model,
            "openai_trade_planner_model": self.openai_trade_planner_model,
            "openai_execution_planner_model": self.openai_execution_planner_model,
            "anthropic_fallback_enabled": bool(self.enable_anthropic_fallback and self.anthropic_api_key),
            "enable_anthropic_fallback": self.enable_anthropic_fallback,
            "anthropic_model": self.anthropic_model,
            "news_enabled": self.news_enabled,
            "news_timeout_seconds": self.news_timeout_seconds,
            "news_lookback_hours": self.news_lookback_hours,
            "news_max_items_per_feed": self.news_max_items_per_feed,
            "news_max_headlines": self.news_max_headlines,
            "fng_enabled": self.fng_enabled,
            "fng_api_url": self.fng_api_url,
            "news_rss_feeds": self.news_rss_feeds,
            "log_level": self.log_level,
            "max_candidates_for_deep_analysis": self.max_candidates_for_deep_analysis,
            "max_candidates_for_deepseek_gate": self.max_candidates_for_deepseek_gate,
            "max_priority_candidates": self.max_priority_candidates,
            "enable_candidate_ranking": self.enable_candidate_ranking,
            "enable_strict_meanrev_postfilter": self.enable_strict_meanrev_postfilter,
            "enable_market_breadth_relaxation": self.enable_market_breadth_relaxation,
            "breadth_relaxation_min_tickers": self.breadth_relaxation_min_tickers,
            "watch_promotion_memory_cycles": self.watch_promotion_memory_cycles,
            "llm_raw_logging_enabled": self.llm_raw_logging_enabled,
            "llm_corrupt_logging_enabled": self.llm_corrupt_logging_enabled,
            "llm_max_raw_chars": self.llm_max_raw_chars,
            "llm_corrupt_max_raw_chars": self.llm_corrupt_max_raw_chars,
            "llm_provider_error_logging_enabled": self.llm_provider_error_logging_enabled,
            "llm_context_hygiene_enabled": self.llm_context_hygiene_enabled,
            "llm_payload_string_max_chars": self.llm_payload_string_max_chars,
            "llm_payload_hygiene_max_depth": self.llm_payload_hygiene_max_depth,
            "llm_repeated_fragment_max_repeats": self.llm_repeated_fragment_max_repeats,
            "llm_cost_ledger_enabled": self.llm_cost_ledger_enabled,
            "enable_phase_d32_llm_pre_live_health": self.enable_phase_d32_llm_pre_live_health,
            "phase_d32_llm_health_window_minutes": self.phase_d32_llm_health_window_minutes,
            "phase_d32_block_on_recent_llm_corrupt": self.phase_d32_block_on_recent_llm_corrupt,
            "phase_d32_block_on_recent_provider_errors": self.phase_d32_block_on_recent_provider_errors,
            "enforce_judge_ticker_match": self.enforce_judge_ticker_match,
            "reject_unknown_llm_keys": self.reject_unknown_llm_keys,
            "enable_expensive_judge_gate": self.enable_expensive_judge_gate,
            "judge_min_gate_confidence": self.judge_min_gate_confidence,
            "judge_min_synth_confidence": self.judge_min_synth_confidence,
            "judge_min_bull_score": self.judge_min_bull_score,
            "judge_max_bear_score": self.judge_max_bear_score,
            "judge_soft_override_enabled": self.judge_soft_override_enabled,
            "judge_soft_override_min_confidence": self.judge_soft_override_min_confidence,
            "judge_soft_override_min_adx": str(self.judge_soft_override_min_adx),
            "judge_soft_override_require_profit": self.judge_soft_override_require_profit,
            "judge_soft_override_max_count": self.judge_soft_override_max_count,
            "judge_runner_partial_fraction": str(self.judge_runner_partial_fraction),
            "judge_runner_trailing_distance_pct": str(self.judge_runner_trailing_distance_pct),
            "judge_runner_require_candle_close": self.judge_runner_require_candle_close,
            "judge_conflict_logging_enabled": self.judge_conflict_logging_enabled,
            "judge_entry_escalation_enabled": self.judge_entry_escalation_enabled,
            "judge_entry_escalation_min_score": self.judge_entry_escalation_min_score,
            "judge_entry_escalation_max_per_cycle": self.judge_entry_escalation_max_per_cycle,
            "judge_entry_allow_soft_gate_override": self.judge_entry_allow_soft_gate_override,
            "judge_entry_starter_size_fraction": str(self.judge_entry_starter_size_fraction),
            "judge_entry_max_override_size_usdc": str(self.judge_entry_max_override_size_usdc),
            "enable_trade_reflection_memory": self.enable_trade_reflection_memory,
            "trade_reflection_max_records": self.trade_reflection_max_records,
            "trade_reflection_recent_limit": self.trade_reflection_recent_limit,
            "trade_reflection_min_samples_for_signal": self.trade_reflection_min_samples_for_signal,
            "trade_reflection_analytics_limit": self.trade_reflection_analytics_limit,
            "enable_decision_outcome_tracking": self.enable_decision_outcome_tracking,
            "decision_outcome_max_records": self.decision_outcome_max_records,
            "decision_outcome_horizons_hours": self.decision_outcome_horizons_hours,
            "decision_outcome_min_move_pct": str(self.decision_outcome_min_move_pct),
            "decision_outcome_adverse_move_pct": str(self.decision_outcome_adverse_move_pct),
            "decision_outcome_summary_limit": self.decision_outcome_summary_limit,
            "enable_shadow_outcome_accelerator": self.enable_shadow_outcome_accelerator,
            "enable_pending_trade_plans": self.enable_pending_trade_plans,
            "pending_trade_plan_ttl_hours": self.pending_trade_plan_ttl_hours,
            "pending_trade_plan_max_records": self.pending_trade_plan_max_records,
            "pending_trade_plan_min_confidence": self.pending_trade_plan_min_confidence,
            "pending_trade_plan_trigger_score": self.pending_trade_plan_trigger_score,
            "pending_trade_plan_max_chase_distance_pct": str(self.pending_trade_plan_max_chase_distance_pct),
            "enable_read_only_execution_planner": self.enable_read_only_execution_planner,
            "execution_planner_call_on_wait": self.execution_planner_call_on_wait,
            "allow_gpt_dynamic_order_expiry": self.allow_gpt_dynamic_order_expiry,
            "order_review_interval_hours": self.order_review_interval_hours,
            "entry_limit_order_min_expiry_hours": self.entry_limit_order_min_expiry_hours,
            "entry_limit_order_default_expiry_hours": self.entry_limit_order_default_expiry_hours,
            "entry_limit_order_max_expiry_hours": self.entry_limit_order_max_expiry_hours,
            "exit_limit_order_min_expiry_hours": self.exit_limit_order_min_expiry_hours,
            "exit_limit_order_default_expiry_hours": self.exit_limit_order_default_expiry_hours,
            "exit_limit_order_max_expiry_hours": self.exit_limit_order_max_expiry_hours,
            "add_to_position_order_min_expiry_hours": self.add_to_position_order_min_expiry_hours,
            "add_to_position_order_default_expiry_hours": self.add_to_position_order_default_expiry_hours,
            "add_to_position_order_max_expiry_hours": self.add_to_position_order_max_expiry_hours,
            "max_order_replaces_per_ticker_per_hour": self.max_order_replaces_per_ticker_per_hour,
            "disallow_unreviewed_gtc_orders": self.disallow_unreviewed_gtc_orders,
            "max_order_actions_per_cycle": self.max_order_actions_per_cycle,
            "max_new_orders_per_cycle": self.max_new_orders_per_cycle,
            "max_cancels_per_cycle": self.max_cancels_per_cycle,
            "max_replaces_per_cycle": self.max_replaces_per_cycle,
            "enable_limit_order_manager": self.enable_limit_order_manager,
            "enable_live_limit_orders": self.enable_live_limit_orders,
            "enable_live_entry_orders": self.enable_live_entry_orders,
            "enable_live_exit_orders": self.enable_live_exit_orders,
            "enable_full_workflow_live_mode": self.enable_full_workflow_live_mode,
            "enable_phase_c_live_small_limit_orders": self.enable_phase_c_live_small_limit_orders,
            "phase_c_allowed_tickers": self.phase_c_allowed_tickers,
            "autonomous_allowed_tickers": self.autonomous_allowed_tickers,
            "configured_ticker_universe": configured_ticker_universe(self),
            "effective_phase_c_allowed_tickers": effective_phase_c_allowed_tickers(self),
            "phase_c_max_order_quote": str(self.phase_c_max_order_quote),
            "phase_c_max_open_entry_orders": self.phase_c_max_open_entry_orders,
            "phase_c_max_new_orders_per_cycle": self.phase_c_max_new_orders_per_cycle,
            "phase_c_max_cancels_per_cycle": self.phase_c_max_cancels_per_cycle,
            "phase_c_max_replaces_per_cycle": self.phase_c_max_replaces_per_cycle,
            "phase_c_require_pending_intent": self.phase_c_require_pending_intent,
            "phase_c_require_promotion_ready": self.phase_c_require_promotion_ready,
            "phase_c_require_fresh_judge": self.phase_c_require_fresh_judge,
            "phase_c_require_risk_approval": self.phase_c_require_risk_approval,
            "phase_c_require_orderbook_freshness": self.phase_c_require_orderbook_freshness,
            "phase_c_entry_order_min_expiry_minutes": self.phase_c_entry_order_min_expiry_minutes,
            "phase_c_entry_order_default_expiry_minutes": self.phase_c_entry_order_default_expiry_minutes,
            "phase_c_entry_order_max_expiry_hours": self.phase_c_entry_order_max_expiry_hours,
            "phase_c_disable_exit_limit_orders": self.phase_c_disable_exit_limit_orders,
            "phase_c_paper_shadow_log": self.phase_c_paper_shadow_log,
            "enable_phase_c_live_submit_infrastructure": self.enable_phase_c_live_submit_infrastructure,
            "enable_phase_c_actual_coinbase_submit": self.enable_phase_c_actual_coinbase_submit,
            "phase_c_live_order_post_only": self.phase_c_live_order_post_only,
            "enable_phase_c43_autonomous_entry_submitter": self.enable_phase_c43_autonomous_entry_submitter,
            "phase_c43_runtime_submit_ack_present": bool(self.phase_c43_runtime_submit_ack),
            "phase_c43_runtime_submit_ack_valid": self.phase_c43_runtime_submit_ack == C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
            "enable_phase_c43_lifecycle_orchestrator": self.enable_phase_c43_lifecycle_orchestrator,
            "phase_c43_lifecycle_allow_coinbase_poll": self.phase_c43_lifecycle_allow_coinbase_poll,
            "phase_c43_lifecycle_apply_local": self.phase_c43_lifecycle_apply_local,
            "phase_c43_lifecycle_build_d2_plan": self.phase_c43_lifecycle_build_d2_plan,
            "phase_c43_lifecycle_persist_d2_plan": self.phase_c43_lifecycle_persist_d2_plan,
            "phase_c43_lifecycle_build_d3_preview": self.phase_c43_lifecycle_build_d3_preview,
            "phase_c43_lifecycle_order_store_path": self.phase_c43_lifecycle_order_store_path,
            "phase_c43_lifecycle_order_events_path": self.phase_c43_lifecycle_order_events_path,
            "enable_exchange_inventory_sync": self.enable_exchange_inventory_sync,
            "enable_phase_d2_position_executor": self.enable_phase_d2_position_executor,
            "phase_d2_min_expected_net_edge_pct": str(self.phase_d2_min_expected_net_edge_pct),
            "phase_d2_min_reward_to_fee_ratio": str(self.phase_d2_min_reward_to_fee_ratio),
            "phase_d2_min_reward_to_risk_ratio": str(self.phase_d2_min_reward_to_risk_ratio),
            "phase_d2_estimated_entry_fee_pct": str(self.phase_d2_estimated_entry_fee_pct),
            "phase_d2_estimated_exit_fee_pct": str(self.phase_d2_estimated_exit_fee_pct),
            "phase_d2_estimated_spread_slippage_pct": str(self.phase_d2_estimated_spread_slippage_pct),
            "phase_d2_fee_safety_buffer_pct": str(self.phase_d2_fee_safety_buffer_pct),
            "phase_d2_max_tp_orders_per_position": self.phase_d2_max_tp_orders_per_position,
            "phase_d2_default_time_limit_hours": self.phase_d2_default_time_limit_hours,
            "phase_d2_default_trailing_activation_pct": str(self.phase_d2_default_trailing_activation_pct),
            "phase_d2_default_trailing_distance_pct": str(self.phase_d2_default_trailing_distance_pct),
            "phase_d2_allow_add_to_winner": self.phase_d2_allow_add_to_winner,
            "phase_d2_max_adds_to_winner": self.phase_d2_max_adds_to_winner,
            "phase_d2_allow_averaging_down": self.phase_d2_allow_averaging_down,
            "enable_phase_d3_controlled_live_exits": self.enable_phase_d3_controlled_live_exits,
            "enable_phase_d3_actual_exit_submit": self.enable_phase_d3_actual_exit_submit,
            "phase_d3_runtime_submit_ack_present": bool(self.phase_d3_runtime_submit_ack),
            "phase_d3_runtime_submit_ack_valid": self.phase_d3_runtime_submit_ack == D3_CONTROLLED_LIVE_EXIT_ACK_VALUE,
            "phase_d3_max_exit_order_quote": str(self.phase_d3_max_exit_order_quote),
            "phase_d3_max_open_exit_orders": self.phase_d3_max_open_exit_orders,
            "phase_d3_max_new_exit_orders_per_cycle": self.phase_d3_max_new_exit_orders_per_cycle,
            "phase_d3_exit_order_post_only": self.phase_d3_exit_order_post_only,
            "phase_d3_require_reduce_only_local": self.phase_d3_require_reduce_only_local,
            "enable_controlled_stop_market_exits": self.enable_controlled_stop_market_exits,
            "enable_autonomous_stop_exit_apply": self.enable_autonomous_stop_exit_apply,
            "controlled_stop_exit_max_quote_usd": str(self.controlled_stop_exit_max_quote_usd),
            "controlled_stop_exit_require_open_tp_cancel_first": self.controlled_stop_exit_require_open_tp_cancel_first,
            "controlled_stop_exit_order_type": self.controlled_stop_exit_order_type,
            "controlled_stop_exit_max_slippage_pct": str(self.controlled_stop_exit_max_slippage_pct),
            "enable_autonomous_small_live_orderbook_mode": self.enable_autonomous_small_live_orderbook_mode,
            "enable_dynamic_entry_sizing": self.enable_dynamic_entry_sizing,
            "min_dynamic_entry_quote_usdc": str(self.min_dynamic_entry_quote_usdc),
            "max_dynamic_entry_quote_usdc": str(self.max_dynamic_entry_quote_usdc),
            "autonomous_max_order_quote": str(self.autonomous_max_order_quote),
            "autonomous_max_open_orders": self.autonomous_max_open_orders,
            "autonomous_max_new_orders_per_cycle": self.autonomous_max_new_orders_per_cycle,
            "autonomous_max_cancels_per_cycle": self.autonomous_max_cancels_per_cycle,
            "autonomous_max_replaces_per_cycle": self.autonomous_max_replaces_per_cycle,
            "autonomous_require_post_only": self.autonomous_require_post_only,
            "autonomous_entry_only_first": self.autonomous_entry_only_first,
            "autonomous_allow_exits": self.autonomous_allow_exits,
            "order_store_max_records": self.order_store_max_records,
            "enable_paper_no_fill_followup_analysis": self.enable_paper_no_fill_followup_analysis,
            "paper_no_fill_followup_min_move_pct": str(self.paper_no_fill_followup_min_move_pct),
            "enable_paper_reserved_balance_checks": self.enable_paper_reserved_balance_checks,
            "enable_paper_order_budget_enforcement": self.enable_paper_order_budget_enforcement,
            "max_open_paper_orders_total": self.max_open_paper_orders_total,
            "max_open_paper_entry_orders_per_ticker": self.max_open_paper_entry_orders_per_ticker,
            "max_open_paper_exit_orders_per_ticker": self.max_open_paper_exit_orders_per_ticker,
            "enable_paper_pending_order_intents": self.enable_paper_pending_order_intents,
            "enable_paper_watchlist_intents_from_gate_watch": self.enable_paper_watchlist_intents_from_gate_watch,
            "paper_pending_intent_ttl_hours": self.paper_pending_intent_ttl_hours,
            "paper_pending_intent_max_records": self.paper_pending_intent_max_records,
            "paper_pending_intent_min_gate_confidence": self.paper_pending_intent_min_gate_confidence,
            "paper_pending_intent_mark_needs_fresh_analysis_status": self.paper_pending_intent_mark_needs_fresh_analysis_status,
            "paper_pending_intent_max_replaced_per_ticker": self.paper_pending_intent_max_replaced_per_ticker,
            "paper_pending_intent_final_retention_hours": self.paper_pending_intent_final_retention_hours,
            "paper_pending_intent_dedupe_tolerance_pct": str(self.paper_pending_intent_dedupe_tolerance_pct),
            "paper_pending_intent_enable_dedupe_refresh": self.paper_pending_intent_enable_dedupe_refresh,
            "neural_shadow_policy_enabled": self.neural_shadow_policy_enabled,
            "neural_shadow_policy_training_enabled": self.neural_shadow_policy_training_enabled,
            "neural_shadow_policy_execution_allowed": self.neural_shadow_policy_execution_allowed,
            "neural_shadow_policy_agreement_required": self.neural_shadow_policy_agreement_required,
            "neural_shadow_policy_model_path": self.neural_shadow_policy_model_path,
            "neural_shadow_policy_min_samples": self.neural_shadow_policy_min_samples,
            "neural_shadow_policy_min_confidence": str(self.neural_shadow_policy_min_confidence),
            "neural_shadow_policy_report_path": self.neural_shadow_policy_report_path,
            "allow_add_to_winners": self.allow_add_to_winners,
            "allow_averaging_down": self.allow_averaging_down,
            "max_adds_per_position": self.max_adds_per_position,
            "max_position_scale_factor": str(self.max_position_scale_factor),
            "inventory_sell_enabled": self.inventory_sell_enabled,
            "inventory_sell_mode": self.inventory_sell_mode,
            "inventory_max_extra_sell_fraction": str(self.inventory_max_extra_sell_fraction),
            "inventory_severe_risk_only": self.inventory_severe_risk_only,
            "inventory_min_residual_base": str(self.inventory_min_residual_base),
            "inventory_reduce_fraction_on_severe": str(self.inventory_reduce_fraction_on_severe),
        }
