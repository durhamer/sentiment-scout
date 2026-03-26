"""Sentiment analysis for collected posts and comments."""

from dataclasses import dataclass
from enum import Enum

from textblob import TextBlob

from src.collectors.base import Post, Comment


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass
class SentimentResult:
    """Result of sentiment analysis on a piece of text."""
    text_preview: str       # First 100 chars
    label: SentimentLabel
    polarity: float         # -1.0 to 1.0
    subjectivity: float     # 0.0 to 1.0

    @property
    def is_opinionated(self) -> bool:
        return self.subjectivity > 0.5


class SentimentAnalyzer:
    """Analyze sentiment of text using TextBlob (lightweight, no GPU needed)."""

    def analyze_text(self, text: str) -> SentimentResult:
        """Analyze a single piece of text."""
        if not text.strip():
            return SentimentResult(
                text_preview="",
                label=SentimentLabel.NEUTRAL,
                polarity=0.0,
                subjectivity=0.0,
            )

        blob = TextBlob(text)
        polarity = blob.sentiment.polarity
        subjectivity = blob.sentiment.subjectivity

        if polarity > 0.1:
            label = SentimentLabel.POSITIVE
        elif polarity < -0.1:
            label = SentimentLabel.NEGATIVE
        else:
            label = SentimentLabel.NEUTRAL

        return SentimentResult(
            text_preview=text[:100],
            label=label,
            polarity=round(polarity, 3),
            subjectivity=round(subjectivity, 3),
        )

    def analyze_post(self, post: Post) -> dict:
        """
        Analyze a post and all its comments.
        Returns a summary dict with overall sentiment distribution.
        """
        # Analyze post body
        post_sentiment = self.analyze_text(f"{post.title} {post.body}")

        # Analyze each comment
        comment_sentiments = []
        for comment in post.comments:
            result = self.analyze_text(comment.body)
            comment_sentiments.append({
                "comment_id": comment.id,
                "author": comment.author,
                "score": comment.score,
                "sentiment": result,
            })

        # Compute distribution
        total = len(comment_sentiments) or 1
        dist = {
            SentimentLabel.POSITIVE: 0,
            SentimentLabel.NEGATIVE: 0,
            SentimentLabel.NEUTRAL: 0,
        }
        weighted_polarity = 0.0

        for cs in comment_sentiments:
            dist[cs["sentiment"].label] += 1
            # Weight by upvotes (min 1 to avoid zero)
            weight = max(cs["score"], 1)
            weighted_polarity += cs["sentiment"].polarity * weight

        total_weight = sum(max(cs["score"], 1) for cs in comment_sentiments) or 1

        return {
            "post_id": post.id,
            "post_title": post.title,
            "post_url": post.url,
            "post_sentiment": post_sentiment,
            "num_comments_analyzed": len(comment_sentiments),
            "distribution": {
                "positive": dist[SentimentLabel.POSITIVE],
                "negative": dist[SentimentLabel.NEGATIVE],
                "neutral": dist[SentimentLabel.NEUTRAL],
                "positive_pct": round(dist[SentimentLabel.POSITIVE] / total * 100, 1),
                "negative_pct": round(dist[SentimentLabel.NEGATIVE] / total * 100, 1),
                "neutral_pct": round(dist[SentimentLabel.NEUTRAL] / total * 100, 1),
            },
            "weighted_avg_polarity": round(weighted_polarity / total_weight, 3),
            "comment_details": comment_sentiments,
            # Top positive and negative comments (by score)
            "top_positive": sorted(
                [c for c in comment_sentiments if c["sentiment"].label == SentimentLabel.POSITIVE],
                key=lambda x: x["score"],
                reverse=True,
            )[:3],
            "top_negative": sorted(
                [c for c in comment_sentiments if c["sentiment"].label == SentimentLabel.NEGATIVE],
                key=lambda x: x["score"],
                reverse=True,
            )[:3],
        }
