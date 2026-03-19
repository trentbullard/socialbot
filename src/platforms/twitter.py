"""Twitter/X platform adapter using tweepy."""

from __future__ import annotations

import tweepy
import tweepy.asynchronous
from loguru import logger

from src.platforms.base import PlatformAdapter, PostResult, TrendingPost


class TwitterAdapter(PlatformAdapter):
    """Posts content to Twitter/X via the v2 API."""

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._client: tweepy.Client | None = None

    async def authenticate(self) -> None:
        logger.debug("Authenticating Twitter client...")
        self._client = tweepy.Client(
            consumer_key=self._credentials["api_key_env"],
            consumer_secret=self._credentials["api_secret_env"],
            access_token=self._credentials["access_token_env"],
            access_token_secret=self._credentials["access_secret_env"],
        )
        logger.info("Twitter client authenticated")

    async def validate_credentials(self) -> bool:
        if self._client is None:
            return False
        try:
            me = self._client.get_me()
            return me.data is not None
        except tweepy.TweepyException as exc:
            logger.warning("Twitter credential validation failed: %s", exc)
            return False

    async def post(self, content: str, media_url: str | None = None) -> PostResult:
        if self._client is None:
            return PostResult(success=False, error="Not authenticated")

        try:
            # TODO: media upload support when media_url is provided
            response = self._client.create_tweet(text=content)
            tweet_id = str(response.data["id"])
            url = f"https://x.com/i/status/{tweet_id}"
            logger.info("Posted tweet %s", tweet_id)
            return PostResult(success=True, post_id=tweet_id, url=url)
        except tweepy.TweepyException as exc:
            logger.error("Failed to post tweet: %s", exc)
            return PostResult(success=False, error=str(exc))

    async def search_recent(self, query: str, max_results: int = 10) -> list[TrendingPost]:
        """Search Twitter for recent popular tweets related to a query."""
        if self._client is None:
            logger.warning("Cannot search — not authenticated")
            return []

        try:
            clamped = max(10, min(max_results, 100))
            response = self._client.search_recent_tweets(
                query=f"{query} -is:retweet lang:en",
                max_results=clamped,
                sort_order="relevancy",
                tweet_fields=["public_metrics", "entities", "author_id"],
            )

            if not response.data:
                logger.debug("No tweets found for query: {}", query)
                return []

            results: list[TrendingPost] = []
            for tweet in response.data:
                metrics = tweet.public_metrics or {}
                engagement = (
                    metrics.get("like_count", 0)
                    + metrics.get("retweet_count", 0)
                    + metrics.get("reply_count", 0)
                )
                hashtags = []
                if tweet.entities and "hashtags" in tweet.entities:
                    hashtags = [h["tag"] for h in tweet.entities["hashtags"]]

                results.append(TrendingPost(
                    text=tweet.text,
                    author=tweet.author_id or "",
                    engagement=engagement,
                    hashtags=hashtags,
                ))

            results.sort(key=lambda p: p.engagement, reverse=True)
            logger.info("Found {} trending tweets for '{}'", len(results), query)
            return results

        except tweepy.TweepyException as exc:
            logger.warning("Twitter search failed: {}", exc)
            return []
