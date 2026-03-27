"""
Threads collector smoke test.

Usage:
    python scripts/test_threads.py                        # search "AI"
    python scripts/test_threads.py --keyword "台積電"
    python scripts/test_threads.py --keyword "AI" --max-posts 5 --max-replies 10
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the Threads API collector")
    parser.add_argument("--keyword", default="AI", help="Search keyword")
    parser.add_argument("--max-posts", type=int, default=10, help="Max posts to fetch")
    parser.add_argument("--max-replies", type=int, default=20, help="Max replies per post")
    return parser.parse_args()


def step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {n}:[/] [bold]{title}[/]")


def main() -> None:
    args = parse_args()

    console.print(Panel.fit(
        "[bold white]Sentiment Scout — Threads Pipeline Test[/]\n"
        "[dim]Threads Graph API → Post Search → Reply Fetch[/]",
        border_style="cyan",
    ))

    # ── Step 1: Init collector ─────────────────────────────────────
    step(1, "初始化 ThreadsCollector")

    try:
        from src.collectors.threads import ThreadsCollector
        collector = ThreadsCollector()
        console.print("  [green]✓[/] ThreadsCollector 初始化成功")
    except ValueError as e:
        console.print(f"  [red]✗ 初始化失敗：{e}[/]")
        console.print(
            "\n  [yellow]請確認 .env 裡已設定：[/]\n"
            "    THREADS_ACCESS_TOKEN=...\n"
            "    THREADS_USER_ID=..."
        )
        sys.exit(1)

    # ── Step 2: Search ─────────────────────────────────────────────
    step(2, f"搜尋關鍵字：「{args.keyword}」（max {args.max_posts} 篇）")
    console.print(
        "  [dim]注意：threads_keyword_search 尚未通過 App Review 前，"
        "搜尋結果只會包含自己帳號的貼文。[/]"
    )

    with console.status("搜尋中…"):
        try:
            posts = collector.search(keywords=[args.keyword], max_posts=args.max_posts)
        except Exception as e:
            # threads_keyword_search returns 500 before App Review is approved
            if "App Review" in str(e):
                console.print(f"\n  [yellow]⚠ {e}[/]")
                console.print(
                    "\n  [dim]這是預期行為。等 Meta 審核通過後，"
                    "就能搜尋所有公開貼文。[/]\n"
                    "  [dim]屆時 collector 架構完全相容，不需再修改程式碼。[/]"
                )
                console.print("\n[dim]Threads pipeline test 完成（等待 App Review）。[/]\n")
                sys.exit(0)
            console.print(f"  [red]✗ 搜尋失敗：{e}[/]")
            sys.exit(1)

    if not posts:
        console.print(
            "\n  [yellow]搜尋結果為空。[/]\n"
            "  這是預期行為——threads_keyword_search 在通過 App Review 之前，\n"
            "  只能搜尋自己帳號的貼文。如果你的帳號沒有包含此關鍵字的貼文，\n"
            "  結果就會是空的。\n\n"
            "  [dim]等 App Review 通過後，就能搜尋所有公開貼文。[/]"
        )
        console.print("\n[dim]Threads pipeline test 完成（無結果可供進一步測試）。[/]\n")
        sys.exit(0)

    tbl = Table(
        title=f"找到 {len(posts)} 篇貼文",
        box=box.SIMPLE,
    )
    tbl.add_column("#", width=3, justify="right")
    tbl.add_column("作者", width=20, style="cyan")
    tbl.add_column("時間", width=20)
    tbl.add_column("愛心", width=6, justify="right", style="green")
    tbl.add_column("內容預覽", max_width=60)

    for i, p in enumerate(posts, 1):
        preview = p.body.replace("\n", " ")[:60] if p.body else "[empty]"
        tbl.add_row(
            str(i),
            p.author or "-",
            p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "-",
            str(p.score),
            preview,
        )

    console.print(tbl)

    # ── Step 3: Fetch replies for top post ─────────────────────────
    top_post = posts[0]
    step(3, f"抓取第一篇貼文的回覆（max {args.max_replies} 則）")
    console.print(f"  Post ID: [yellow]{top_post.id}[/]")
    console.print(f"  URL: [yellow]{top_post.url}[/]")

    with console.status("抓取回覆中…"):
        try:
            full_post = collector.get_post_with_comments(
                top_post.id, max_comments=args.max_replies
            )
        except Exception as e:
            console.print(f"  [red]✗ 抓取回覆失敗：{e}[/]")
            sys.exit(1)

    n_replies = len(full_post.comments)
    console.print(f"  [green]✓[/] 取得 {n_replies} 則回覆")

    if n_replies > 0:
        console.print()
        for i, c in enumerate(full_post.comments[:5], 1):
            preview = c.body.replace("\n", " ")[:70] if c.body else "[empty]"
            console.print(
                f"  [dim]{i}.[/] [@{c.author or '?'}] "
                f"[green]♥{c.score}[/]  {preview}"
            )
        if n_replies > 5:
            console.print(f"  [dim]... 還有 {n_replies - 5} 則回覆[/]")

    # ── Summary ────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[bold green]搜尋：{len(posts)} 篇貼文  |  "
        f"第一篇回覆：{n_replies} 則[/]\n"
        f"[dim]Threads collector 架構正常，等 App Review 通過後即可搜尋公開貼文。[/]",
        border_style="green",
    ))
    console.print("\n[dim]Threads pipeline test 完成。[/]\n")


if __name__ == "__main__":
    main()
