from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot.market_intelligence_context import (
    FETCH_LOG_PATH,
    STATE_PATH,
    assemble_context,
    build_fixture_context,
    build_market_intelligence_context,
    fetch_coinmetrics,
    fetch_defillama,
    feature_pack_market_intelligence_context,
    inject_market_intelligence_feature_pack,
    is_context_stale,
    normalize_coinmetrics,
    normalize_defillama,
    normalize_santiment,
)


def test_defillama_fixture_normalizes_stablecoin_and_tvl_context() -> None:
    fixture = build_fixture_context()
    data = fixture["defillama"]
    assert data["available"] is True
    assert data["stablecoin_market_cap"] == 108.0
    assert data["defi_tvl"] == 80.0
    assert data["dex_volume_24h"] == 5.0
    assert data["liquidity_regime"] == "risk_on"


def test_defillama_stablecoins_success_fills_market_cap() -> None:
    data = normalize_defillama(
        {
            "stablecoins": {
                "peggedAssets": [
                    {
                        "symbol": "USDC",
                        "price": 1.0,
                        "circulating": {"peggedUSD": 60.0},
                        "circulatingPrevDay": {"peggedUSD": 59.0},
                        "circulatingPrevWeek": {"peggedUSD": 55.0},
                    },
                    {
                        "symbol": "USDT",
                        "price": 1.0,
                        "circulating": {"peggedUSD": 40.0},
                        "circulatingPrevDay": {"peggedUSD": 40.0},
                        "circulatingPrevWeek": {"peggedUSD": 39.0},
                    },
                ]
            }
        }
    )
    assert data["available"] is True
    assert data["stablecoin_market_cap"] == 100.0
    assert data["stablecoin_peg_stress"] is False


def test_defillama_stablecoincharts_404_degrades_with_other_sources_available() -> None:
    def fetcher(url, headers=None, body=None):
        if url.endswith("/stablecoins"):
            return {"bad": "shape"}
        if url.endswith("/stablecoincharts/all"):
            raise RuntimeError("HTTP Error 404: Not Found")
        if url.endswith("/stablecoinchains"):
            return []
        if url.endswith("/v2/chains"):
            return [{"name": "Ethereum", "tvl": 70.0}]
        if url.endswith("/overview/dexs"):
            return {"total24h": 5.0}
        if url.endswith("/overview/open-interest"):
            return {"totalOpenInterest": 3.0}
        if url.endswith("/overview/fees"):
            return {"total24h": 1.0}
        return []

    data, raw = fetch_defillama(fetcher)
    assert data["available"] is True
    assert data["stablecoin_market_cap"] is None
    assert data["defi_tvl"] == 70.0
    assert data["dex_volume_24h"] == 5.0
    assert data["perps_volume_24h"] == 3.0
    assert raw["errors"]["stablecoincharts_all"] == "HTTP Error 404: Not Found"
    assert any("stablecoincharts_all_fetch_failed:HTTP Error 404: Not Found" == warning for warning in data["warnings"])


def test_defillama_stablecoins_primary_404_uses_legacy_host_fallback() -> None:
    def fetcher(url, headers=None, body=None):
        if url == "https://api.llama.fi/stablecoins":
            raise RuntimeError("HTTP Error 404: Not Found")
        if url == "https://stablecoins.llama.fi/stablecoins":
            return {"peggedAssets": [{"symbol": "USDC", "price": 1.0, "circulating": {"peggedUSD": 123.0}}]}
        if url.endswith("/stablecoincharts/all") or url.endswith("/stablecoinchains"):
            raise RuntimeError("HTTP Error 404: Not Found")
        return []

    data, raw = fetch_defillama(fetcher)
    assert data["available"] is True
    assert data["stablecoin_market_cap"] == 123.0
    assert raw["errors"]["stablecoins"] == "HTTP Error 404: Not Found"


def test_coinmetrics_fixture_normalizes_btc_eth_network_context() -> None:
    fixture = build_fixture_context()
    data = fixture["coinmetrics"]
    assert data["available"] is True
    assert data["btc_network_activity"] == "rising"
    assert data["eth_network_activity"] == "rising"
    assert data["macro_network_regime"] == "supportive"
    assert data["btc_active_addresses_change"] == 10.0


def test_coinmetrics_403_degrades_to_unavailable_unknown() -> None:
    def fetcher(url, headers=None, body=None):
        if "/catalog-v2/asset-metrics" in url:
            return {"data": [{"asset": "btc", "metrics": ["AdrActCnt"]}, {"asset": "eth", "metrics": ["AdrActCnt"]}]}
        raise RuntimeError("HTTP Error 403: Forbidden")

    data, raw = fetch_coinmetrics(fetcher)
    assert data["available"] is False
    assert data["macro_network_regime"] == "unknown"
    assert raw["errors"]["asset_metrics"] == "HTTP Error 403: Forbidden"
    assert any("asset_metrics_fetch_failed:HTTP Error 403: Forbidden" == warning for warning in data["warnings"])


def test_coinmetrics_catalog_discovery_limits_requested_metrics() -> None:
    requested_urls = []

    def fetcher(url, headers=None, body=None):
        requested_urls.append(url)
        if "/catalog-v2/asset-metrics" in url:
            return {"data": [{"asset": "btc", "metrics": ["AdrActCnt"]}, {"asset": "eth", "metrics": ["AdrActCnt"]}]}
        assert "metrics=AdrActCnt" in url
        assert "TxTfrValAdjUSD" not in url
        return {
            "data": [
                {"asset": "btc", "time": "2026-06-01", "AdrActCnt": "100"},
                {"asset": "btc", "time": "2026-06-14", "AdrActCnt": "110"},
                {"asset": "eth", "time": "2026-06-01", "AdrActCnt": "200"},
                {"asset": "eth", "time": "2026-06-14", "AdrActCnt": "210"},
            ]
        }

    data, _raw = fetch_coinmetrics(fetcher)
    assert data["available"] is True
    assert data["btc_active_addresses_change"] == 10.0
    assert any("/catalog-v2/asset-metrics" in url for url in requested_urls)


def test_santiment_disabled_without_key_is_unavailable(tmp_path: Path) -> None:
    context = build_market_intelligence_context(root=tmp_path, no_network=True, env={}, sources=["santiment"], use_cache=False)
    assert context["santiment"] == {"available": False, "reason": "disabled_or_missing_api_key"}


def test_santiment_fixture_with_key_normalizes_social_and_sentiment() -> None:
    fixture = build_fixture_context(include_santiment=True)
    data = fixture["santiment"]
    assert data["available"] is True
    assert data["crowd_regime"] == "neutral"
    assert data["btc_sentiment"] == 0.4
    assert data["social_volume_spike"] is False


def test_normalizers_fail_gracefully_on_bad_payloads() -> None:
    assert normalize_defillama({"stablecoincharts_all": {"bad": "shape"}})["available"] is False
    assert normalize_coinmetrics({"asset_metrics": {"data": []}})["available"] is False
    santiment = normalize_santiment({"bitcoin:weighted_sentiment": "bad"})
    assert santiment["available"] is False
    assert santiment["warnings"]


def test_network_failure_warns_and_does_not_crash(tmp_path: Path) -> None:
    def failing_fetcher(url, headers=None, body=None):
        raise RuntimeError("network down")

    context = build_market_intelligence_context(root=tmp_path, fetcher=failing_fetcher, sources=["defillama", "coinmetrics"], use_cache=False)
    assert context["available"] is False
    assert context["defillama"]["warnings"]
    assert context["coinmetrics"]["warnings"]


def test_context_writes_state_atomically_and_raw_fetch_log(tmp_path: Path) -> None:
    context = build_market_intelligence_context(root=tmp_path, no_network=True, use_cache=False)
    state_path = tmp_path / STATE_PATH
    log_path = tmp_path / FETCH_LOG_PATH
    assert state_path.exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["source_policy"] == "context_only_no_order_authority"
    assert log_path.exists()
    assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) >= 2
    assert context["can_authorize_execution"] is False


def test_expired_context_is_stale() -> None:
    generated = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
    context = assemble_context(
        defillama={"available": False},
        coinmetrics={"available": False},
        santiment={"available": False},
        generated_at=generated,
        ttl_minutes=1,
    )
    assert is_context_stale(context, now=datetime(2026, 6, 14, 10, 2, tzinfo=timezone.utc)) is True


def test_feature_pack_gets_external_market_intelligence(tmp_path: Path) -> None:
    build_market_intelligence_context(root=tmp_path, no_network=True, use_cache=False)
    summary = feature_pack_market_intelligence_context(root=tmp_path)
    assert summary["available"] is True
    pack = inject_market_intelligence_feature_pack({"decision_context": {}}, root=tmp_path)
    external = pack["decision_context"]["external_context"]["market_intelligence"]
    assert external["summary"]["liquidity_regime"] == "risk_on"
    assert external["can_authorize_execution"] is False
    assert external["can_block_execution"] is False
    assert external["can_mutate_parameters"] is False


def test_context_safety_flags_are_always_false(tmp_path: Path) -> None:
    context = build_market_intelligence_context(root=tmp_path, no_network=True, use_cache=False)
    assert context["can_authorize_execution"] is False
    assert context["can_block_execution"] is False
    assert context["can_mutate_parameters"] is False


def test_no_coinbase_or_order_state_mutation(tmp_path: Path) -> None:
    build_market_intelligence_context(root=tmp_path, no_network=True, use_cache=False)
    assert not (tmp_path / "state/open_orders.json").exists()
    assert not (tmp_path / "state/positions.json").exists()


def test_no_env_mutation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_SANTIMENT_CONTEXT", "false")
    before = dict(__import__("os").environ)
    build_market_intelligence_context(root=tmp_path, no_network=True, use_cache=False)
    after = dict(__import__("os").environ)
    assert after == before
