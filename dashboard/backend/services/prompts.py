"""Static inventory of LLM prompt templates from bot/prompts.py.

Parsed with `ast` directly from source text — we never `import bot.prompts`
(no need to pull in the bot's runtime dependencies just to read template
text), and never execute anything. These are prompt *templates* checked
into the repo; no live-filled prompts (with real market data) are ever
served by this endpoint.
"""

from __future__ import annotations

import ast

from dashboard.backend import cache, config

_PROMPTS_FILE = config.PROJECT_ROOT / "bot" / "prompts.py"

_PURPOSE_BY_NAME = {
    "GPT_NANO_GATE_PROMPT": "Fast entry gate filter (skip/watch/analyze/priority_analyze)",
    "GPT_NANO_POSITION_WATCH_PROMPT": "Heartbeat position watchdog",
    "DEEPSEEK_PREPROCESS_PROMPT": "Optional market preprocessor (regime/trend/breakout/meanrev hints)",
    "REGIME_PROMPT": "Market regime classifier",
    "TREND_PROMPT": "Trend-continuation analyst",
    "BREAKOUT_PROMPT": "Breakout/compression analyst",
    "MEANREV_PROMPT": "Mean-reversion analyst",
    "BULL_PROMPT": "Bullish case presenter",
    "BEAR_PROMPT": "Bearish/no-trade case presenter",
    "SYNTH_PROMPT": "Strategy synthesizer",
    "TRADE_PLANNER_PROMPT": "Concrete trade plan builder",
    "CLAUDE_JUDGE_PROMPT": "Final trade decision engine",
}


def _extract_prompts() -> list[dict]:
    if not _PROMPTS_FILE.is_file():
        return []
    source = _PROMPTS_FILE.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)

    prompts = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("PROMPT"):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        text = node.value.value
        prompts.append(
            {
                "name": target.id,
                "purpose": _PURPOSE_BY_NAME.get(target.id, ""),
                "length": len(text),
                "text": text.strip(),
            }
        )
    return prompts


def get_prompts() -> dict:
    prompts = cache.get_or_compute("prompts", _extract_prompts, ttl_seconds=300)
    return {"prompts": prompts}
