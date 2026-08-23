from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from bot.atomic_io import atomic_write_json


STATE_PATH = Path("state/market_intelligence_context.json")
FETCH_LOG_PATH = Path("logs/market_intelligence_fetches.jsonl")
SOURCE_POLICY = "context_only_no_order_authority"
DEFAULT_TTL_MINUTES = 60
DEFILLAMA_BASE_URL = "https://api.llama.fi"
DEFILLAMA_STABLECOINS_BASE_URL = "https://stablecoins.llama.fi"
COINMETRICS_BASE_URL = "https://community-api.coinmetrics.io/v4"
SANTIMENT_GRAPHQL_URL = "https://api.santiment.net/graphql"

JsonFetcher = Callable[[str, Optional[Dict[str, str]], Optional[bytes]], Any]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_z(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return round(((new - old) / old) * 100.0, 4)


def _trend(values: List[Optional[float]], *, threshold_pct: float = 1.0) -> str:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return "unknown"
    change = _pct_change(clean[0], clean[-1])
    if change is None:
        return "unknown"
    if change > threshold_pct:
        return "rising"
    if change < -threshold_pct:
        return "falling"
    return "neutral"


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def default_json_fetcher(url: str, headers: Optional[Dict[str, str]] = None, body: Optional[bytes] = None) -> Any:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def _empty_defillama() -> Dict[str, Any]:
    return {
        "available": False,
        "stablecoin_market_cap": None,
        "stablecoin_1d_change_pct": None,
        "stablecoin_7d_change_pct": None,
        "stablecoin_peg_stress": False,
        "defi_tvl": None,
        "dex_volume_24h": None,
        "perps_volume_24h": None,
        "liquidity_regime": "unknown",
        "warnings": [],
    }


def _empty_coinmetrics() -> Dict[str, Any]:
    return {
        "available": False,
        "btc_network_activity": "unknown",
        "eth_network_activity": "unknown",
        "btc_active_addresses_change": None,
        "eth_active_addresses_change": None,
        "btc_transfer_value_change": None,
        "eth_transfer_value_change": None,
        "macro_network_regime": "unknown",
        "warnings": [],
    }


def _disabled_santiment(reason: str = "disabled_or_missing_api_key") -> Dict[str, Any]:
    return {"available": False, "reason": reason}


def _empty_santiment() -> Dict[str, Any]:
    return {
        "available": False,
        "social_volume_spike": False,
        "sentiment_extreme": False,
        "crowd_regime": "unknown",
        "btc_sentiment": None,
        "eth_sentiment": None,
        "sol_sentiment": None,
        "warnings": [],
    }


def _stablecoin_total_from_value(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key in ["peggedUSD", "usd", "totalCirculatingUSD", "totalCirculating"]:
            parsed = _to_float(value.get(key))
            if parsed is not None:
                return parsed
    return _to_float(value)


def _stablecoin_supply_from_asset(asset: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        parsed = _stablecoin_total_from_value(asset.get(key))
        if parsed is not None:
            return parsed
    chains = asset.get("chains")
    if isinstance(chains, dict):
        total = 0.0
        found = False
        for chain_value in chains.values():
            parsed = _stablecoin_total_from_value(chain_value)
            if parsed is not None:
                total += parsed
                found = True
        if found:
            return total
    return None


def _stablecoins_current_mcap(raw: Any) -> tuple[Optional[float], Optional[float], Optional[float], bool, List[str]]:
    warnings: List[str] = []
    if not isinstance(raw, dict):
        return None, None, None, False, ["stablecoins_payload_unexpected_shape"]
    assets = raw.get("peggedAssets") or raw.get("data") or raw.get("stablecoins")
    if not isinstance(assets, list):
        direct = _stablecoin_total_from_value(raw.get("totalCirculatingUSD") or raw.get("totalCirculating"))
        if direct is not None:
            return direct, None, None, False, []
        return None, None, None, False, ["stablecoins_assets_missing"]

    current_total = 0.0
    prev_day_total = 0.0
    prev_week_total = 0.0
    current_found = False
    prev_day_found = False
    prev_week_found = False
    peg_stress = False
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        current = _stablecoin_supply_from_asset(asset, ["circulating", "totalCirculatingUSD", "totalCirculating"])
        prev_day = _stablecoin_supply_from_asset(asset, ["circulatingPrevDay", "totalCirculatingUSDPrevDay"])
        prev_week = _stablecoin_supply_from_asset(asset, ["circulatingPrevWeek", "totalCirculatingUSDPrevWeek"])
        if current is not None:
            current_total += current
            current_found = True
        if prev_day is not None:
            prev_day_total += prev_day
            prev_day_found = True
        if prev_week is not None:
            prev_week_total += prev_week
            prev_week_found = True
        price = _to_float(asset.get("price") or asset.get("peg") or asset.get("pegPrice"))
        if price is not None and abs(price - 1.0) >= 0.015:
            peg_stress = True
        peg_deviation = _to_float(asset.get("pegDeviation") or asset.get("pegDeviationPct"))
        if peg_deviation is not None and abs(peg_deviation) >= 1.5:
            peg_stress = True

    if not current_found:
        warnings.append("stablecoins_current_supply_missing")
    one_day = _pct_change(prev_day_total, current_total) if current_found and prev_day_found else None
    seven_day = _pct_change(prev_week_total, current_total) if current_found and prev_week_found else None
    return (current_total if current_found else None), one_day, seven_day, peg_stress, warnings


def _latest_stablecoin_mcap(raw: Any) -> tuple[Optional[float], Optional[float], Optional[float], bool]:
    rows = raw.get("data") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    if not isinstance(rows, list):
        return None, None, None, False
    dated = []
    peg_stress = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        total = row.get("totalCirculatingUSD") or row.get("totalCirculating")
        if isinstance(total, dict):
            total = total.get("peggedUSD") or total.get("usd")
        value = _to_float(total)
        if value is None:
            continue
        date_value = _to_float(row.get("date") or row.get("timestamp"))
        dated.append((date_value or float(len(dated)), value))
    dated.sort(key=lambda item: item[0])
    latest = dated[-1][1] if dated else None
    one_day = _pct_change(dated[-2][1], dated[-1][1]) if len(dated) >= 2 else None
    seven_day = _pct_change(dated[-8][1], dated[-1][1]) if len(dated) >= 8 else None
    return latest, one_day, seven_day, peg_stress


def normalize_defillama(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty_defillama()
    warnings: List[str] = []
    try:
        stable_mcap, stable_1d, stable_7d, peg_stress, stable_warnings = _stablecoins_current_mcap(raw.get("stablecoins"))
        warnings.extend(stable_warnings)
        if stable_mcap is None:
            stable_mcap, stable_1d, stable_7d, peg_stress = _latest_stablecoin_mcap(raw.get("stablecoincharts_all"))
        if stable_mcap is None:
            stable_mcap, stable_1d, stable_7d, peg_stress = _latest_stablecoin_mcap(raw.get("stablecoinchains"))
        out["stablecoin_market_cap"] = stable_mcap
        out["stablecoin_1d_change_pct"] = stable_1d
        out["stablecoin_7d_change_pct"] = stable_7d
        out["stablecoin_peg_stress"] = peg_stress

        chains = raw.get("chains")
        if isinstance(chains, list):
            out["defi_tvl"] = sum(_to_float(row.get("tvl")) or 0.0 for row in chains if isinstance(row, dict)) or None
        historical = raw.get("historical_chain_tvl")
        if out["defi_tvl"] is None and isinstance(historical, list) and historical:
            out["defi_tvl"] = _to_float(historical[-1].get("tvl") if isinstance(historical[-1], dict) else None)

        dex = raw.get("dex_overview") if isinstance(raw.get("dex_overview"), dict) else {}
        out["dex_volume_24h"] = _to_float(dex.get("total24h") or dex.get("totalVolume24h"))
        perps = raw.get("open_interest_overview") if isinstance(raw.get("open_interest_overview"), dict) else {}
        out["perps_volume_24h"] = _to_float(perps.get("total24h") or perps.get("totalVolume24h") or perps.get("totalOpenInterest"))

        fees = raw.get("fees_overview") if isinstance(raw.get("fees_overview"), dict) else {}
        fee_24h = _to_float(fees.get("total24h") or fees.get("totalFees24h"))

        if stable_7d is not None and stable_7d < -1.0:
            out["liquidity_regime"] = "risk_off"
            warnings.append("stablecoin_market_cap_contracting_7d")
        elif stable_7d is not None and stable_7d > 1.0:
            out["liquidity_regime"] = "risk_on"
        elif out["defi_tvl"] or out["dex_volume_24h"] or fee_24h:
            out["liquidity_regime"] = "neutral"

        out["available"] = any(out.get(k) is not None for k in ["stablecoin_market_cap", "defi_tvl", "dex_volume_24h", "perps_volume_24h"])
    except Exception as exc:
        warnings.append(f"defillama_normalization_failed:{exc}")
    out["warnings"] = warnings
    return out


def fetch_defillama(fetcher: JsonFetcher = default_json_fetcher) -> tuple[Dict[str, Any], Dict[str, Any]]:
    endpoints = {
        "stablecoins": f"{DEFILLAMA_BASE_URL}/stablecoins",
        "stablecoins_legacy_host": f"{DEFILLAMA_STABLECOINS_BASE_URL}/stablecoins",
        "chains": f"{DEFILLAMA_BASE_URL}/v2/chains",
        "historical_chain_tvl": f"{DEFILLAMA_BASE_URL}/v2/historicalChainTvl",
        "dex_overview": f"{DEFILLAMA_BASE_URL}/overview/dexs",
        "open_interest_overview": f"{DEFILLAMA_BASE_URL}/overview/open-interest",
        "fees_overview": f"{DEFILLAMA_BASE_URL}/overview/fees",
        "stablecoincharts_all": f"{DEFILLAMA_BASE_URL}/stablecoincharts/all",
        "stablecoincharts_all_legacy_host": f"{DEFILLAMA_STABLECOINS_BASE_URL}/stablecoincharts/all",
        "stablecoinchains": f"{DEFILLAMA_BASE_URL}/stablecoinchains",
        "stablecoinchains_legacy_host": f"{DEFILLAMA_STABLECOINS_BASE_URL}/stablecoinchains",
    }
    raw: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for key, url in endpoints.items():
        canonical_key = key.replace("_legacy_host", "")
        if key.endswith("_legacy_host") and canonical_key in raw:
            continue
        try:
            raw[canonical_key] = fetcher(url, None, None)
        except Exception as exc:
            errors[key] = str(exc)
    normalized = normalize_defillama(raw)
    if errors:
        normalized["warnings"].extend(f"{key}_fetch_failed:{value}" for key, value in errors.items())
    return normalized, {"source": "defillama", "raw": raw, "errors": errors}


COINMETRICS_METRICS = ["AdrActCnt", "TxTfrValAdjUSD"]


def _catalog_metric_names(raw: Any, assets: Iterable[str]) -> List[str]:
    wanted_assets = {asset.lower() for asset in assets}
    rows = raw.get("data") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    if not isinstance(rows, list):
        return []
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").lower()
        if asset and asset not in wanted_assets:
            continue
        metrics = row.get("metrics")
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, str):
                    names.add(metric)
                elif isinstance(metric, dict) and metric.get("metric"):
                    names.add(str(metric.get("metric")))
        metric = row.get("metric")
        if metric:
            names.add(str(metric))
    return sorted(names)


def normalize_coinmetrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty_coinmetrics()
    warnings: List[str] = []
    rows = raw.get("asset_metrics", {}).get("data") if isinstance(raw.get("asset_metrics"), dict) else raw.get("data")
    if not isinstance(rows, list):
        out["warnings"] = ["coinmetrics_asset_metrics_missing"]
        return out
    by_asset: Dict[str, List[Dict[str, Any]]] = {"btc": [], "eth": []}
    for row in rows:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").lower()
        if asset in by_asset:
            by_asset[asset].append(row)
    for asset, values in by_asset.items():
        values.sort(key=lambda row: str(row.get("time") or ""))
        active = [_to_float(row.get("AdrActCnt")) for row in values]
        transfer = [_to_float(row.get("TxTfrValAdjUSD")) for row in values]
        active_change = _pct_change(next((v for v in active if v is not None), None), next((v for v in reversed(active) if v is not None), None))
        transfer_change = _pct_change(next((v for v in transfer if v is not None), None), next((v for v in reversed(transfer) if v is not None), None))
        activity = _trend(active, threshold_pct=2.0)
        prefix = "btc" if asset == "btc" else "eth"
        out[f"{prefix}_network_activity"] = activity
        out[f"{prefix}_active_addresses_change"] = active_change
        out[f"{prefix}_transfer_value_change"] = transfer_change
        if not values:
            warnings.append(f"{asset}_community_metrics_unavailable")
    trends = [out["btc_network_activity"], out["eth_network_activity"]]
    if "falling" in trends and trends.count("rising") == 0:
        out["macro_network_regime"] = "risk_off"
    elif "rising" in trends and trends.count("falling") == 0:
        out["macro_network_regime"] = "supportive"
    elif any(t != "unknown" for t in trends):
        out["macro_network_regime"] = "neutral"
    out["available"] = any(out.get(k) is not None for k in ["btc_active_addresses_change", "eth_active_addresses_change", "btc_transfer_value_change", "eth_transfer_value_change"])
    out["warnings"] = warnings
    return out


def fetch_coinmetrics(fetcher: JsonFetcher = default_json_fetcher) -> tuple[Dict[str, Any], Dict[str, Any]]:
    end = now_utc().date()
    start = end - timedelta(days=14)
    raw: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    catalog_endpoints = {
        "catalog_v2_asset_metrics": f"{COINMETRICS_BASE_URL}/catalog-v2/asset-metrics?assets=btc,eth",
        "catalog_asset_metrics": f"{COINMETRICS_BASE_URL}/catalog/asset-metrics?assets=btc,eth",
    }
    available_metrics: List[str] = []
    for key, url in catalog_endpoints.items():
        try:
            raw[key] = fetcher(url, None, None)
            available_metrics = [metric for metric in COINMETRICS_METRICS if metric in _catalog_metric_names(raw[key], ["btc", "eth"])]
            if available_metrics:
                break
            errors[key] = "no_requested_community_metrics_discovered"
        except Exception as exc:
            errors[key] = str(exc)
    if not available_metrics:
        normalized = normalize_coinmetrics(raw)
        normalized["warnings"].append("coinmetrics_community_metrics_not_discovered")
        normalized["warnings"].extend(f"{key}_fetch_failed:{value}" for key, value in errors.items())
        return normalized, {"source": "coinmetrics", "raw": raw, "errors": errors}

    params = urllib.parse.urlencode(
        {
            "assets": "btc,eth",
            "metrics": ",".join(available_metrics),
            "frequency": "1d",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "page_size": "10000",
        }
    )
    url = f"{COINMETRICS_BASE_URL}/timeseries/asset-metrics?{params}"
    try:
        raw["asset_metrics"] = fetcher(url, None, None)
    except Exception as exc:
        errors["asset_metrics"] = str(exc)
    normalized = normalize_coinmetrics(raw)
    if errors:
        normalized["warnings"].extend(f"{key}_fetch_failed:{value}" for key, value in errors.items())
    return normalized, {"source": "coinmetrics", "raw": raw, "errors": errors}


def _santiment_metric_query(slug: str, metric: str) -> str:
    return (
        "{ getMetric(metric: \"%s\") { timeseriesData(slug: \"%s\", from: \"utc_now-14d\", to: \"utc_now\", interval: \"1d\") { datetime value } } }"
        % (metric, slug)
    )


def normalize_santiment(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty_santiment()
    warnings: List[str] = []
    sentiments: Dict[str, Optional[float]] = {}
    social_spike = False
    sentiment_extreme = False
    for asset in ["btc", "eth", "sol"]:
        slug = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana"}[asset]
        sentiment_rows = raw.get(f"{slug}:weighted_sentiment") or raw.get(f"{slug}:sentiment")
        if isinstance(sentiment_rows, list):
            values = [_to_float(row.get("value")) for row in sentiment_rows if isinstance(row, dict)]
            latest = next((v for v in reversed(values) if v is not None), None)
            sentiments[asset] = latest
            if latest is not None and abs(latest) >= 1.5:
                sentiment_extreme = True
        social_rows = raw.get(f"{slug}:social_volume_total") or raw.get(f"{slug}:social_volume")
        if isinstance(social_rows, list):
            values = [_to_float(row.get("value")) for row in social_rows if isinstance(row, dict)]
            clean = [v for v in values if v is not None]
            if len(clean) >= 4 and clean[-1] > (sum(clean[:-1]) / len(clean[:-1])) * 2.0:
                social_spike = True
    out["btc_sentiment"] = sentiments.get("btc")
    out["eth_sentiment"] = sentiments.get("eth")
    out["sol_sentiment"] = sentiments.get("sol")
    out["social_volume_spike"] = social_spike
    out["sentiment_extreme"] = sentiment_extreme
    sentiment_values = [v for v in sentiments.values() if v is not None]
    if sentiment_values:
        avg = sum(sentiment_values) / len(sentiment_values)
        if avg >= 1.0:
            out["crowd_regime"] = "euphoria"
        elif avg <= -1.0:
            out["crowd_regime"] = "fear"
        else:
            out["crowd_regime"] = "neutral"
        out["available"] = True
    else:
        warnings.append("santiment_sentiment_metrics_unavailable")
    out["warnings"] = warnings
    return out


def fetch_santiment(fetcher: JsonFetcher = default_json_fetcher, *, enabled: bool, api_key: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not enabled or not api_key:
        return _disabled_santiment(), {"source": "santiment", "raw": {}, "errors": {"disabled": "disabled_or_missing_api_key"}}
    headers = {"Content-Type": "application/json", "Authorization": f"Apikey {api_key}"}
    raw: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for slug in ["bitcoin", "ethereum", "solana"]:
        for metric in ["social_volume_total", "weighted_sentiment", "network_growth", "dev_activity"]:
            key = f"{slug}:{metric}"
            body = json.dumps({"query": _santiment_metric_query(slug, metric)}).encode("utf-8")
            try:
                response = fetcher(SANTIMENT_GRAPHQL_URL, headers, body)
                rows = (((response or {}).get("data") or {}).get("getMetric") or {}).get("timeseriesData")
                raw[key] = rows
            except Exception as exc:
                errors[key] = str(exc)
    normalized = normalize_santiment(raw)
    if errors:
        normalized["warnings"].extend(f"{key}_fetch_failed:{value}" for key, value in errors.items())
    return normalized, {"source": "santiment", "raw": raw, "errors": errors}


def _fixture_raw() -> Dict[str, Any]:
    return {
        "defillama": {
            "stablecoins": {
                "peggedAssets": [
                    {
                        "symbol": "USDC",
                        "price": 1.0,
                        "circulating": {"peggedUSD": 58.0},
                        "circulatingPrevDay": {"peggedUSD": 57.0},
                        "circulatingPrevWeek": {"peggedUSD": 54.0},
                    },
                    {
                        "symbol": "USDT",
                        "price": 1.0,
                        "circulating": {"peggedUSD": 50.0},
                        "circulatingPrevDay": {"peggedUSD": 49.0},
                        "circulatingPrevWeek": {"peggedUSD": 46.0},
                    },
                ]
            },
            "stablecoincharts_all": {
                "data": [
                    {"date": 1, "totalCirculatingUSD": {"peggedUSD": 100.0}},
                    {"date": 2, "totalCirculatingUSD": {"peggedUSD": 101.0}},
                    {"date": 3, "totalCirculatingUSD": {"peggedUSD": 102.5}},
                    {"date": 4, "totalCirculatingUSD": {"peggedUSD": 103.0}},
                    {"date": 5, "totalCirculatingUSD": {"peggedUSD": 104.0}},
                    {"date": 6, "totalCirculatingUSD": {"peggedUSD": 105.0}},
                    {"date": 7, "totalCirculatingUSD": {"peggedUSD": 106.0}},
                    {"date": 8, "totalCirculatingUSD": {"peggedUSD": 108.0}},
                ]
            },
            "chains": [{"name": "Ethereum", "tvl": 70.0}, {"name": "Solana", "tvl": 10.0}],
            "dex_overview": {"total24h": 5.0},
            "open_interest_overview": {"totalOpenInterest": 3.0},
            "fees_overview": {"total24h": 1.0},
        },
        "coinmetrics": {
            "asset_metrics": {
                "data": [
                    {"asset": "btc", "time": "2026-06-01", "AdrActCnt": "100", "TxTfrValAdjUSD": "1000"},
                    {"asset": "btc", "time": "2026-06-14", "AdrActCnt": "110", "TxTfrValAdjUSD": "1200"},
                    {"asset": "eth", "time": "2026-06-01", "AdrActCnt": "200", "TxTfrValAdjUSD": "900"},
                    {"asset": "eth", "time": "2026-06-14", "AdrActCnt": "210", "TxTfrValAdjUSD": "990"},
                ]
            }
        },
        "santiment": {
            "bitcoin:weighted_sentiment": [{"value": "0.2"}, {"value": "0.4"}],
            "ethereum:weighted_sentiment": [{"value": "0.1"}, {"value": "0.3"}],
            "solana:weighted_sentiment": [{"value": "0.0"}, {"value": "0.2"}],
            "bitcoin:social_volume_total": [{"value": "10"}, {"value": "11"}, {"value": "10"}, {"value": "12"}],
            "ethereum:social_volume_total": [{"value": "9"}, {"value": "10"}, {"value": "9"}, {"value": "10"}],
            "solana:social_volume_total": [{"value": "8"}, {"value": "8"}, {"value": "9"}, {"value": "9"}],
        },
    }


def build_fixture_context(*, include_santiment: bool = False) -> Dict[str, Any]:
    raw = _fixture_raw()
    return {
        "defillama": normalize_defillama(raw["defillama"]),
        "coinmetrics": normalize_coinmetrics(raw["coinmetrics"]),
        "santiment": normalize_santiment(raw["santiment"]) if include_santiment else _disabled_santiment(),
        "_raw_fetches": [
            {"source": "defillama", "raw": raw["defillama"], "errors": {}},
            {"source": "coinmetrics", "raw": raw["coinmetrics"], "errors": {}},
            {"source": "santiment", "raw": raw["santiment"] if include_santiment else {}, "errors": {}},
        ],
    }


def summarize_context(defillama: Dict[str, Any], coinmetrics: Dict[str, Any], santiment: Dict[str, Any]) -> Dict[str, Any]:
    risk_warnings: List[str] = []
    positive_context: List[str] = []
    liquidity = str(defillama.get("liquidity_regime") or "unknown")
    network = str(coinmetrics.get("macro_network_regime") or "unknown")
    crowd = str(santiment.get("crowd_regime") or "unknown") if santiment.get("available") else "unknown"
    if liquidity == "risk_off":
        risk_warnings.append("defillama_liquidity_regime_risk_off")
    elif liquidity == "risk_on":
        positive_context.append("defillama_liquidity_regime_risk_on")
    if network == "risk_off":
        risk_warnings.append("coinmetrics_macro_network_regime_risk_off")
    elif network == "supportive":
        positive_context.append("coinmetrics_macro_network_regime_supportive")
    if crowd in {"euphoria", "fear"}:
        risk_warnings.append(f"santiment_crowd_regime_{crowd}")
    return {
        "liquidity_regime": liquidity,
        "network_regime": network,
        "crowd_regime": crowd,
        "risk_warnings": risk_warnings,
        "positive_context": positive_context,
    }


def assemble_context(
    *,
    defillama: Dict[str, Any],
    coinmetrics: Dict[str, Any],
    santiment: Dict[str, Any],
    generated_at: Optional[datetime] = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> Dict[str, Any]:
    generated = generated_at or now_utc()
    expires = generated + timedelta(minutes=ttl_minutes)
    summary = summarize_context(defillama, coinmetrics, santiment)
    available = bool(defillama.get("available") or coinmetrics.get("available") or santiment.get("available"))
    return {
        "generated_at": isoformat_z(generated),
        "ttl_minutes": ttl_minutes,
        "expires_at": isoformat_z(expires),
        "available": available,
        "stale": False,
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "defillama": defillama,
        "coinmetrics": coinmetrics,
        "santiment": santiment,
        "summary": summary,
    }


def market_intelligence_source_status(context: Dict[str, Any]) -> Dict[str, str]:
    defillama = context.get("defillama") if isinstance(context.get("defillama"), dict) else {}
    coinmetrics = context.get("coinmetrics") if isinstance(context.get("coinmetrics"), dict) else {}
    santiment = context.get("santiment") if isinstance(context.get("santiment"), dict) else {}

    def _available_or_partial(source: Dict[str, Any], value_keys: Iterable[str]) -> str:
        if not source:
            return "unavailable"
        if not source.get("available"):
            return "unavailable"
        return "available" if all(source.get(key) is not None for key in value_keys) else "partial"

    santiment_status = "available" if santiment.get("available") else "unavailable"
    if santiment.get("reason") in {"disabled_or_missing_api_key", "source_not_selected"}:
        santiment_status = "disabled"
    return {
        "defillama": _available_or_partial(defillama, ["stablecoin_market_cap", "defi_tvl", "dex_volume_24h", "perps_volume_24h"]),
        "coinmetrics": _available_or_partial(
            coinmetrics,
            ["btc_active_addresses_change", "eth_active_addresses_change", "btc_transfer_value_change", "eth_transfer_value_change"],
        ),
        "santiment": santiment_status,
    }


def market_intelligence_warnings(context: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    for source_name in ["defillama", "coinmetrics", "santiment"]:
        source = context.get(source_name)
        if isinstance(source, dict):
            for warning in source.get("warnings") or []:
                warnings.append(f"{source_name}:{warning}")
            reason = source.get("reason")
            if reason:
                warnings.append(f"{source_name}:{reason}")
    return warnings


def context_with_status(context: Dict[str, Any]) -> Dict[str, Any]:
    enriched = deepcopy(context) if isinstance(context, dict) else {}
    enriched["sources"] = market_intelligence_source_status(enriched)
    enriched["warnings"] = market_intelligence_warnings(enriched)
    return enriched


def is_context_stale(context: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    expires = parse_iso_z(context.get("expires_at"))
    if expires is None:
        return True
    return (now or now_utc()) >= expires


def load_market_intelligence_context(path: Path = STATE_PATH, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data["stale"] = is_context_stale(data, now=now)
        data["can_authorize_execution"] = False
        data["can_block_execution"] = False
        data["can_mutate_parameters"] = False
        return data
    return {}


def feature_pack_market_intelligence_context(root: Path = Path("."), *, now: Optional[datetime] = None) -> Dict[str, Any]:
    context = load_market_intelligence_context(root / STATE_PATH, now=now)
    if not context:
        return {
            "available": False,
            "stale": True,
            "summary": {
                "liquidity_regime": "unknown",
                "network_regime": "unknown",
                "crowd_regime": "unknown",
                "risk_warnings": [],
                "positive_context": [],
            },
            "can_authorize_execution": False,
            "can_block_execution": False,
            "can_mutate_parameters": False,
        }
    return {
        "available": bool(context.get("available")),
        "stale": bool(context.get("stale")),
        "summary": deepcopy(context.get("summary") or {}),
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
    }


def inject_market_intelligence_feature_pack(feature_pack: Dict[str, Any], root: Path = Path(".")) -> Dict[str, Any]:
    pack = feature_pack if isinstance(feature_pack, dict) else {}
    decision_context = pack.setdefault("decision_context", {})
    external = decision_context.setdefault("external_context", {})
    external["market_intelligence"] = feature_pack_market_intelligence_context(root)
    return pack


def build_market_intelligence_context(
    *,
    root: Path = Path("."),
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    sources: Optional[Iterable[str]] = None,
    no_network: bool = False,
    fetcher: JsonFetcher = default_json_fetcher,
    env: Optional[Dict[str, str]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    root = Path(root)
    env_map = env or os.environ
    selected = {s.strip().lower() for s in (sources or ["defillama", "coinmetrics", "santiment"]) if s.strip()}
    state_path = root / STATE_PATH
    if use_cache and state_path.exists() and not no_network:
        cached = load_market_intelligence_context(state_path)
        if cached and not cached.get("stale"):
            return cached

    raw_fetches: List[Dict[str, Any]] = []
    if no_network:
        fixture = build_fixture_context(include_santiment="santiment" in selected and bool(env_map.get("SANTIMENT_API_KEY")))
        defillama = fixture["defillama"] if "defillama" in selected else _empty_defillama()
        coinmetrics = fixture["coinmetrics"] if "coinmetrics" in selected else _empty_coinmetrics()
        santiment = fixture["santiment"] if "santiment" in selected else _disabled_santiment("source_not_selected")
        raw_fetches = fixture["_raw_fetches"]
    else:
        if "defillama" in selected and env_map.get("ENABLE_DEFILLAMA_CONTEXT", "true").lower() != "false":
            defillama, raw = fetch_defillama(fetcher)
            raw_fetches.append(raw)
        else:
            defillama = _empty_defillama()
        if "coinmetrics" in selected and env_map.get("ENABLE_COINMETRICS_CONTEXT", "true").lower() != "false":
            coinmetrics, raw = fetch_coinmetrics(fetcher)
            raw_fetches.append(raw)
        else:
            coinmetrics = _empty_coinmetrics()
        santiment_enabled = env_map.get("ENABLE_SANTIMENT_CONTEXT", "false").lower() == "true"
        santiment_key = env_map.get("SANTIMENT_API_KEY", "")
        if "santiment" in selected:
            santiment, raw = fetch_santiment(fetcher, enabled=santiment_enabled, api_key=santiment_key)
            raw_fetches.append(raw)
        else:
            santiment = _disabled_santiment("source_not_selected")

    context = assemble_context(defillama=defillama, coinmetrics=coinmetrics, santiment=santiment, ttl_minutes=ttl_minutes)
    atomic_write_json(state_path, context)
    for raw in raw_fetches:
        entry = {"logged_at": isoformat_z(now_utc()), "source_policy": SOURCE_POLICY, **raw}
        _append_jsonl(root / FETCH_LOG_PATH, entry)
    return context


def render_context_status(context: Dict[str, Any]) -> str:
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    lines = [
        "Market intelligence context",
        f"available: {context.get('available')}",
        f"stale: {context.get('stale')}",
        f"sources: {market_intelligence_source_status(context)}",
        f"warnings: {market_intelligence_warnings(context)}",
        f"generated_at: {context.get('generated_at')}",
        f"expires_at: {context.get('expires_at')}",
        f"defillama_available: {(context.get('defillama') or {}).get('available') if isinstance(context.get('defillama'), dict) else False}",
        f"coinmetrics_available: {(context.get('coinmetrics') or {}).get('available') if isinstance(context.get('coinmetrics'), dict) else False}",
        f"santiment_available: {(context.get('santiment') or {}).get('available') if isinstance(context.get('santiment'), dict) else False}",
        f"liquidity_regime: {summary.get('liquidity_regime')}",
        f"network_regime: {summary.get('network_regime')}",
        f"crowd_regime: {summary.get('crowd_regime')}",
        f"risk_warnings: {summary.get('risk_warnings') or []}",
        f"positive_context: {summary.get('positive_context') or []}",
        f"source_policy: {context.get('source_policy')}",
        "can_authorize_execution: False",
        "can_block_execution: False",
        "can_mutate_parameters: False",
    ]
    return "\n".join(lines)


__all__ = [
    "STATE_PATH",
    "FETCH_LOG_PATH",
    "SOURCE_POLICY",
    "assemble_context",
    "build_fixture_context",
    "build_market_intelligence_context",
    "feature_pack_market_intelligence_context",
    "context_with_status",
    "inject_market_intelligence_feature_pack",
    "is_context_stale",
    "load_market_intelligence_context",
    "market_intelligence_source_status",
    "market_intelligence_warnings",
    "normalize_coinmetrics",
    "normalize_defillama",
    "normalize_santiment",
    "render_context_status",
]
