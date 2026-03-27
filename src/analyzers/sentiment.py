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


class PttSentimentResult:
    """Sentiment result computed directly from PTT 推/噓/→ tags."""

    def __init__(self, push: int, boo: int, arrow: int):
        self.push = push
        self.boo = boo
        self.arrow = arrow
        total = push + boo + arrow or 1
        self.positive_pct = round(push / total * 100, 1)
        self.negative_pct = round(boo / total * 100, 1)
        self.neutral_pct = round(arrow / total * 100, 1)
        # Normalised polarity: (推 - 噓) / total, range [-1, 1]
        self.polarity = round((push - boo) / total, 3)

        if self.polarity > 0.1:
            self.label = SentimentLabel.POSITIVE
        elif self.polarity < -0.1:
            self.label = SentimentLabel.NEGATIVE
        else:
            self.label = SentimentLabel.NEUTRAL


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

    def analyze_ptt_post(self, post: Post) -> dict:
        """
        Analyze a PTT post using push/boo/arrow tags instead of NLP.

        PTT comments carry explicit sentiment via push-tag:
          推 → positive, 噓 → negative, → → neutral

        Returns the same dict structure as analyze_post() for dashboard compatibility.
        """
        push_comments = []
        boo_comments = []
        arrow_comments = []

        for comment in post.comments:
            tag = comment.metadata.get("push_tag", "→")
            if tag == "推":
                push_comments.append(comment)
            elif tag == "噓":
                boo_comments.append(comment)
            else:
                arrow_comments.append(comment)

        result = PttSentimentResult(
            push=len(push_comments),
            boo=len(boo_comments),
            arrow=len(arrow_comments),
        )

        total = len(post.comments) or 1

        # Build comment detail list (keeps dashboard compatibility)
        comment_details = []
        for comment in post.comments:
            tag = comment.metadata.get("push_tag", "→")
            if tag == "推":
                label = SentimentLabel.POSITIVE
                polarity = 1.0
            elif tag == "噓":
                label = SentimentLabel.NEGATIVE
                polarity = -1.0
            else:
                label = SentimentLabel.NEUTRAL
                polarity = 0.0

            sent = SentimentResult(
                text_preview=comment.body[:100],
                label=label,
                polarity=polarity,
                subjectivity=1.0,  # PTT push tags are explicit opinions
            )
            comment_details.append({
                "comment_id": comment.id,
                "author": comment.author,
                "score": comment.score,
                "sentiment": sent,
                "push_tag": tag,
            })

        top_positive = sorted(
            [c for c in comment_details if c["sentiment"].label == SentimentLabel.POSITIVE],
            key=lambda x: x["score"],
            reverse=True,
        )[:3]
        top_negative = sorted(
            [c for c in comment_details if c["sentiment"].label == SentimentLabel.NEGATIVE],
            key=lambda x: x["score"],
            reverse=True,
        )[:3]

        return {
            "post_id": post.id,
            "post_title": post.title,
            "post_url": post.url,
            "post_sentiment": SentimentResult(
                text_preview=post.title[:100],
                label=result.label,
                polarity=result.polarity,
                subjectivity=1.0,
            ),
            "num_comments_analyzed": len(post.comments),
            "distribution": {
                "positive": result.push,
                "negative": result.boo,
                "neutral": result.arrow,
                "positive_pct": result.positive_pct,
                "negative_pct": result.negative_pct,
                "neutral_pct": result.neutral_pct,
            },
            "weighted_avg_polarity": result.polarity,
            "comment_details": comment_details,
            "top_positive": top_positive,
            "top_negative": top_negative,
            # PTT-specific extras
            "push_summary": {
                "推": result.push,
                "噓": result.boo,
                "→": result.arrow,
            },
        }
