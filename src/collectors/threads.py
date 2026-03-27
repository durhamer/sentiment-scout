"""Threads collector using the official Threads Graph API."""

import os
import time
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

from .base import BaseCollector, Comment, Post

load_dotenv()

_BASE_URL = "https://graph.threads.net/v1.0"


class AppReviewPendingError(RuntimeError):
    """Raised when the Threads API rejects a call due to pending App Review."""
_DEFAULT_POST_FIELDS = "id,text,timestamp,like_count,username,permalink"
_DEFAULT_REPLY_FIELDS = "id,text,timestamp,like_count,username"
_REQUEST_INTERVAL = 2.0  # seconds between requests


class ThreadsCollector(BaseCollector):
    """Collect posts from Threads via the official Graph API.

    Notes
    -----
    Keyword search currently returns only the authenticated user's own posts
    until the ``threads_keyword_search`` permission is approved via App Review.
    Once approved, search() will return public posts matching the keyword.
    """

    platform_name = "threads"

    def __init__(
        self,
        access_token: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self._token = access_token or os.getenv("THREADS_ACCESS_TOKEN", "")
        self._user_id = user_id or os.getenv("THREADS_USER_ID", "")
        self._last_request_at: float = 0.0

        if not self._token:
            raise ValueError(
                "Threads access token is required. "
                "Set THREADS_ACCESS_TOKEN in your .env file."
            )
        if not self._user_id:
            raise ValueError(
                "Threads user ID is required. "
                "Set THREADS_USER_ID in your .env file."
            )

    # ── Public interface ───────────────────────────────────────────

    def search(
        self,
        keywords: list[str],
        max_posts: int = 25,
        **kwargs,
    ) -> list[Post]:
        """Search Threads for posts matching *keywords*.

        Because ``threads_keyword_search`` App Review may not yet be approved,
        this can return only the authenticated user's own posts or an empty
        list.  The caller receives a proper list[Post] either way.
        """
        posts: list[Post] = []
        seen_ids: set[str] = set()

        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue

            try:
                data = self._get(
                    f"{_BASE_URL}/{self._user_id}/threads_keyword_search",
                    params={
                        "q": keyword,
                        "fields": _DEFAULT_POST_FIELDS,
                    },
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 500:
                    # Threads returns 500 when threads_keyword_search permission
                    # has not been approved via App Review yet.  Treat as empty.
                    raise AppReviewPendingError(
                        "threads_keyword_search 尚未通過 App Review，"
                        "無法執行關鍵字搜尋（伺服器回傳 500）。"
                    ) from e
                raise

            for item in data.get("data", []):
                post_id = item.get("id")
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                posts.append(self._item_to_post(item))
                if len(posts) >= max_posts:
                    return posts

        return posts

    def get_post_with_comments(
        self,
        post_id: str,
        max_comments: int = 50,
    ) -> Post:
        """Fetch a single Threads post and its replies."""
        # Fetch the post itself
        post_data = self._get(
            f"{_BASE_URL}/{post_id}",
            params={"fields": _DEFAULT_POST_FIELDS},
        )
        post = self._item_to_post(post_data)

        # Fetch replies
        replies_data = self._get(
            f"{_BASE_URL}/{post_id}/replies",
            params={"fields": _DEFAULT_REPLY_FIELDS},
        )
        comments: list[Comment] = []
        for item in replies_data.get("data", [])[:max_comments]:
            comment = self._item_to_comment(item, parent_id=post_id)
            comments.append(comment)

        post.comments = comments
        post.num_comments = len(comments)
        return post

    # ── Private helpers ────────────────────────────────────────────

    def _rate_limited_get(self, url: str, params: dict) -> dict:
        """Issue a GET request, honoring the 2-second inter-request delay."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _REQUEST_INTERVAL:
            time.sleep(_REQUEST_INTERVAL - elapsed)

        params = {**params, "access_token": self._token}
        resp = requests.get(url, params=params, timeout=15)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return resp.json()

    def _get(self, url: str, params: dict) -> dict:
        return self._rate_limited_get(url, params)

    @staticmethod
    def _parse_timestamp(ts: Optional[str]) -> datetime:
        if not ts:
            return datetime.utcnow()
        # Threads returns ISO 8601 with timezone, e.g. "2024-01-15T12:34:56+0000"
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+0000"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        return datetime.utcnow()

    def _item_to_post(self, item: dict) -> Post:
        post_id = item.get("id", "")
        return Post(
            id=post_id,
            platform=self.platform_name,
            title="",  # Threads has no post titles
            body=item.get("text") or "",
            author=item.get("username") or "",
            score=item.get("like_count") or 0,
            num_comments=0,
            created_at=self._parse_timestamp(item.get("timestamp")),
            url=item.get("permalink") or f"https://www.threads.net/t/{post_id}",
            subreddit=None,
            metadata={
                "like_count": item.get("like_count") or 0,
                "permalink": item.get("permalink") or "",
            },
        )

    def _item_to_comment(self, item: dict, parent_id: str) -> Comment:
        return Comment(
            id=item.get("id", ""),
            platform=self.platform_name,
            author=item.get("username") or "",
            body=item.get("text") or "",
            score=item.get("like_count") or 0,
            created_at=self._parse_timestamp(item.get("timestamp")),
            parent_id=parent_id,
            metadata={"like_count": item.get("like_count") or 0},
        )
