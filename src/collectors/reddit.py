"""Reddit collector using public JSON endpoints (no API credentials needed).

Reddit exposes public data via .json suffix on any URL.
Rate limit: ~10 requests/minute for unauthenticated access.
Read-only by design — no write capabilities.
"""

import time
from datetime import datetime, timezone

import requests

from .base import BaseCollector, Post, Comment


class RedditCollector(BaseCollector):
    """Collect posts and comments from Reddit via public JSON endpoints."""

    platform_name = "reddit"
    BASE_URL = "https://www.reddit.com"

    # Respect rate limits: ~10 req/min → at least 6s between requests
    REQUEST_INTERVAL = 6.5

    def __init__(self, user_agent: str = "sentiment-scout/1.0"):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request_time = 0.0

    def _rate_limited_get(self, url: str, params: dict | None = None) -> dict:
        """Make a GET request with rate limiting."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.REQUEST_INTERVAL:
            time.sleep(self.REQUEST_INTERVAL - elapsed)

        response = self.session.get(url, params=params, timeout=15)
        self._last_request_time = time.time()

        if response.status_code == 429:
            # Rate limited — back off and retry once
            print("[Reddit] Rate limited, waiting 30s...")
            time.sleep(30)
            response = self.session.get(url, params=params, timeout=15)
            self._last_request_time = time.time()

        response.raise_for_status()
        return response.json()

    # ── Public API ────────────────────────────────────────────────

    def search(
        self,
        keywords: list[str],
        subreddits: list[str] | None = None,
        sort: str = "relevance",
        time_filter: str = "week",
        max_posts: int = 25,
    ) -> list[Post]:
        """
        Search Reddit for posts matching keywords.

        Args:
            keywords: List of search terms (OR-joined)
            subreddits: Specific subreddits to search (None = all)
            sort: relevance, hot, top, new, comments
            time_filter: hour, day, week, month, year, all
            max_posts: Maximum posts to return per subreddit
        """
        query = " OR ".join(keywords)
        posts = []

        targets = subreddits or ["all"]

        for sub_name in targets:
            try:
                url = f"{self.BASE_URL}/r/{sub_name}/search.json"
                params = {
                    "q": query,
                    "sort": sort,
                    "t": time_filter,
                    "limit": min(max_posts, 100),  # Reddit max is 100
                    "restrict_sr": "on",  # Restrict to this subreddit
                }
                if sub_name == "all":
                    params.pop("restrict_sr")

                data = self._rate_limited_get(url, params)
                children = data.get("data", {}).get("children", [])

                for child in children:
                    if child.get("kind") == "t3":  # t3 = link/post
                        post = self._json_to_post(child["data"])
                        posts.append(post)

                print(f"[Reddit] r/{sub_name}: found {len(children)} posts")

            except Exception as e:
                print(f"[Reddit] Error searching r/{sub_name}: {e}")

        return posts

    def get_post_with_comments(
        self, post_id: str, max_comments: int = 50
    ) -> Post:
        """Fetch a Reddit post with its comment tree."""
        url = f"{self.BASE_URL}/comments/{post_id}.json"
        params = {"limit": max_comments, "depth": 3}

        data = self._rate_limited_get(url, params)

        # Response is a list: [post_listing, comments_listing]
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError(f"Unexpected response format for post {post_id}")

        # Parse post
        post_data = data[0]["data"]["children"][0]["data"]
        post = self._json_to_post(post_data)

        # Parse comments
        comment_children = data[1]["data"]["children"]
        count = 0
        for child in comment_children:
            if count >= max_comments:
                break
            if child.get("kind") == "t1":  # t1 = comment
                comment = self._json_to_comment(child["data"], post_id)
                post.comments.append(comment)
                count += 1

                # Also grab first-level replies
                replies = child["data"].get("replies")
                if isinstance(replies, dict):
                    for reply_child in replies.get("data", {}).get("children", []):
                        if count >= max_comments:
                            break
                        if reply_child.get("kind") == "t1":
                            reply = self._json_to_comment(reply_child["data"], post_id)
                            post.comments.append(reply)
                            count += 1

        return post

    def get_subreddit_listing(
        self, subreddit: str, listing: str = "hot", limit: int = 25
    ) -> list[Post]:
        """
        Get posts from a subreddit listing.

        Args:
            subreddit: Subreddit name
            listing: hot, new, rising, top
            limit: Max posts to return
        """
        url = f"{self.BASE_URL}/r/{subreddit}/{listing}.json"
        params = {"limit": min(limit, 100)}

        data = self._rate_limited_get(url, params)
        posts = []

        for child in data.get("data", {}).get("children", []):
            if child.get("kind") == "t3":
                posts.append(self._json_to_post(child["data"]))

        return posts

    # ── Internal helpers ──────────────────────────────────────────

    def _json_to_post(self, data: dict) -> Post:
        """Convert Reddit JSON post data to Post model."""
        created_utc = data.get("created_utc", 0)
        return Post(
            id=data.get("id", ""),
            platform="reddit",
            title=data.get("title", ""),
            body=data.get("selftext", ""),
            author=data.get("author", "[deleted]"),
            score=data.get("score", 0),
            num_comments=data.get("num_comments", 0),
            created_at=datetime.fromtimestamp(created_utc, tz=timezone.utc),
            url=f"https://reddit.com{data.get('permalink', '')}",
            subreddit=data.get("subreddit", ""),
        )

    def _json_to_comment(self, data: dict, post_id: str) -> Comment:
        """Convert Reddit JSON comment data to Comment model."""
        created_utc = data.get("created_utc", 0)
        return Comment(
            id=data.get("id", ""),
            platform="reddit",
            author=data.get("author", "[deleted]"),
            body=data.get("body", ""),
            score=data.get("score", 0),
            created_at=datetime.fromtimestamp(created_utc, tz=timezone.utc),
            parent_id=data.get("parent_id", ""),
            url=f"https://reddit.com{data.get('permalink', '')}",
            metadata={"is_submitter": data.get("is_submitter", False)},
        )


# ── CLI entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    import yaml
    from rich.console import Console
    from rich.table import Table

    console = Console()

    with open("config/settings.yaml") as f:
        config = yaml.safe_load(f)

    collector = RedditCollector()
    mon = config["monitoring"]

    console.print(f"[bold green]🔍 Searching Reddit for:[/] {mon['keywords']}")
    console.print("[dim]Using public JSON endpoints (no API key needed)[/]\n")

    posts = collector.search(
        keywords=mon["keywords"],
        subreddits=mon["reddit"]["subreddits"],
        sort=mon["reddit"]["sort_by"],
        time_filter=mon["reddit"]["time_filter"],
        max_posts=mon["reddit"]["max_posts_per_sub"],
    )

    table = Table(title=f"Found {len(posts)} posts")
    table.add_column("Sub", style="cyan", width=15)
    table.add_column("Score", justify="right", style="green", width=6)
    table.add_column("Title", style="white", max_width=60)
    table.add_column("Comments", justify="right", width=8)

    for p in sorted(posts, key=lambda x: x.score, reverse=True):
        table.add_row(p.subreddit, str(p.score), p.title, str(p.num_comments))

    console.print(table)
    console.print(f"\n[dim]💡 Rate limit: ~10 req/min. Fetched with {collector.REQUEST_INTERVAL}s intervals.[/]")
