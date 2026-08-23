from __future__ import annotations

import json

from bot.exchange_rejection_memory import summarize_recent_exchange_rejections


def test_invalid_price_precision_from_logs_is_summarized(tmp_path):
    log = tmp_path / "phase_c_live_submit.jsonl"
    log.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-17T00:00:00+00:00",
                "ticker": "BTC-USDC",
                "live_submission_attempted": True,
                "submit_result": {
                    "reject_reason": "INVALID_PRICE_PRECISION",
                    "reject_message": "Too many decimals in price",
                    "payload": {"size_quote_normalized": "50.00", "limit_price": "65000.001"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = summarize_recent_exchange_rejections(log, ticker="BTC-USDC", hours=24 * 365)
    assert report["recent_rejections"]["INVALID_PRICE_PRECISION"] == 1
    assert report["events"][0]["reject_reason"] == "INVALID_PRICE_PRECISION"


def test_invalid_size_precision_from_logs_is_summarized(tmp_path):
    log = tmp_path / "phase_c_live_submit.jsonl"
    log.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-17T00:00:00+00:00",
                "ticker": "SOL-USDC",
                "live_submission_attempted": True,
                "coinbase_response": {
                    "error_response": {
                        "error": "INVALID_SIZE_PRECISION",
                        "message": "Too many decimals in size",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = summarize_recent_exchange_rejections(log, ticker="SOL-USDC", hours=24 * 365)
    assert report["recent_rejections"]["INVALID_SIZE_PRECISION"] == 1
    assert report["reject_reasons_by_ticker"]["SOL-USDC"]["INVALID_SIZE_PRECISION"] == 1
