"""Base collector interface for all platform collectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Comment:
    """A single comment/reply in a discussion."""
    id: str
    platform: str
    author: str
    body: str
    score: int
    created_at: datetime
    parent_id: Optional[str] = None
    url: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Post:
    """A discussion post from any platform."""
    id: str
    platform: str
    title: str
    body: str
    author: str
    score: int
    num_comments: int
    created_at: datetime
    url: str
    subreddit: Optional[str] = None  # Reddit-specific, but useful as category
    comments: list[Comment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class BaseCollector(ABC):
    """Abstract base class for platform collectors."""

    platform_name: str = "unknown"

    @abstractmethod
    def search(self, keywords: list[str], **kwargs) -> list[Post]:
        """Search for posts matching keywords."""
        ...

    @abstractmethod
    def get_post_with_comments(self, post_id: str, max_comments: int = 50) -> Post:
        """Fetch a single post with its comment tree."""
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} platform={self.platform_name}>"
