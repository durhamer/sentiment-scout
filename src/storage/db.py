"""SQLite storage for posts, comments, and analysis results."""

import json
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Text,
    DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


class PostRecord(Base):
    __tablename__ = "posts"

    id = Column(String, primary_key=True)
    platform = Column(String, index=True)
    title = Column(Text)
    body = Column(Text)
    author = Column(String)
    score = Column(Integer)
    num_comments = Column(Integer)
    created_at = Column(DateTime)
    url = Column(String)
    subreddit = Column(String, nullable=True)
    collected_at = Column(DateTime, default=datetime.utcnow)

    # Sentiment analysis results
    sentiment_label = Column(String, nullable=True)
    sentiment_polarity = Column(Float, nullable=True)
    positive_pct = Column(Float, nullable=True)
    negative_pct = Column(Float, nullable=True)
    neutral_pct = Column(Float, nullable=True)
    weighted_polarity = Column(Float, nullable=True)

    comments = relationship("CommentRecord", back_populates="post")
    drafts = relationship("DraftRecord", back_populates="post")


class CommentRecord(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True)
    post_id = Column(String, ForeignKey("posts.id"), index=True)
    platform = Column(String)
    author = Column(String)
    body = Column(Text)
    score = Column(Integer)
    created_at = Column(DateTime)
    parent_id = Column(String, nullable=True)
    url = Column(String, nullable=True)

    sentiment_label = Column(String, nullable=True)
    sentiment_polarity = Column(Float, nullable=True)

    post = relationship("PostRecord", back_populates="comments")


class DraftRecord(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(String, ForeignKey("posts.id"), index=True)
    target_comment_id = Column(String, nullable=True)
    stance_id = Column(String)
    draft_text = Column(Text)
    tone = Column(String)
    language = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    used = Column(Boolean, default=False)  # Track if user used this draft

    post = relationship("PostRecord", back_populates="drafts")


class Storage:
    """Manage SQLite database for Sentiment Scout."""

    def __init__(self, db_path: str = "data/sentinel.db"):
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def save_post(self, post, analysis: dict | None = None):
        """Save a post and its comments to the database."""
        session = self.Session()
        try:
            record = PostRecord(
                id=post.id,
                platform=post.platform,
                title=post.title,
                body=post.body,
                author=post.author,
                score=post.score,
                num_comments=post.num_comments,
                created_at=post.created_at,
                url=post.url,
                subreddit=post.subreddit,
            )

            if analysis:
                dist = analysis.get("distribution", {})
                record.sentiment_label = analysis["post_sentiment"].label.value
                record.sentiment_polarity = analysis["post_sentiment"].polarity
                record.positive_pct = dist.get("positive_pct")
                record.negative_pct = dist.get("negative_pct")
                record.neutral_pct = dist.get("neutral_pct")
                record.weighted_polarity = analysis.get("weighted_avg_polarity")

            session.merge(record)

            for comment in post.comments:
                c_record = CommentRecord(
                    id=comment.id,
                    post_id=post.id,
                    platform=comment.platform,
                    author=comment.author,
                    body=comment.body,
                    score=comment.score,
                    created_at=comment.created_at,
                    parent_id=comment.parent_id,
                    url=comment.url,
                )
                session.merge(c_record)

            session.commit()
        finally:
            session.close()

    def save_draft(self, draft, post_id: str, comment_id: str | None = None):
        """Save a generated draft."""
        session = self.Session()
        try:
            record = DraftRecord(
                post_id=post_id,
                target_comment_id=comment_id,
                stance_id=draft.stance_id,
                draft_text=draft.draft_text,
                tone=draft.tone,
                language=draft.language,
            )
            session.add(record)
            session.commit()
            return record.id
        finally:
            session.close()

    def get_recent_posts(self, platform: str | None = None, limit: int = 50):
        """Get recently collected posts."""
        session = self.Session()
        try:
            query = session.query(PostRecord).order_by(PostRecord.collected_at.desc())
            if platform:
                query = query.filter(PostRecord.platform == platform)
            return query.limit(limit).all()
        finally:
            session.close()

    def get_post_comments(self, post_id: str):
        """Get all comments for a post."""
        session = self.Session()
        try:
            return (
                session.query(CommentRecord)
                .filter(CommentRecord.post_id == post_id)
                .order_by(CommentRecord.score.desc())
                .all()
            )
        finally:
            session.close()
