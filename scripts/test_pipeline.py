"""
End-to-end pipeline smoke test.

Usage:
    python scripts/test_pipeline.py                   # use settings.yaml defaults
    python scripts/test_pipeline.py --keywords "AI" "machine learning"
    python scripts/test_pipeline.py --subreddit technology --max-posts 10
"""

import argparse
import sys
from pathlib import Path

# Make sure the project root is on sys.path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.collectors.reddit import RedditCollector
from src.analyzers.sentiment import SentimentAnalyzer, SentimentLabel

console = Console()


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_args(config: dict) -> argparse.Namespace:
    mon = config["monitoring"]
    reddit_cfg = mon["reddit"]

    parser = argparse.ArgumentParser(description="Test the full sentiment pipeline")
    parser.add_argument(
        "--keywords", nargs="+",
        default=mon["keywords"],
        help="Search keywords (space-separated)",
    )
    parser.add_argument(
        "--subreddit", nargs="+",
        default=reddit_cfg["subreddits"],
        help="Subreddit(s) to search",
    )
    parser.add_argument(
        "--sort",
        default=reddit_cfg["sort_by"],
        choices=["relevance", "hot", "top", "new", "comments"],
    )
    parser.add_argument(
        "--time-filter",
        default=reddit_cfg["time_filter"],
        choices=["hour", "day", "week", "month", "year", "all"],
    )
    parser.add_argument(
        "--max-posts", type=int,
        default=reddit_cfg["max_posts_per_sub"],
    )
    parser.add_argument(
        "--max-comments", type=int,
        default=reddit_cfg.get("max_comments_per_post", 50),
    )
    return parser.parse_args()


# ── Step display helpers ───────────────────────────────────────────

def step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {n}:[/] [bold]{title}[/]")


def sentiment_color(label: SentimentLabel) -> str:
    return {"positive": "green", "negative": "red", "neutral": "yellow"}[label.value]


def bar(count: int, total: int, width: int = 20) -> str:
    filled = round(count / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)


# ── Main pipeline ─────────────────────────────────────────────────

def main() -> None:
    config = load_config()
    args = parse_args(config)

    console.print(Panel.fit(
        "[bold white]Sentiment Scout — Pipeline Test[/]\n"
        "[dim]Reddit → Sentiment Analysis → Terminal Report[/]",
        border_style="cyan",
    ))

    # ── Step 1: Search Reddit ──────────────────────────────────────
    step(1, "Searching Reddit")
    console.print(f"  Keywords : [yellow]{args.keywords}[/]")
    console.print(f"  Subreddits: [yellow]{args.subreddit}[/]")
    console.print(f"  Sort={args.sort}  Time={args.time_filter}  Max={args.max_posts}\n")

    collector = RedditCollector()
    posts = collector.search(
        keywords=args.keywords,
        subreddits=args.subreddit,
        sort=args.sort,
        time_filter=args.time_filter,
        max_posts=args.max_posts,
    )

    if not posts:
        console.print("[red]No posts found. Try different keywords or subreddits.[/]")
        sys.exit(1)

    # Sort by score, pick top post
    posts_sorted = sorted(posts, key=lambda p: p.score, reverse=True)

    tbl = Table(title=f"Found {len(posts)} posts (top 5 shown)", box=box.SIMPLE)
    tbl.add_column("Rank", width=4, justify="right")
    tbl.add_column("Score", width=6, justify="right", style="green")
    tbl.add_column("Sub", width=15, style="cyan")
    tbl.add_column("Title", max_width=60)

    for i, p in enumerate(posts_sorted[:5], 1):
        tbl.add_row(str(i), str(p.score), p.subreddit, p.title)

    console.print(tbl)

    top_post = posts_sorted[0]
    console.print(
        f"\n[bold]→ Selecting top post:[/] [green]{top_post.title[:80]}[/]\n"
        f"  [dim]r/{top_post.subreddit} · score {top_post.score} · "
        f"{top_post.num_comments} comments[/]"
    )

    # ── Step 2: Fetch comments ─────────────────────────────────────
    step(2, "Fetching comments")
    console.print(f"  Post ID : [yellow]{top_post.id}[/]")
    console.print(f"  Max comments: [yellow]{args.max_comments}[/]")

    with console.status("Fetching post with comments…"):
        post_with_comments = collector.get_post_with_comments(
            top_post.id, max_comments=args.max_comments
        )

    n_comments = len(post_with_comments.comments)
    console.print(f"  [green]✓[/] Retrieved {n_comments} comments")

    if n_comments == 0:
        console.print("[yellow]  No comments retrieved — skipping analysis.[/]")
        sys.exit(0)

    # ── Step 3: Sentiment analysis ─────────────────────────────────
    step(3, "Running sentiment analysis")

    analyzer = SentimentAnalyzer()
    with console.status("Analysing…"):
        result = analyzer.analyze_post(post_with_comments)

    dist = result["distribution"]
    total = result["num_comments_analyzed"] or 1

    console.print(f"  [green]✓[/] Analysed {result['num_comments_analyzed']} comments")

    # ── Step 4: Print summary ──────────────────────────────────────
    step(4, "Sentiment summary")

    # Post-level
    ps = result["post_sentiment"]
    ps_color = sentiment_color(ps.label)
    console.print(f"\n  [bold]Post itself:[/] [{ps_color}]{ps.label.value.upper()}[/]  "
                  f"polarity={ps.polarity:+.3f}  subjectivity={ps.subjectivity:.3f}")
    console.print(f"  [dim]{post_with_comments.url}[/]")

    # Distribution bar chart
    console.print()
    for label, color in [
        (SentimentLabel.POSITIVE, "green"),
        (SentimentLabel.NEUTRAL,  "yellow"),
        (SentimentLabel.NEGATIVE, "red"),
    ]:
        count = dist[label.value]
        pct   = dist[f"{label.value}_pct"]
        b     = bar(count, total)
        console.print(
            f"  [{color}]{label.value.capitalize():8}[/]  "
            f"[{color}]{b}[/]  {count:3d} ({pct:5.1f}%)"
        )

    wavg = result["weighted_avg_polarity"]
    wavg_color = "green" if wavg > 0.05 else ("red" if wavg < -0.05 else "yellow")
    console.print(f"\n  Weighted avg polarity: [{wavg_color}]{wavg:+.3f}[/]")

    # Representative comments
    def show_top_comments(label: str, items: list, color: str) -> None:
        if not items:
            return
        console.print(f"\n  [bold {color}]Top {label} comments:[/]")
        for i, c in enumerate(items, 1):
            preview = c["comment"].body[:120].replace("\n", " ")
            console.print(
                f"    {i}. [dim](score {c['score']}, "
                f"polarity {c['sentiment'].polarity:+.3f})[/]\n"
                f"       {preview}"
            )

    # Rebuild comment detail with body for display
    comment_map = {c.id: c for c in post_with_comments.comments}

    enriched_pos = []
    for item in result["top_positive"]:
        cid = item["comment_id"]
        if cid in comment_map:
            enriched_pos.append({**item, "comment": comment_map[cid]})

    enriched_neg = []
    for item in result["top_negative"]:
        cid = item["comment_id"]
        if cid in comment_map:
            enriched_neg.append({**item, "comment": comment_map[cid]})

    show_top_comments("positive", enriched_pos, "green")
    show_top_comments("negative", enriched_neg, "red")

    # Final verdict
    console.print()
    if dist["positive_pct"] >= 50:
        verdict = "[bold green]Overall: Positive sentiment dominates[/]"
    elif dist["negative_pct"] >= 50:
        verdict = "[bold red]Overall: Negative sentiment dominates[/]"
    elif dist["neutral_pct"] >= 50:
        verdict = "[bold yellow]Overall: Mostly neutral discussion[/]"
    else:
        verdict = "[bold white]Overall: Mixed sentiment[/]"

    console.print(Panel(verdict, border_style="dim"))
    console.print("\n[dim]Pipeline test complete. All modules working correctly.[/]\n")


if __name__ == "__main__":
    main()
