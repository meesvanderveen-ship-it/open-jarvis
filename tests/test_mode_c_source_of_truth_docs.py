from __future__ import annotations

from pathlib import Path

from bot.config import MODE_C_MARKET_ORDER_ACK_VALUE


def test_mode_c_docs_source_of_truth_matches_readiness() -> None:
    text = Path("docs/MODE_C_MARKET_ORDER_SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
    assert "Full workflow baseline keeps market order flags disabled" in text
    assert MODE_C_MARKET_ORDER_ACK_VALUE in text
    assert "replication is fully disabled" in text
    assert "controlled close/stop routing" in text
    assert "does not authorize arbitrary speculative market entries" in text

