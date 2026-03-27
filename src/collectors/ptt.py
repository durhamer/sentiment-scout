"""PTT collector using web scraping (no official API).

PTT Web: https://www.ptt.cc/bbs/
Rate limit: 2 seconds between requests to avoid IP ban.
Read-only by design — no write capabilities.
"""

import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

import requests
from bs4 import BeautifulSoup

from .base import BaseCollector, Post, Comment


class PttCollector(BaseCollector):
    """Collect posts and comments from PTT via web scraping."""

    platform_name = "ptt"
    BASE_URL = "https://www.ptt.cc"

    # At least 2 seconds between requests
    REQUEST_INTERVAL = 2.0

    def __init__(self):
        self.session = requests.Session()
        # Required cookie to pass the over-18 gate (e.g. Gossiping board)
        self.session.cookies.set("over18", "1", domain="www.ptt.cc")
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        })
        self._last_request_time = 0.0

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        """Rate-limited GET request."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_INTERVAL:
            time.sleep(self.REQUEST_INTERVAL - elapsed)

        response = self.session.get(url, params=params, timeout=15)
        self._last_request_time = time.time()
        response.raise_for_status()
        return response

    # ── Public API ────────────────────────────────────────────────

    def search(
        self,
        keywords: list[str],
        boards: list[str] | None = None,
        max_posts: int = 25,
    ) -> list[Post]:
        """
        Search PTT boards for posts matching keywords.

        Args:
            keywords: Search terms (only first keyword used per board search)
            boards: PTT board names to search (defaults to ["Gossiping"])
            max_posts: Max posts to return per board per keyword
        """
        boards = boards or ["Gossiping"]
        posts = []

        for board in boards:
            for keyword in keywords:
                try:
                    url = f"{self.BASE_URL}/bbs/{board}/search"
                    params = {"q": keyword}
                    resp = self._get(url, params=params)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    board_posts = self._parse_listing(soup, board)
                    board_posts = board_posts[:max_posts]
                    posts.extend(board_posts)
                    print(f"[PTT] /{board} 搜尋「{keyword}」: 找到 {len(board_posts)} 篇")
                except Exception as e:
                    print(f"[PTT] 搜尋 /{board} 出錯: {e}")

        return posts

    def get_post_with_comments(
        self, post_url_or_id: str, max_comments: int = 200
    ) -> Post:
        """
        Fetch a PTT post with its push/comment list.

        Args:
            post_url_or_id: Full URL like https://www.ptt.cc/bbs/Gossiping/M.xxx.html
                            or just the path /bbs/Gossiping/M.xxx.html
        """
        if post_url_or_id.startswith("http"):
            url = post_url_or_id
        else:
            url = f"{self.BASE_URL}{post_url_or_id}"

        resp = self._get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_post_page(soup, url, max_comments)

    def get_board_listing(
        self, board: str, max_pages: int = 3
    ) -> list[Post]:
        """
        Scrape recent posts from a board listing (no keyword filter).

        Args:
            board: PTT board name, e.g. "Gossiping"
            max_pages: Number of listing pages to crawl
        """
        posts = []
        url = f"{self.BASE_URL}/bbs/{board}/index.html"

        for page in range(max_pages):
            try:
                resp = self._get(url)
                soup = BeautifulSoup(resp.text, "html.parser")
                page_posts = self._parse_listing(soup, board)
                posts.extend(page_posts)
                print(f"[PTT] /{board} 第{page+1}頁: {len(page_posts)} 篇")

                # Navigate to previous page
                prev_link = soup.select_one("a.btn.wide:contains('上頁')")
                if prev_link and prev_link.get("href"):
                    url = self.BASE_URL + prev_link["href"]
                else:
                    break
            except Exception as e:
                print(f"[PTT] 爬 /{board} 第{page+1}頁出錯: {e}")
                break

        return posts

    # ── HTML parsers ──────────────────────────────────────────────

    def _parse_listing(self, soup: BeautifulSoup, board: str) -> list[Post]:
        """Parse a board listing page and return Post stubs (no comments)."""
        posts = []
        for entry in soup.select("div.r-ent"):
            try:
                title_tag = entry.select_one("div.title a")
                if not title_tag:
                    # Deleted post — skip
                    continue

                title = title_tag.get_text(strip=True)
                href = title_tag["href"]  # e.g. /bbs/Gossiping/M.xxx.html
                url = self.BASE_URL + href

                # Author
                author_tag = entry.select_one("div.author")
                author = author_tag.get_text(strip=True) if author_tag else ""

                # Push count (could be "爆", "XX", or a number)
                push_tag = entry.select_one("div.nrec span")
                push_count = 0
                if push_tag:
                    raw = push_tag.get_text(strip=True)
                    if raw == "爆":
                        push_count = 100
                    elif raw.startswith("X"):
                        push_count = -10
                    else:
                        try:
                            push_count = int(raw)
                        except ValueError:
                            pass

                # Date (format: "3/27" — no year)
                date_tag = entry.select_one("div.date")
                date_str = date_tag.get_text(strip=True) if date_tag else ""
                created_at = self._parse_listing_date(date_str)

                # Use URL path as ID
                post_id = href.replace("/bbs/", "").replace(".html", "")

                posts.append(Post(
                    id=post_id,
                    platform="ptt",
                    title=title,
                    body="",  # filled in by get_post_with_comments
                    author=author,
                    score=push_count,
                    num_comments=0,
                    created_at=created_at,
                    url=url,
                    subreddit=board,
                ))
            except Exception as e:
                print(f"[PTT] 解析文章列表項目失敗: {e}")
                continue

        return posts

    def _parse_post_page(
        self, soup: BeautifulSoup, url: str, max_comments: int
    ) -> Post:
        """Parse a full PTT article page."""
        main = soup.select_one("div#main-content")
        if not main:
            raise ValueError(f"找不到 main-content: {url}")

        # ── Meta fields ──
        meta_values = main.select("span.article-meta-value")
        author = meta_values[0].get_text(strip=True) if len(meta_values) > 0 else ""
        board = meta_values[1].get_text(strip=True) if len(meta_values) > 1 else ""
        title = meta_values[2].get_text(strip=True) if len(meta_values) > 2 else ""
        date_str = meta_values[3].get_text(strip=True) if len(meta_values) > 3 else ""
        created_at = self._parse_article_date(date_str)

        # ── Body: clone main-content, remove push divs and meta header ──
        body_soup = BeautifulSoup(str(main), "html.parser")
        body_main = body_soup.select_one("div#main-content")

        for tag in body_main.select("div.push"):
            tag.decompose()
        for tag in body_main.select("div.article-metaline"):
            tag.decompose()
        for tag in body_main.select("div.article-metaline-right"):
            tag.decompose()
        # Remove trailing separator lines (--\n)
        body_text = body_main.get_text(separator="\n").strip()
        # Strip the trailing "-- \n※" footer PTT appends
        if "\n--\n" in body_text:
            body_text = body_text[:body_text.rfind("\n--\n")].strip()

        # ── Push comments ──
        comments = []
        push_divs = main.select("div.push")
        for i, div in enumerate(push_divs[:max_comments]):
            try:
                push_tag_el = div.select_one("span.push-tag")
                user_el = div.select_one("span.push-userid")
                content_el = div.select_one("span.push-content")
                ipdatetime_el = div.select_one("span.push-ipdatetime")

                tag_text = push_tag_el.get_text(strip=True) if push_tag_el else "→"
                user = user_el.get_text(strip=True) if user_el else ""
                # push-content starts with ": " — strip it
                content = content_el.get_text(strip=True).lstrip(":").strip() if content_el else ""
                dt_raw = ipdatetime_el.get_text(strip=True) if ipdatetime_el else ""

                # Score: 推=+1, 噓=-1, →=0
                score = {"推": 1, "噓": -1, "→": 0}.get(tag_text, 0)

                comments.append(Comment(
                    id=f"{url}#{i}",
                    platform="ptt",
                    author=user,
                    body=content,
                    score=score,
                    created_at=created_at,  # push doesn't have year, reuse post date
                    url=url,
                    metadata={"push_tag": tag_text, "ipdatetime": dt_raw},
                ))
            except Exception as e:
                print(f"[PTT] 解析推文失敗: {e}")
                continue

        post_id = url.replace(self.BASE_URL + "/bbs/", "").replace(".html", "")

        return Post(
            id=post_id,
            platform="ptt",
            title=title,
            body=body_text,
            author=author,
            score=sum(1 for c in comments if c.metadata.get("push_tag") == "推")
                  - sum(1 for c in comments if c.metadata.get("push_tag") == "噓"),
            num_comments=len(comments),
            created_at=created_at,
            url=url,
            subreddit=board,
            comments=comments,
        )

    # ── Date helpers ──────────────────────────────────────────────

    def _parse_listing_date(self, date_str: str) -> datetime:
        """Parse listing date like '3/27' → datetime (current year assumed)."""
        try:
            now = datetime.now()
            month, day = [int(x) for x in date_str.strip().split("/")]
            return datetime(now.year, month, day, tzinfo=timezone.utc)
        except Exception:
            return datetime.now(tz=timezone.utc)

    def _parse_article_date(self, date_str: str) -> datetime:
        """Parse article date like 'Fri Mar 27 12:34:56 2026'."""
        try:
            return datetime.strptime(date_str.strip(), "%a %b %d %H:%M:%S %Y").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            return datetime.now(tz=timezone.utc)
