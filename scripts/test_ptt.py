"""
PTT collector smoke test.

Usage:
    python scripts/test_ptt.py                      # search "AI" in Gossiping
    python scripts/test_ptt.py --keyword "台積電" --board Stock
    python scripts/test_ptt.py --keyword "AI" --board Gossiping --max-posts 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.collectors.ptt import PttCollector
from src.analyzers.sentiment import SentimentAnalyzer

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the PTT scraper pipeline")
    parser.add_argument("--keyword", default="AI", help="Search keyword")
    parser.add_argument("--board", default="Gossiping", help="PTT board name")
    parser.add_argument("--max-posts", type=int, default=10, help="Max posts to fetch from search")
    parser.add_argument("--max-comments", type=int, default=200, help="Max push/comments per post")
    return parser.parse_args()


def bar(count: int, total: int, width: int = 20) -> str:
    filled = round(count / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {n}:[/] [bold]{title}[/]")


def main() -> None:
    args = parse_args()

    console.print(Panel.fit(
        "[bold white]Sentiment Scout — PTT Pipeline Test[/]\n"
        "[dim]PTT Web → Push/Boo Analysis → Terminal Report[/]",
        border_style="cyan",
    ))

    # ── Step 1: Search ─────────────────────────────────────────────
    step(1, f"Searching PTT /{args.board} for「{args.keyword}」")

    collector = PttCollector()
    posts = collector.search(
        keywords=[args.keyword],
        boards=[args.board],
        max_posts=args.max_posts,
    )

    if not posts:
        console.print("[red]沒有找到文章。請確認板名正確，或換個關鍵字。[/]")
        sys.exit(1)

    # Sort by score (push count) descending
    posts_sorted = sorted(posts, key=lambda p: p.score, reverse=True)

    tbl = Table(title=f"找到 {len(posts)} 篇文章（依推文數排序，顯示前 10）", box=box.SIMPLE)
    tbl.add_column("排名", width=4, justify="right")
    tbl.add_column("推文", width=6, justify="right", style="green")
    tbl.add_column("作者", width=12, style="cyan")
    tbl.add_column("標題", max_width=60)

    for i, p in enumerate(posts_sorted[:10], 1):
        tbl.add_row(str(i), str(p.score), p.author, p.title)

    console.print(tbl)

    top_post = posts_sorted[0]
    console.print(
        f"\n[bold]→ 選取最高推文文章:[/] [green]{top_post.title[:80]}[/]\n"
        f"  [dim]/{args.board} · 推文數 {top_post.score} · URL: {top_post.url}[/]"
    )

    # ── Step 2: Fetch full post with comments ──────────────────────
    step(2, "抓取文章內容與推文")
    console.print(f"  URL: [yellow]{top_post.url}[/]")
    console.print(f"  Max 推文數: [yellow]{args.max_comments}[/]")

    with console.status("爬取中…"):
        full_post = collector.get_post_with_comments(
            top_post.url, max_comments=args.max_comments
        )

    n_comments = len(full_post.comments)
    console.print(f"  [green]✓[/] 取得 {n_comments} 則推文")

    if n_comments == 0:
        console.print("[yellow]  沒有推文 — 跳過分析。[/]")
        sys.exit(0)

    # ── Step 3: PTT sentiment analysis ────────────────────────────
    step(3, "推噓情緒分析（不用 NLP，直接計算推/噓/→）")

    analyzer = SentimentAnalyzer()
    with console.status("分析中…"):
        result = analyzer.analyze_ptt_post(full_post)

    push_summary = result["push_summary"]
    dist = result["distribution"]
    total = result["num_comments_analyzed"] or 1

    console.print(f"  [green]✓[/] 分析 {total} 則推文完成")

    # ── Step 4: Print summary ──────────────────────────────────────
    step(4, "推噓統計摘要")

    console.print(
        f"\n  [bold]文章標題:[/] {full_post.title}\n"
        f"  [dim]{full_post.url}[/]\n"
        f"  作者: {full_post.author}"
    )

    console.print()
    label_color = {
        "positive": "green",
        "negative": "red",
        "neutral": "yellow",
    }
    overall_label = result["post_sentiment"].label.value
    overall_color = label_color[overall_label]
    console.print(
        f"  [bold]整體風向:[/] [{overall_color}]{overall_label.upper()}[/]  "
        f"polarity={result['weighted_avg_polarity']:+.3f}"
    )

    console.print()
    rows = [
        ("推 (正面)", push_summary["推"], dist["positive_pct"], "green"),
        ("→ (中性)", push_summary["→"], dist["neutral_pct"], "yellow"),
        ("噓 (負面)", push_summary["噓"], dist["negative_pct"], "red"),
    ]
    for label, count, pct, color in rows:
        b = bar(count, total)
        console.print(
            f"  [{color}]{label:10}[/]  [{color}]{b}[/]  {count:4d} ({pct:5.1f}%)"
        )

    # ── Step 5: Representative pushes ─────────────────────────────
    step(5, "代表性推文")

    def show_comments(title: str, items: list, color: str) -> None:
        if not items:
            return
        console.print(f"\n  [bold {color}]{title}[/]")
        for i, c in enumerate(items[:3], 1):
            tag = c.get("push_tag", "→")
            preview = c["sentiment"].text_preview[:80].replace("\n", " ")
            console.print(f"    {i}. [{color}]{tag}[/] [{c['author']}] {preview}")

    # Rebuild with author info from full_post.comments
    comment_map = {c.id: c for c in full_post.comments}
    enriched_details = []
    for item in result["comment_details"]:
        cid = item["comment_id"]
        if cid in comment_map:
            enriched_details.append({**item, "author": comment_map[cid].author})
        else:
            enriched_details.append(item)

    top_pos = [c for c in enriched_details if c["push_tag"] == "推"][:3]
    top_neg = [c for c in enriched_details if c["push_tag"] == "噓"][:3]

    show_comments("最新「推」留言：", top_pos, "green")
    show_comments("最新「噓」留言：", top_neg, "red")

    # Final verdict
    console.print()
    if dist["positive_pct"] >= 50:
        verdict = "[bold green]整體：正面（推文）主導[/]"
    elif dist["negative_pct"] >= 50:
        verdict = "[bold red]整體：負面（噓文）主導[/]"
    elif dist["neutral_pct"] >= 50:
        verdict = "[bold yellow]整體：以箭頭（中性）為主[/]"
    else:
        verdict = "[bold white]整體：推噓混雜[/]"

    console.print(Panel(verdict, border_style="dim"))
    console.print("\n[dim]PTT pipeline test 完成。[/]\n")


if __name__ == "__main__":
    main()
