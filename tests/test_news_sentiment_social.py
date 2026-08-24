from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from bot.news_sentiment import NewsSentimentService


def _reddit_response(posts):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": {"children": [{"data": p} for p in posts]}}
    return resp


def _post(title, *, hours_ago=1.0, ups=10, num_comments=2, selftext=""):
    created = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "title": title,
        "selftext": selftext,
        "created_utc": created.timestamp(),
        "ups": ups,
        "num_comments": num_comments,
        "permalink": "/r/test/comments/1/",
    }


def _service(**env_overrides):
    import os

    env = {
        "SOCIAL_ENABLED": "true",
        "SOCIAL_SUBREDDITS": "CryptoCurrency,CryptoMarkets",
        "SOCIAL_CACHE_MINUTES": "15",
        "SOCIAL_LOOKBACK_HOURS": "24",
        "NEWS_ENABLED": "false",
    }
    env.update(env_overrides)
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return NewsSentimentService(), old, env
    finally:
        pass


def _restore(old):
    import os

    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_social_disabled_returns_neutral_defaults():
    svc, old, _ = _service(SOCIAL_ENABLED="false")
    try:
        pack = svc.build_social_pack("BTC-USDC")
        assert pack["social_available"] is False
        assert pack["social_engagement_score"] == 0.50
        assert pack["social_post_count"] == 0
        assert pack["social_top_posts"] == []
        assert pack["social_sources"] == []
    finally:
        _restore(old)


def test_social_fetch_failure_is_unavailable_not_a_fake_zero():
    svc, old, _ = _service()
    try:
        svc.session.get = MagicMock(side_effect=Exception("boom"))
        pack = svc.build_social_pack("BTC-USDC")
        assert pack["social_available"] is False
        assert pack["social_engagement_score"] == 0.50
        assert pack["social_sources"] == ["reddit:CryptoCurrency", "reddit:CryptoMarkets"]
    finally:
        _restore(old)


def test_social_matches_ticker_and_scores_engagement():
    svc, old, _ = _service(SOCIAL_SUBREDDITS="CryptoCurrency")
    try:
        posts = [
            _post("Bitcoin about to break out", ups=100, num_comments=50),
            _post("Some unrelated altcoin news", ups=5, num_comments=1),
        ]
        svc.session.get = MagicMock(return_value=_reddit_response(posts))

        pack = svc.build_social_pack("BTC-USDC")

        assert pack["social_available"] is True
        assert pack["social_post_count"] == 1
        assert pack["social_top_posts"][0]["title"] == "Bitcoin about to break out"
        assert 0.0 < pack["social_engagement_score"] <= 1.0
    finally:
        _restore(old)


def test_social_excludes_posts_outside_lookback_window():
    svc, old, _ = _service(SOCIAL_LOOKBACK_HOURS="6")
    try:
        posts = [_post("Bitcoin whale alert", hours_ago=48)]
        svc.session.get = MagicMock(return_value=_reddit_response(posts))

        pack = svc.build_social_pack("BTC-USDC")

        assert pack["social_post_count"] == 0
    finally:
        _restore(old)


def test_social_listing_is_cached_across_calls():
    svc, old, _ = _service()
    try:
        posts = [_post("Bitcoin rally continues")]
        svc.session.get = MagicMock(return_value=_reddit_response(posts))

        svc.build_social_pack("BTC-USDC")
        svc.build_social_pack("ETH-USDC")

        assert svc.session.get.call_count == len(svc.subreddits)
    finally:
        _restore(old)
