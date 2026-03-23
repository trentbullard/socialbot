"""Twitter/X platform adapter using tweepy."""

from __future__ import annotations

from datetime import datetime, timezone

import tweepy
import tweepy.asynchronous
from loguru import logger

from src.platforms.base import PlatformAdapter, PostResult, ReplyCandidate, TrendingPost


class TwitterAdapter(PlatformAdapter):
    """Posts content to Twitter/X via the v2 API."""

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._client: tweepy.Client | None = None
        self._api: tweepy.API | None = None  # v1.1 API for media upload
        self._user_id: str = ""
        self._username: str = ""

    async def authenticate(self) -> None:
        logger.debug("Authenticating Twitter client...")
        self._client = tweepy.Client(
            consumer_key=self._credentials["api_key_env"],
            consumer_secret=self._credentials["api_secret_env"],
            access_token=self._credentials["access_token_env"],
            access_token_secret=self._credentials["access_secret_env"],
        )
        # v1.1 API is needed for media uploads
        auth = tweepy.OAuth1UserHandler(
            self._credentials["api_key_env"],
            self._credentials["api_secret_env"],
            self._credentials["access_token_env"],
            self._credentials["access_secret_env"],
        )
        self._api = tweepy.API(auth)
        logger.info("Twitter client authenticated (v2 + v1.1 media)")

    async def validate_credentials(self) -> bool:
        if self._client is None:
            return False
        try:
            me = self._client.get_me()
            if me.data is None:
                return False
            self._user_id = str(me.data.id)
            self._username = getattr(me.data, "username", "") or ""
            return True
        except tweepy.TweepyException as exc:
            logger.warning("Twitter credential validation failed: {}", exc)
            return False

    async def post(
        self,
        content: str,
        media_path: str | None = None,
        in_reply_to_post_id: str | None = None,
    ) -> PostResult:
        if self._client is None:
            return PostResult(success=False, error="Not authenticated")

        try:
            media_ids = None
            if media_path and self._api is not None:
                logger.debug("Uploading media: {}", media_path)
                media = self._api.media_upload(filename=media_path)
                media_ids = [media.media_id]
                logger.info("Uploaded media, id={}", media.media_id)

            response = self._client.create_tweet(
                text=content,
                media_ids=media_ids,
                in_reply_to_tweet_id=in_reply_to_post_id,
            )
            tweet_id = str(response.data["id"])
            url = f"https://x.com/i/status/{tweet_id}"
            logger.info("Posted tweet {}", tweet_id)
            return PostResult(success=True, post_id=tweet_id, url=url)
        except tweepy.TweepyException as exc:
            logger.error("Failed to post tweet: {}", exc)
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

    async def list_direct_replies(
        self,
        post_id: str,
        since_id: str | None = None,
    ) -> list[ReplyCandidate]:
        if self._client is None:
            logger.warning("Cannot list replies — not authenticated")
            return []

        try:
            response = self._client.search_recent_tweets(
                query=f"conversation_id:{post_id}",
                since_id=since_id,
                max_results=100,
                sort_order="recency",
                expansions=["author_id"],
                tweet_fields=[
                    "author_id",
                    "conversation_id",
                    "created_at",
                    "referenced_tweets",
                ],
                user_fields=["username"],
            )
        except tweepy.TweepyException as exc:
            logger.warning("Twitter reply search failed for {}: {}", post_id, exc)
            return []

        if not response.data:
            return []

        includes = getattr(response, "includes", {}) or {}
        users = includes.get("users", []) if isinstance(includes, dict) else []
        user_map = {
            str(user.id): getattr(user, "username", "") or ""
            for user in users
        }

        results: list[ReplyCandidate] = []
        for tweet in response.data:
            parent_id = self._extract_replied_to_parent_id(tweet)
            if parent_id != post_id:
                continue

            created_at = getattr(tweet, "created_at", None) or datetime.now(timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            author_id = str(getattr(tweet, "author_id", "") or "")
            results.append(ReplyCandidate(
                reply_id=str(tweet.id),
                parent_post_id=post_id,
                author_id=author_id,
                author_handle=user_map.get(author_id, ""),
                text=getattr(tweet, "text", "") or "",
                created_at=created_at,
            ))

        return results

    def get_authenticated_user_id(self) -> str:
        return self._user_id

    @staticmethod
    def _extract_replied_to_parent_id(tweet: object) -> str:
        for ref in getattr(tweet, "referenced_tweets", []) or []:
            ref_type = getattr(ref, "type", None)
            ref_id = getattr(ref, "id", None)
            if isinstance(ref, dict):
                ref_type = ref.get("type")
                ref_id = ref.get("id")
            if ref_type == "replied_to":
                return str(ref_id or "")
        return ""
