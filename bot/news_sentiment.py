from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published_at: str
    summary: str
    score: float
    tags: List[str]


class NewsSentimentService:
    def __init__(self):
        self.enabled = self._get_bool_env("NEWS_ENABLED", True)
        self.timeout = self._get_int_env("NEWS_TIMEOUT_SECONDS", 12)
        self.lookback_hours = self._get_int_env("NEWS_LOOKBACK_HOURS", 48)
        self.max_items_per_feed = self._get_int_env("NEWS_MAX_ITEMS_PER_FEED", 15)
        self.max_headlines = self._get_int_env("NEWS_MAX_HEADLINES", 8)
        self.fng_enabled = self._get_bool_env("FNG_ENABLED", True)
        self.fng_url = os.getenv("FNG_API_URL", "https://api.alternative.me/fng/").strip()

        # Free, no-API-key social proxy: public Reddit post listings (read-only,
        # no OAuth). Deliberately separate from Santiment (bot/market_intelligence_context.py),
        # which is the real on-chain/crowd data source but needs a paid API key
        # that isn't configured. This is a lower-fidelity but zero-cost stand-in:
        # real user posts/comments/upvotes on crypto subreddits, not another
        # reading of the same RSS headlines (see news_momentum_score above).
        self.social_enabled = self._get_bool_env("SOCIAL_ENABLED", True)
        self.social_timeout = self._get_int_env("SOCIAL_TIMEOUT_SECONDS", 10)
        self.social_lookback_hours = self._get_int_env("SOCIAL_LOOKBACK_HOURS", 24)
        self.social_max_posts_per_sub = self._get_int_env("SOCIAL_MAX_POSTS_PER_SUB", 100)
        self.social_max_top_posts = self._get_int_env("SOCIAL_MAX_TOP_POSTS", 5)
        # Cache the raw subreddit listings for a few minutes so an 18-ticker
        # scan doesn't refetch the same pages 18x/hour and trip Reddit's
        # anti-bot rate limiting; only the per-ticker filtering happens fresh.
        self.social_cache_minutes = self._get_int_env("SOCIAL_CACHE_MINUTES", 15)
        default_subreddits = ["CryptoCurrency", "CryptoMarkets"]
        raw_subreddits = os.getenv("SOCIAL_SUBREDDITS", ",".join(default_subreddits))
        self.subreddits = [x.strip() for x in raw_subreddits.split(",") if x.strip()]
        self._social_cache: Dict[str, Any] = {"fetched_at": None, "posts": []}

        self.session = requests.Session()

        default_feeds = [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
        ]
        raw_feeds = os.getenv("NEWS_RSS_FEEDS", ",".join(default_feeds))
        self.feeds = [x.strip() for x in raw_feeds.split(",") if x.strip()]

        self.asset_aliases = {
            "BTC-USDC": ["btc", "bitcoin"],
            "ETH-USDC": ["eth", "ethereum", "ether"],
            "SOL-USDC": ["sol", "solana"],
            "XRP-USDC": ["xrp", "ripple"],
            "ADA-USDC": ["ada", "cardano"],
            "LINK-USDC": ["link", "chainlink"],
            "AVAX-USDC": ["avax", "avalanche"],
            "DOGE-USDC": ["doge", "dogecoin"],
            "SUI-USDC": ["sui"],
            "LTC-USDC": ["ltc", "litecoin"],
            "HBAR-USDC": ["hbar", "hedera", "hedera hashgraph"],
            "ATOM-USDC": ["atom", "cosmos"],
            "NEAR-USDC": ["near", "near protocol"],
            "APT-USDC": ["apt", "aptos"],
            "INJ-USDC": ["inj", "injective"],
            "ARB-USDC": ["arb", "arbitrum"],
            "OP-USDC": ["op", "optimism"],
            "UNI-USDC": ["uni", "uniswap"],
        }

        self.positive_keywords = {
            "approval": 1.2,
            "adoption": 1.0,
            "inflow": 1.1,
            "bullish": 1.1,
            "rally": 0.9,
            "surge": 0.8,
            "breakout": 0.8,
            "institutional": 0.7,
            "treasury": 0.7,
            "buy": 0.6,
            "launch": 0.5,
            "integrates": 0.5,
            "support": 0.4,
            "growth": 0.6,
            "partnership": 0.5,
            "expands": 0.5,
        }

        self.negative_keywords = {
            "hack": -1.4,
            "exploit": -1.3,
            "lawsuit": -1.1,
            "ban": -1.0,
            "probe": -0.9,
            "fraud": -1.4,
            "selloff": -1.0,
            "drop": -0.8,
            "crash": -1.3,
            "liquidation": -0.9,
            "outflow": -0.9,
            "bearish": -1.0,
            "fear": -0.8,
            "decline": -0.7,
            "block": -0.6,
            "scrap": -0.5,
            "war": -0.7,
        }

        self.event_risk_keywords = {
            "sec": "regulation",
            "etf": "etf",
            "lawsuit": "legal",
            "court": "legal",
            "hack": "security",
            "exploit": "security",
            "fed": "macro",
            "rates": "macro",
            "tariff": "macro",
            "war": "macro",
            "ban": "regulation",
            "approval": "etf",
            "license": "regulation",
            "legislation": "regulation",
        }

    @staticmethod
    def _get_bool_env(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _normalize_score_to_unit(value: float, scale: float = 5.0) -> float:
        x = max(-scale, min(scale, value))
        return (x + scale) / (2 * scale)

    @staticmethod
    def _source_name_from_url(url: str) -> str:
        try:
            host = urlparse(url).netloc.lower()
            if "coindesk" in host:
                return "CoinDesk"
            if "cointelegraph" in host:
                return "Cointelegraph"
            return host or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _parse_pubdate(value: str) -> Optional[datetime]:
        if not value:
            return None

        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                continue

        return None

    def _within_lookback(self, dt: Optional[datetime]) -> bool:
        if dt is None:
            return False
        return dt >= (self._now_utc() - timedelta(hours=self.lookback_hours))

    def _extract_xml_text(self, item: ET.Element, tag_names: List[str]) -> str:
        for tag in tag_names:
            value = item.findtext(tag, default="")
            if value:
                return value
        return ""

    def _extract_atom_link(self, item: ET.Element) -> str:
        for link_el in item.findall("{*}link"):
            href = link_el.attrib.get("href", "")
            if href:
                return href
        for link_el in item.findall("link"):
            href = link_el.attrib.get("href", "")
            if href:
                return href
            if link_el.text:
                return link_el.text
        return ""

    def _fetch_feed(self, url: str) -> List[Dict[str, Any]]:
        try:
            r = self.session.get(url, timeout=self.timeout, headers={"User-Agent": "coinbase-bot/1.0"})
            r.raise_for_status()
        except Exception:
            return []

        try:
            root = ET.fromstring(r.content)
        except Exception:
            return []

        items: List[Dict[str, Any]] = []
        source = self._source_name_from_url(url)

        rss_items = root.findall(".//item")
        atom_items = root.findall(".//{*}entry")

        iterable = rss_items if rss_items else atom_items

        for item in iterable:
            title = self._clean_text(
                self._extract_xml_text(item, ["title", "{*}title"])
            )

            link = self._clean_text(
                self._extract_xml_text(item, ["link"])
            )
            if not link:
                link = self._clean_text(self._extract_atom_link(item))

            pub = (
                self._extract_xml_text(item, ["pubDate", "published", "updated", "{*}published", "{*}updated"])
                or ""
            )
            desc = self._clean_text(
                self._extract_xml_text(item, ["description", "summary", "{*}summary", "{*}content"])
            )

            pub_dt = self._parse_pubdate(pub)
            if not self._within_lookback(pub_dt):
                continue

            if not title or not link:
                continue

            items.append({
                "source": source,
                "title": title,
                "link": link,
                "published_at": pub_dt.isoformat() if pub_dt else "",
                "summary": desc[:300],
            })

            if len(items) >= self.max_items_per_feed:
                break

        return items

    def _score_text(self, text: str) -> tuple[float, List[str]]:
        text_l = text.lower()
        score = 0.0
        tags: List[str] = []

        for kw, weight in self.positive_keywords.items():
            if kw in text_l:
                score += weight
                tags.append(f"pos:{kw}")

        for kw, weight in self.negative_keywords.items():
            if kw in text_l:
                score += weight
                tags.append(f"neg:{kw}")

        for kw, tag in self.event_risk_keywords.items():
            if kw in text_l:
                tags.append(f"risk:{tag}")

        return score, list(dict.fromkeys(tags))

    def _matches_ticker(self, ticker: str, text: str) -> bool:
        aliases = self.asset_aliases.get(ticker.upper(), [])
        text_l = text.lower()

        for alias in aliases:
            pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
            if re.search(pattern, text_l):
                return True
        return False

    def _ticker_news_items(self, ticker: str, items: List[Dict[str, Any]]) -> List[NewsItem]:
        out: List[NewsItem] = []

        for item in items:
            blob = f"{item['title']} {item.get('summary', '')}"
            base_score, tags = self._score_text(blob)

            blob_l = blob.lower()

            if self._matches_ticker(ticker, blob):
                base_score *= 1.25
                tags.append("asset_match")
            elif any(x in blob_l for x in ["crypto", "bitcoin", "ethereum", "solana", "markets", "market"]):
                base_score *= 0.85
            else:
                continue

            out.append(
                NewsItem(
                    source=item["source"],
                    title=item["title"],
                    link=item["link"],
                    published_at=item["published_at"],
                    summary=item.get("summary", ""),
                    score=base_score,
                    tags=list(dict.fromkeys(tags)),
                )
            )

        out.sort(
            key=lambda x: self._parse_pubdate(x.published_at) or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        return out

    def _summarize_headlines(self, items: List[NewsItem], max_items: int) -> List[Dict[str, Any]]:
        out = []
        for item in items[:max_items]:
            out.append({
                "source": item.source,
                "title": item.title,
                "published_at": item.published_at,
                "score": round(item.score, 4),
                "tags": item.tags[:8],
                "link": item.link,
            })
        return out

    def _event_risk_level(self, items: List[NewsItem]) -> str:
        risk_hits = 0
        for item in items[:8]:
            if any(tag.startswith("risk:") for tag in item.tags):
                risk_hits += 1

        if risk_hits >= 4:
            return "high"
        if risk_hits >= 2:
            return "medium"
        return "low"

    def _narrative_tags(self, items: List[NewsItem]) -> List[str]:
        counts: Dict[str, int] = {}
        for item in items[:12]:
            for tag in item.tags:
                if tag.startswith("risk:"):
                    key = tag.replace("risk:", "")
                    counts[key] = counts.get(key, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in ranked[:5]]

    def _summary_text(self, items: List[NewsItem], fng_label: Optional[str]) -> str:
        if not items:
            if fng_label:
                return f"No major recent ticker-specific headlines found; broad market mood is {fng_label.lower()}."
            return "No major recent ticker-specific headlines found."

        top = items[:3]
        titles = "; ".join(x.title for x in top)
        if fng_label:
            return f"Recent headlines: {titles}. Broad crypto mood: {fng_label.lower()}."
        return f"Recent headlines: {titles}."

    def _fetch_fng(self) -> Dict[str, Any]:
        if not self.fng_enabled:
            return {}

        try:
            r = self.session.get(self.fng_url, timeout=self.timeout, headers={"User-Agent": "coinbase-bot/1.0"})
            r.raise_for_status()
            data = r.json()
            values = data.get("data", [])
            if not values:
                return {}
            item = values[0]
            return {
                "value": int(item.get("value", 0)),
                "classification": str(item.get("value_classification", "")),
                "timestamp": str(item.get("timestamp", "")),
            }
        except Exception:
            return {}

    def _fetch_reddit_listing(self, subreddit: str) -> List[Dict[str, Any]]:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={self.social_max_posts_per_sub}"
        try:
            r = self.session.get(
                url,
                timeout=self.social_timeout,
                headers={"User-Agent": "coinbase-bot-social-scan/1.0 (read-only public listing fetch)"},
            )
            r.raise_for_status()
            payload = r.json()
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        children = ((payload or {}).get("data") or {}).get("children") or []
        for child in children:
            post = (child or {}).get("data") or {}
            created_utc = post.get("created_utc")
            try:
                created_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc) if created_utc else None
            except (TypeError, ValueError, OSError):
                created_dt = None
            if not self._within_social_lookback(created_dt):
                continue
            title = self._clean_text(str(post.get("title") or ""))
            if not title:
                continue
            out.append({
                "subreddit": subreddit,
                "title": title,
                "selftext": self._clean_text(str(post.get("selftext") or ""))[:300],
                "created_at": created_dt.isoformat() if created_dt else "",
                "upvotes": int(post.get("ups") or 0),
                "num_comments": int(post.get("num_comments") or 0),
                "permalink": self._clean_text(str(post.get("permalink") or "")),
            })
        return out

    def _within_social_lookback(self, dt: Optional[datetime]) -> bool:
        if dt is None:
            return False
        return dt >= (self._now_utc() - timedelta(hours=self.social_lookback_hours))

    def _fetch_all_reddit_posts(self) -> List[Dict[str, Any]]:
        cached_at = self._social_cache.get("fetched_at")
        if cached_at is not None and (self._now_utc() - cached_at) < timedelta(minutes=self.social_cache_minutes):
            return self._social_cache["posts"]

        posts: List[Dict[str, Any]] = []
        for subreddit in self.subreddits:
            posts.extend(self._fetch_reddit_listing(subreddit))

        self._social_cache = {"fetched_at": self._now_utc(), "posts": posts}
        return posts

    def build_social_pack(self, ticker: str) -> Dict[str, Any]:
        if not self.social_enabled:
            return {
                "social_available": False,
                "social_engagement_score": 0.50,
                "social_post_count": 0,
                "social_top_posts": [],
                "social_sources": [],
            }

        all_posts = self._fetch_all_reddit_posts()
        if not all_posts:
            # Empty could mean "no chatter" or "Reddit fetch failed/blocked";
            # do not claim availability when nothing at all came back for any
            # subreddit, so callers/prompts don't read this as a real zero.
            return {
                "social_available": False,
                "social_engagement_score": 0.50,
                "social_post_count": 0,
                "social_top_posts": [],
                "social_sources": [f"reddit:{s}" for s in self.subreddits],
            }

        matched = [
            post for post in all_posts
            if self._matches_ticker(ticker, f"{post['title']} {post.get('selftext', '')}")
        ]
        matched.sort(key=lambda p: (p.get("upvotes", 0) + p.get("num_comments", 0)), reverse=True)

        post_count = len(matched)
        volume_component = min(1.0, post_count / 10.0)
        engagement_total = sum(p.get("upvotes", 0) + p.get("num_comments", 0) for p in matched[:20])
        engagement_component = min(1.0, engagement_total / 500.0)
        social_engagement_score = round((volume_component * 0.5) + (engagement_component * 0.5), 4)

        return {
            "social_available": True,
            "social_engagement_score": social_engagement_score,
            "social_post_count": post_count,
            "social_top_posts": [
                {
                    "subreddit": p["subreddit"],
                    "title": p["title"],
                    "upvotes": p.get("upvotes", 0),
                    "num_comments": p.get("num_comments", 0),
                    "created_at": p.get("created_at", ""),
                }
                for p in matched[: self.social_max_top_posts]
            ],
            "social_sources": [f"reddit:{s}" for s in self.subreddits],
        }

    def build_sentiment_pack(self, ticker: str) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "news_summary_short": "News pipeline disabled.",
                "event_risk_level": "low",
                "sentiment_score": 0.50,
                "news_momentum_score": 0.50,
                "narrative_tags": [],
                "recent_headlines": [],
                "fear_greed": {},
            }

        all_items: List[Dict[str, Any]] = []
        for feed in self.feeds:
            all_items.extend(self._fetch_feed(feed))

        ticker_items = self._ticker_news_items(ticker, all_items)
        fng = self._fetch_fng()

        avg_score = 0.0
        if ticker_items:
            avg_score = sum(x.score for x in ticker_items[:10]) / min(len(ticker_items), 10)

        sentiment_score = self._normalize_score_to_unit(avg_score, scale=4.0)

        if fng:
            fng_value = float(fng.get("value", 50))
            fng_unit = self._clamp(fng_value / 100.0, 0.0, 1.0)
            sentiment_score = round((sentiment_score * 0.65) + (fng_unit * 0.35), 4)
        else:
            sentiment_score = round(sentiment_score, 4)

        # Derived purely from this same RSS headline stream (volume + score
        # intensity) -- NOT real social-platform data (no Twitter/Reddit/etc.
        # feed exists here). Keep the name honest so it isn't mistaken for an
        # independent corroborating signal alongside sentiment_score; see
        # market_intelligence_context.py's santiment social_volume_spike for
        # the real (currently disabled, no API key) social-data source.
        headline_intensity = min(1.0, len(ticker_items) / max(1, self.max_headlines))
        score_intensity = min(1.0, abs(avg_score) / 3.0)
        news_momentum_score = round((headline_intensity * 0.55) + (score_intensity * 0.45), 4)

        event_risk_level = self._event_risk_level(ticker_items)
        narrative_tags = self._narrative_tags(ticker_items)
        summary = self._summary_text(ticker_items, fng.get("classification"))

        return {
            "news_summary_short": summary,
            "event_risk_level": event_risk_level,
            "sentiment_score": sentiment_score,
            "news_momentum_score": news_momentum_score,
            "narrative_tags": narrative_tags,
            "recent_headlines": self._summarize_headlines(ticker_items, self.max_headlines),
            "fear_greed": fng,
            "news_item_count": len(ticker_items),
            "rss_sources": self.feeds,
        }