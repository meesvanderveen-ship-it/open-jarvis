from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List

import pandas as pd

from bot.coinbase_client import CoinbaseClient
from bot.indicators import ema, rsi, atr, adx, bollinger_bands, donchian, slope
from bot.news_sentiment import NewsSentimentService


GRANULARITY_MAP = {
    "15M": "FIFTEEN_MINUTE",
    "1H": "ONE_HOUR",
    "4H": "FOUR_HOUR",
    "1D": "ONE_DAY",
}


class MarketDataService:
    def __init__(self, client: CoinbaseClient):
        self.client = client
        self.news = NewsSentimentService()

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        ticker = ticker.upper().strip()
        if not ticker or "-" not in ticker:
            raise ValueError("ticker moet formaat BASE-QUOTE hebben, bv. BTC-USDC")
        return ticker

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        tf = timeframe.strip().upper()
        aliases = {
            "15M": "15M", "15MIN": "15M", "15MINUTE": "15M", "15MINUTES": "15M",
            "1H": "1H", "1HR": "1H", "1HOUR": "1H", "1HOURS": "1H",
            "4H": "4H", "4HR": "4H", "4HOUR": "4H", "4HOURS": "4H",
            "1D": "1D", "D": "1D", "1DAY": "1D", "1DAYS": "1D", "DAY": "1D",
        }
        if tf not in aliases:
            raise ValueError(f"Onbekend timeframe: {timeframe}")
        return aliases[tf]

    @staticmethod
    def _lookback_delta(timeframe: str, candles_needed: int) -> timedelta:
        if timeframe == "15M":
            return timedelta(minutes=15 * candles_needed)
        if timeframe == "1H":
            return timedelta(hours=1 * candles_needed)
        if timeframe == "4H":
            return timedelta(hours=4 * candles_needed)
        if timeframe == "1D":
            return timedelta(days=1 * candles_needed)
        raise ValueError(f"Onbekend timeframe: {timeframe}")

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "15M": 15 * 60,
            "1H": 60 * 60,
            "4H": 4 * 60 * 60,
            "1D": 24 * 60 * 60,
        }
        return mapping[timeframe]

    def _drop_open_candle(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        if df.empty or "start" not in df.columns:
            return df

        interval = self._timeframe_to_seconds(timeframe)
        if interval <= 0:
            return df

        try:
            last_start = int(df.iloc[-1]["start"])
        except Exception:
            return df

        now_ts = int(self._now_utc().timestamp())
        if (last_start + interval) > now_ts and len(df) > 1:
            return df.iloc[:-1].reset_index(drop=True)

        return df

    @staticmethod
    def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
        if denominator == 0:
            return default
        return numerator / denominator

    @staticmethod
    def _last(df: pd.DataFrame, column: str, default: float = 0.0) -> float:
        if column not in df.columns or df.empty:
            return default
        val = df.iloc[-1][column]
        try:
            if pd.isna(val):
                return default
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _to_float_list(series: pd.Series, limit: int, digits: int = 6) -> List[float]:
        vals = []
        for x in series.tail(limit).tolist():
            try:
                vals.append(round(float(x), digits))
            except Exception:
                vals.append(0.0)
        return vals

    @staticmethod
    def _to_int_list(series: pd.Series, limit: int) -> List[int]:
        vals = []
        for x in series.tail(limit).tolist():
            try:
                vals.append(int(x))
            except Exception:
                vals.append(0)
        return vals

    @staticmethod
    def _pct_change(current: float, previous: float) -> float:
        if previous == 0:
            return 0.0
        return (current - previous) / previous

    def _build_raw_slice(self, df: pd.DataFrame, limit: int = 20) -> Dict[str, Any]:
        closes = self._to_float_list(df["close"], limit)
        highs = self._to_float_list(df["high"], limit)
        lows = self._to_float_list(df["low"], limit)
        opens = self._to_float_list(df["open"], limit)
        volumes = self._to_float_list(df["volume"], limit)
        starts = self._to_int_list(df["start"], limit)

        returns: List[float] = []
        for i in range(1, len(closes)):
            returns.append(round(self._pct_change(closes[i], closes[i - 1]), 6))

        candle_colors = ["green" if c >= o else "red" for o, c in zip(opens, closes)]

        return {
            "count": len(closes),
            "starts": starts,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": volumes,
            "returns": returns,
            "candle_colors": candle_colors,
            "latest_close": closes[-1] if closes else 0.0,
            "latest_volume": volumes[-1] if volumes else 0.0,
            "highest_in_slice": max(highs) if highs else 0.0,
            "lowest_in_slice": min(lows) if lows else 0.0,
        }

    def _build_microstructure(self, df: pd.DataFrame, limit: int = 10) -> Dict[str, Any]:
        closes = self._to_float_list(df["close"], limit)
        highs = self._to_float_list(df["high"], limit)
        lows = self._to_float_list(df["low"], limit)
        volumes = self._to_float_list(df["volume"], limit)

        up_closes = 0
        down_closes = 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                up_closes += 1
            elif closes[i] < closes[i - 1]:
                down_closes += 1

        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        latest_volume = volumes[-1] if volumes else 0.0

        return {
            "up_closes": up_closes,
            "down_closes": down_closes,
            "net_close_direction": "up" if up_closes > down_closes else "down" if down_closes > up_closes else "flat",
            "recent_high": max(highs) if highs else 0.0,
            "recent_low": min(lows) if lows else 0.0,
            "range_pct": self._safe_div(
                (max(highs) - min(lows)) if highs and lows else 0.0,
                closes[-1] if closes else 1.0,
                0.0,
            ),
            "avg_volume": round(avg_volume, 6),
            "latest_volume": latest_volume,
            "volume_vs_avg": round(self._safe_div(latest_volume, avg_volume, 0.0), 6) if avg_volume else 0.0,
        }

    def _fetch_candles_df(self, ticker: str, timeframe: str, candles_needed: int = 240) -> pd.DataFrame:
        ticker = self._normalize_ticker(ticker)
        tf = self._normalize_timeframe(timeframe)

        granularity = GRANULARITY_MAP[tf]
        now = self._now_utc()
        lookback = self._lookback_delta(tf, candles_needed + 5)
        start_dt = now - lookback

        start = str(int(start_dt.timestamp()))
        end = str(int(now.timestamp()))

        data = self.client.get_public_candles(
            product_id=ticker,
            granularity=granularity,
            start=start,
            end=end,
            limit=min(candles_needed + 10, 350),
        )

        candles = data.get("candles", [])
        if not candles:
            raise RuntimeError(f"Geen candles ontvangen voor {ticker} {timeframe}")

        rows: List[Dict[str, Any]] = []
        for c in candles:
            try:
                rows.append({
                    "start": int(c["start"]),
                    "low": float(c["low"]),
                    "high": float(c["high"]),
                    "open": float(c["open"]),
                    "close": float(c["close"]),
                    "volume": float(c["volume"]),
                })
            except Exception:
                continue

        if not rows:
            raise RuntimeError(f"Candles voor {ticker} {timeframe} konden niet geparsed worden")

        df = pd.DataFrame(rows).sort_values("start").reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["start"], unit="s", utc=True)

        df = self._drop_open_candle(df, tf)

        if len(df) < 60:
            raise RuntimeError(f"Te weinig gesloten candles voor {ticker} {timeframe}")

        return df.tail(candles_needed).reset_index(drop=True)

    def _apply_common_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_20"] = ema(df["close"], 20)
        df["ema_50"] = ema(df["close"], 50)
        df["rsi_14"] = rsi(df["close"], 14)
        df["atr_14"] = atr(df, 14)
        df["adx_14"] = adx(df, 14)

        bb_mid, bb_upper, bb_lower, bb_width_pct = bollinger_bands(df["close"], 20, 2.0)
        df["bb_mid"] = bb_mid
        df["bb_upper"] = bb_upper
        df["bb_lower"] = bb_lower
        df["bb_width_pct"] = bb_width_pct

        d20h, d20l = donchian(df, 20)
        d55h, d55l = donchian(df, 55)
        df["donchian_20_high"] = d20h
        df["donchian_20_low"] = d20l
        df["donchian_55_high"] = d55h
        df["donchian_55_low"] = d55l
        return df

    def _enrich_timeframes(self, df_15m, df_1h, df_4h, df_1d):
        df_15m = self._apply_common_indicators(df_15m)
        df_1h = self._apply_common_indicators(df_1h)
        df_4h = self._apply_common_indicators(df_4h)
        df_1d = self._apply_common_indicators(df_1d)
        df_4h["ema_200"] = ema(df_4h["close"], 200)
        df_1d["ema_200"] = ema(df_1d["close"], 200)
        return df_15m, df_1h, df_4h, df_1d

    def _build_structure(self, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> Dict[str, Any]:
        if len(df_1h) < 3:
            higher_highs_1h = higher_lows_1h = lower_highs_1h = lower_lows_1h = False
        else:
            higher_highs_1h = bool(df_1h["high"].iloc[-1] > df_1h["high"].iloc[-2] > df_1h["high"].iloc[-3])
            higher_lows_1h = bool(df_1h["low"].iloc[-1] > df_1h["low"].iloc[-2] > df_1h["low"].iloc[-3])
            lower_highs_1h = bool(df_1h["high"].iloc[-1] < df_1h["high"].iloc[-2] < df_1h["high"].iloc[-3])
            lower_lows_1h = bool(df_1h["low"].iloc[-1] < df_1h["low"].iloc[-2] < df_1h["low"].iloc[-3])

        last_1h_adx = self._last(df_1h, "adx_14")
        last_1h_bb_width = self._last(df_1h, "bb_width_pct")
        last_4h_adx = self._last(df_4h, "adx_14")

        nearest_support = float(df_1h["low"].tail(20).min()) if not df_1h.empty else 0.0
        nearest_resistance = float(df_1h["high"].tail(20).max()) if not df_1h.empty else 0.0
        swing_low_1h = float(df_1h["low"].tail(5).min()) if not df_1h.empty else 0.0
        swing_high_1h = float(df_1h["high"].tail(5).max()) if not df_1h.empty else 0.0

        return {
            "higher_highs_1h": higher_highs_1h,
            "higher_lows_1h": higher_lows_1h,
            "lower_highs_1h": lower_highs_1h,
            "lower_lows_1h": lower_lows_1h,
            "compression_detected": bool(last_1h_bb_width < 0.05),
            "range_fit_score": float(max(0.0, 1.0 - min(1.0, last_1h_adx / 35.0))),
            "trend_fit_score": float(min(1.0, last_4h_adx / 30.0)),
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "support_1h": nearest_support,
            "resistance_1h": nearest_resistance,
            "swing_low_1h": swing_low_1h,
            "swing_high_1h": swing_high_1h,
            "range_low": nearest_support,
            "range_high": nearest_resistance,
        }

    def _build_technical_flags(self, df_15m, df_1h, df_4h, df_1d) -> List[str]:
        flags: List[str] = []

        flags.append("4h ema50 above ema200" if self._last(df_4h, "ema_50") > self._last(df_4h, "ema_200") else "4h ema50 below ema200")
        flags.append("1d ema50 above ema200" if self._last(df_1d, "ema_50") > self._last(df_1d, "ema_200") else "1d ema50 below ema200")
        flags.append("1h ema20 above ema50" if self._last(df_1h, "ema_20") > self._last(df_1h, "ema_50") else "1h ema20 below ema50")

        if self._last(df_15m, "adx_14") >= 25:
            flags.append("15m adx strong")
        if self._last(df_1h, "adx_14") >= 25:
            flags.append("1h adx strong")
        if self._last(df_1h, "close") >= self._last(df_1h, "donchian_20_high") * 0.995:
            flags.append("near 1h donchian20 high")
        if self._last(df_1h, "close") <= self._last(df_1h, "donchian_20_low") * 1.005:
            flags.append("near 1h donchian20 low")
        if self._last(df_1h, "bb_width_pct") < 0.05:
            flags.append("1h compression")

        rsi_1h = self._last(df_1h, "rsi_14")
        rsi_4h = self._last(df_4h, "rsi_14")
        if rsi_1h < 35:
            flags.append("1h oversold")
        if rsi_1h > 70:
            flags.append("1h overbought")
        if rsi_4h < 35:
            flags.append("4h oversold")
        if rsi_4h > 70:
            flags.append("4h overbought")

        return flags

    def _build_orderbook_context(
        self,
        ticker: str,
        best_bid: Decimal,
        best_ask: Decimal,
        mid_price: Decimal,
    ) -> Dict[str, Any]:
        """
        Behoudende orderboek-context.
        Als de client geen orderboek endpoint heeft of faalt, geven we gewoon beperkte context terug.
        """
        default_context = {
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "mid_price": str(mid_price),
            "bid_ask_spread_abs": str(best_ask - best_bid if best_bid > 0 and best_ask > 0 else Decimal("0")),
            "bid_ask_spread_pct": float((best_ask - best_bid) / best_ask) if best_ask > 0 else 0.0,
            "top_bid_size": "0",
            "top_ask_size": "0",
            "bid_depth_top5": "0",
            "ask_depth_top5": "0",
            "depth_imbalance_top5": 0.0,
            "book_pressure": "unknown",
            "snapshot_available": False,
        }

        try:
            if not hasattr(self.client, "get_product_book"):
                return default_context

            book = self.client.get_product_book(ticker)
            bids = book.get("bids", []) if isinstance(book, dict) else []
            asks = book.get("asks", []) if isinstance(book, dict) else []

            def _px(level: Any) -> Decimal:
                try:
                    if isinstance(level, dict):
                        return Decimal(str(level.get("price", "0")))
                    return Decimal(str(level[0]))
                except Exception:
                    return Decimal("0")

            def _sz(level: Any) -> Decimal:
                try:
                    if isinstance(level, dict):
                        return Decimal(str(level.get("size", "0")))
                    return Decimal(str(level[1]))
                except Exception:
                    return Decimal("0")

            top_bid_size = _sz(bids[0]) if bids else Decimal("0")
            top_ask_size = _sz(asks[0]) if asks else Decimal("0")
            bid_depth_top5 = sum((_sz(x) for x in bids[:5]), Decimal("0"))
            ask_depth_top5 = sum((_sz(x) for x in asks[:5]), Decimal("0"))

            imbalance = 0.0
            if bid_depth_top5 > 0 or ask_depth_top5 > 0:
                imbalance = float((bid_depth_top5 - ask_depth_top5) / (bid_depth_top5 + ask_depth_top5))

            if imbalance > 0.15:
                pressure = "bid_heavy"
            elif imbalance < -0.15:
                pressure = "ask_heavy"
            else:
                pressure = "balanced"

            context = dict(default_context)
            context.update({
                "top_bid_price": str(_px(bids[0])) if bids else "0",
                "top_ask_price": str(_px(asks[0])) if asks else "0",
                "top_bid_size": str(top_bid_size),
                "top_ask_size": str(top_ask_size),
                "bid_depth_top5": str(bid_depth_top5),
                "ask_depth_top5": str(ask_depth_top5),
                "depth_imbalance_top5": imbalance,
                "book_pressure": pressure,
                "snapshot_available": True,
            })
            return context

        except Exception:
            return default_context

    def build_feature_pack(self, ticker: str) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)

        df_15m = self._fetch_candles_df(ticker, "15m", 240)
        df_1h = self._fetch_candles_df(ticker, "1H", 240)
        df_4h = self._fetch_candles_df(ticker, "4H", 240)
        df_1d = self._fetch_candles_df(ticker, "1D", 240)

        df_15m, df_1h, df_4h, df_1d = self._enrich_timeframes(df_15m, df_1h, df_4h, df_1d)

        ticker_snapshot = self.client.get_public_ticker(ticker)
        best_bid = Decimal(str(ticker_snapshot.get("best_bid", "0")))
        best_ask = Decimal(str(ticker_snapshot.get("best_ask", "0")))
        mid_price = (best_bid + best_ask) / Decimal("2") if best_bid > 0 and best_ask > 0 else Decimal("0")
        spread_abs = best_ask - best_bid if best_ask > 0 and best_bid > 0 else Decimal("0")
        spread_pct = float((best_ask - best_bid) / best_ask) if best_ask > 0 else 0.0

        product = self.client.get_product(ticker)
        base_symbol, quote_symbol = ticker.split("-", 1)

        available_quote = self.client.get_available_balance(quote_symbol)
        available_base = self.client.get_available_balance(base_symbol)

        structure = self._build_structure(df_1h, df_4h)
        technical_flags = self._build_technical_flags(df_15m, df_1h, df_4h, df_1d)
        sentiment = self.news.build_sentiment_pack(ticker)
        social = self.news.build_social_pack(ticker)
        orderbook_context = self._build_orderbook_context(ticker, best_bid, best_ask, mid_price)

        bullish_evidence = [flag for flag in technical_flags if "above" in flag or "strong" in flag or "high" in flag]
        bearish_evidence = [flag for flag in technical_flags if "below" in flag or "oversold" in flag or "low" in flag]

        raw_context = {
            "15m": self._build_raw_slice(df_15m, limit=24),
            "1h": self._build_raw_slice(df_1h, limit=24),
            "4h": self._build_raw_slice(df_4h, limit=20),
            "1d": self._build_raw_slice(df_1d, limit=20),
        }

        microstructure = {
            "15m": self._build_microstructure(df_15m, limit=12),
            "1h": self._build_microstructure(df_1h, limit=12),
            "4h": self._build_microstructure(df_4h, limit=10),
            "1d": self._build_microstructure(df_1d, limit=10),
        }

        return {
            "ticker": ticker,
            "generated_at": self._now_utc().isoformat(),
            "market": {
                "best_bid": str(best_bid),
                "best_ask": str(best_ask),
                "mid_price": str(mid_price),
                "spread_abs": str(spread_abs),
                "spread_pct": spread_pct,
                "product_status": product.get("status"),
                "trading_disabled": bool(product.get("trading_disabled", False)),
                "cancel_only": bool(product.get("cancel_only", False)),
                "quote_increment": product.get("quote_increment"),
                "base_increment": product.get("base_increment"),
                "quote_min_size": product.get("quote_min_size"),
                "base_min_size": product.get("base_min_size"),
            },
            "indicators": {
                "15m": {
                    "close": self._last(df_15m, "close"),
                    "ema_20": self._last(df_15m, "ema_20"),
                    "ema_50": self._last(df_15m, "ema_50"),
                    "rsi_14": self._last(df_15m, "rsi_14"),
                    "atr_14": self._last(df_15m, "atr_14"),
                    "atr_pct": self._safe_div(self._last(df_15m, "atr_14"), self._last(df_15m, "close")),
                    "adx_14": self._last(df_15m, "adx_14"),
                },
                "1h": {
                    "close": self._last(df_1h, "close"),
                    "ema_20": self._last(df_1h, "ema_20"),
                    "ema_50": self._last(df_1h, "ema_50"),
                    "rsi_14": self._last(df_1h, "rsi_14"),
                    "atr_14": self._last(df_1h, "atr_14"),
                    "atr_pct": self._safe_div(self._last(df_1h, "atr_14"), self._last(df_1h, "close")),
                    "adx_14": self._last(df_1h, "adx_14"),
                    "bb_mid": self._last(df_1h, "bb_mid"),
                    "bb_upper": self._last(df_1h, "bb_upper"),
                    "bb_lower": self._last(df_1h, "bb_lower"),
                    "bb_width_pct": self._last(df_1h, "bb_width_pct"),
                    "donchian_20_high": self._last(df_1h, "donchian_20_high"),
                    "donchian_20_low": self._last(df_1h, "donchian_20_low"),
                    "donchian_55_high": self._last(df_1h, "donchian_55_high"),
                    "donchian_55_low": self._last(df_1h, "donchian_55_low"),
                    "distance_to_ema20_pct": self._safe_div(
                        self._last(df_1h, "close") - self._last(df_1h, "ema_20"),
                        self._last(df_1h, "close"),
                    ),
                },
                "4h": {
                    "close": self._last(df_4h, "close"),
                    "ema_50": self._last(df_4h, "ema_50"),
                    "ema_200": self._last(df_4h, "ema_200"),
                    "rsi_14": self._last(df_4h, "rsi_14"),
                    "atr_14": self._last(df_4h, "atr_14"),
                    "atr_pct": self._safe_div(self._last(df_4h, "atr_14"), self._last(df_4h, "close")),
                    "adx_14": self._last(df_4h, "adx_14"),
                    "trend_slope": slope(df_4h["close"], 10),
                },
                "1d": {
                    "close": self._last(df_1d, "close"),
                    "ema_50": self._last(df_1d, "ema_50"),
                    "ema_200": self._last(df_1d, "ema_200"),
                    "rsi_14": self._last(df_1d, "rsi_14"),
                    "trend_slope": slope(df_1d["close"], 10),
                },
            },
            "structure": structure,
            "raw_context": raw_context,
            "microstructure": microstructure,
            "orderbook_context": orderbook_context,
            "sentiment": {
                "news_summary_short": sentiment["news_summary_short"],
                "event_risk_level": sentiment["event_risk_level"],
                "sentiment_score": sentiment["sentiment_score"],
                "news_momentum_score": sentiment["news_momentum_score"],
                "narrative_tags": sentiment["narrative_tags"],
                # Real Reddit chatter (see social_context for detail/sources),
                # distinct from news_momentum_score which only re-measures the
                # RSS headline stream above.
                "social_engagement_score": social["social_engagement_score"],
                "social_available": social["social_available"],
            },
            "news_context": {
                "recent_headlines": sentiment["recent_headlines"],
                "fear_greed": sentiment["fear_greed"],
                "news_item_count": sentiment["news_item_count"],
                "rss_sources": sentiment["rss_sources"],
            },
            "social_context": {
                "social_post_count": social["social_post_count"],
                "social_top_posts": social["social_top_posts"],
                "social_sources": social["social_sources"],
            },
            "risk_context": {
                "base_symbol": base_symbol,
                "quote_symbol": quote_symbol,
                "available_quote_balance": str(available_quote),
                "available_base_balance": str(available_base),
                "max_notional_limit": str(Decimal(os.getenv("MAX_NOTIONAL_USD", "25.00"))),
                "max_spread_pct": os.getenv("MAX_SPREAD_PCT", "0.0100"),
            },
            "evidence": {
                "technical_flags": technical_flags,
                "bullish_evidence": bullish_evidence,
                "bearish_evidence": bearish_evidence,
                "uncertainties": [
                    "Headline-based sentiment is lightweight and can miss nuance",
                ],
                "raw_snippets_market": [
                    f"best_bid={best_bid}",
                    f"best_ask={best_ask}",
                    f"mid_price={mid_price}",
                    f"spread_pct={spread_pct:.6f}",
                    f"book_pressure={orderbook_context.get('book_pressure')}",
                ],
            },
        }
