"""Streamlit dashboard for Sentiment Scout."""

import sys
from pathlib import Path

# Ensure project root is on sys.path when running via `streamlit run src/dashboard/app.py`
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from collections import Counter

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import yaml

from src.collectors.reddit import RedditCollector
from src.analyzers.sentiment import SentimentAnalyzer
from src.drafter.reply_drafter import ReplyDrafter
from src.storage.db import Storage

# ── Page config ───────────────────────────────────────────────────

st.set_page_config(
    page_title="Sentiment Scout 🔭",
    page_icon="🔭",
    layout="wide",
)

st.title("🔭 Sentiment Scout")
st.caption("輿情監控 · 風向分析 · 論點草稿")

# ── Load config & init ────────────────────────────────────────────

@st.cache_resource
def load_config():
    with open("config/settings.yaml") as f:
        return yaml.safe_load(f)

@st.cache_resource
def init_components():
    return {
        "collector": RedditCollector(),
        "analyzer": SentimentAnalyzer(),
        "drafter": ReplyDrafter(),
        "storage": Storage(),
    }

config = load_config()
components = init_components()


def fetch_recommended_subreddits(keywords: list, top_n: int = 3) -> list:
    """Search Reddit r/all for keywords and return top subreddits by post count."""
    counter = Counter()
    headers = {"User-Agent": "sentiment-scout/0.1"}
    for keyword in keywords[:3]:
        keyword = keyword.strip()
        if not keyword:
            continue
        try:
            resp = requests.get(
                "https://www.reddit.com/r/all/search.json",
                params={"q": keyword, "sort": "relevance", "limit": 100, "t": "month"},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            for child in resp.json().get("data", {}).get("children", []):
                sub = child.get("data", {}).get("subreddit")
                if sub:
                    counter[sub] += 1
        except Exception:
            continue
    return [sub for sub, _ in counter.most_common(top_n)]


# ── Sidebar ───────────────────────────────────────────────────────

# Initialise subreddit input state once
if "subreddits_input" not in st.session_state:
    st.session_state["subreddits_input"] = "\n".join(
        config["monitoring"]["reddit"]["subreddits"]
    )

# Apply pending recommendation before the widget renders
if st.session_state.get("_pending_subreddits"):
    st.session_state["subreddits_input"] = st.session_state.pop("_pending_subreddits")

with st.sidebar:
    st.header("⚙️ 設定")

    keywords_raw = st.text_area(
        "監控關鍵字（每行一個）",
        value="\n".join(config["monitoring"]["keywords"]),
    )
    keywords = [k.strip() for k in keywords_raw.strip().split("\n") if k.strip()]

    if st.button("🎯 推薦 Subreddits", use_container_width=True):
        if not keywords:
            st.warning("請先輸入關鍵字！")
        else:
            with st.spinner("正在分析最相關的社群..."):
                recommended = fetch_recommended_subreddits(keywords)
            if recommended:
                st.session_state["_pending_subreddits"] = "\n".join(recommended)
                st.rerun()
            else:
                st.warning("找不到推薦的 subreddits，請手動輸入。")

    subreddits_raw = st.text_area(
        "Subreddits（每行一個）",
        key="subreddits_input",
    )
    subreddits = [s.strip() for s in subreddits_raw.strip().split("\n") if s.strip()]

    sort_by = st.selectbox("排序", ["hot", "new", "rising", "top", "relevance"])
    time_filter = st.selectbox("時間範圍", ["day", "week", "month", "year", "all"])
    max_posts = st.slider("每個 sub 最多幾篇", 5, 50, 25)

    fetch_button = st.button("🔍 開始搜尋", type="primary", use_container_width=True)

    st.divider()

    # Stance selector for drafting
    st.header("📝 立場設定")
    stances = components["drafter"].get_available_stances()
    stance_options = {s["name"]: s["id"] for s in stances}
    selected_stance_name = st.selectbox("選擇立場", list(stance_options.keys()))
    selected_stance_id = stance_options[selected_stance_name]

# ── Main content ──────────────────────────────────────────────────

if fetch_button:
    with st.spinner("正在從 Reddit 收集資料..."):
        posts = components["collector"].search(
            keywords=keywords,
            subreddits=subreddits,
            sort=sort_by,
            time_filter=time_filter,
            max_posts=max_posts,
        )

    if not posts:
        st.warning("沒有找到相關貼文。試試調整關鍵字或時間範圍。")
    else:
        st.success(f"找到 {len(posts)} 篇貼文")

        # Fetch comments and analyze
        analyzed = []
        progress = st.progress(0)
        for i, post in enumerate(posts):
            with st.spinner(f"分析中... ({i+1}/{len(posts)})"):
                try:
                    full_post = components["collector"].get_post_with_comments(
                        post.id,
                        max_comments=config["monitoring"]["reddit"].get("max_comments_per_post", 50),
                    )
                    analysis = components["analyzer"].analyze_post(full_post)
                    analyzed.append((full_post, analysis))
                    components["storage"].save_post(full_post, analysis)
                except Exception as e:
                    st.error(f"分析 {post.title[:50]} 時出錯: {e}")
            progress.progress((i + 1) / len(posts))

        st.session_state["analyzed"] = analyzed

# ── Display results ───────────────────────────────────────────────

if "analyzed" in st.session_state and st.session_state["analyzed"]:
    analyzed = st.session_state["analyzed"]

    # ── Overview metrics ──
    col1, col2, col3, col4 = st.columns(4)
    total_comments = sum(a["num_comments_analyzed"] for _, a in analyzed)
    avg_polarity = sum(a["weighted_avg_polarity"] for _, a in analyzed) / len(analyzed)

    pos_total = sum(a["distribution"]["positive"] for _, a in analyzed)
    neg_total = sum(a["distribution"]["negative"] for _, a in analyzed)
    neu_total = sum(a["distribution"]["neutral"] for _, a in analyzed)

    col1.metric("貼文數", len(analyzed))
    col2.metric("留言分析數", total_comments)
    col3.metric("平均風向", f"{avg_polarity:+.2f}", delta_color="normal")
    col4.metric("正面 vs 負面", f"{pos_total} / {neg_total}")

    # ── Sentiment distribution chart ──
    st.subheader("📊 整體風向分佈")
    fig = go.Figure(data=[go.Pie(
        labels=["正面", "負面", "中性"],
        values=[pos_total, neg_total, neu_total],
        marker_colors=["#2ecc71", "#e74c3c", "#95a5a6"],
        hole=0.4,
    )])
    fig.update_layout(height=350, margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # ── Per-post breakdown ──
    st.subheader("📋 各貼文風向")

    for post, analysis in sorted(analyzed, key=lambda x: x[1]["weighted_avg_polarity"]):
        polarity = analysis["weighted_avg_polarity"]
        dist = analysis["distribution"]

        if polarity > 0.1:
            indicator = "🟢"
        elif polarity < -0.1:
            indicator = "🔴"
        else:
            indicator = "🟡"

        with st.expander(
            f"{indicator} [{post.subreddit}] {post.title[:80]}  "
            f"(⬆{post.score} · 💬{analysis['num_comments_analyzed']} · "
            f"風向 {polarity:+.2f})"
        ):
            st.markdown(f"**[原文連結]({post.url})**")

            # Mini bar chart
            bar_fig = go.Figure(data=[go.Bar(
                x=[dist["positive_pct"], dist["neutral_pct"], dist["negative_pct"]],
                y=["正面", "中性", "負面"],
                orientation="h",
                marker_color=["#2ecc71", "#95a5a6", "#e74c3c"],
            )])
            bar_fig.update_layout(height=150, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(bar_fig, use_container_width=True)

            # Top comments
            if analysis["top_positive"]:
                st.markdown("**👍 最高票正面留言：**")
                for c in analysis["top_positive"][:2]:
                    st.info(f"⬆{c['score']} | {c['sentiment'].text_preview}...")

            if analysis["top_negative"]:
                st.markdown("**👎 最高票負面留言：**")
                for c in analysis["top_negative"][:2]:
                    st.error(f"⬆{c['score']} | {c['sentiment'].text_preview}...")

            # ── Draft generation ──
            st.divider()
            st.markdown("**✍️ 草擬回覆**")

            reply_target = st.radio(
                "回覆對象",
                ["貼文本身"] + [
                    f"留言: {c['sentiment'].text_preview[:60]}..."
                    for c in (analysis["top_positive"] + analysis["top_negative"])[:5]
                ],
                key=f"target_{post.id}",
            )

            if st.button("產生草稿", key=f"draft_{post.id}"):
                target_comment = None
                if reply_target != "貼文本身":
                    # Find the matching comment body
                    all_top = analysis["top_positive"] + analysis["top_negative"]
                    for c in all_top:
                        if reply_target.startswith(f"留言: {c['sentiment'].text_preview[:60]}"):
                            # Find the full comment body
                            for detail in analysis["comment_details"]:
                                if detail["comment_id"] == c["comment_id"]:
                                    target_comment = detail["sentiment"].text_preview
                                    break
                            break

                context = [
                    c["sentiment"].text_preview
                    for c in analysis["comment_details"][:5]
                ]

                with st.spinner("正在產生草稿..."):
                    draft = components["drafter"].generate_draft(
                        stance_id=selected_stance_id,
                        post_title=post.title,
                        post_body=post.body[:500],
                        target_comment=target_comment,
                        discussion_context=context,
                    )

                st.success("草稿已產生！請審閱後自行決定是否使用。")
                st.text_area(
                    "📋 草稿內容（可複製修改）",
                    value=draft.draft_text,
                    height=200,
                    key=f"draft_text_{post.id}",
                )
                st.warning("⚠ 這是 AI 產生的草稿。請自行審閱、修改後再手動發佈。")

else:
    st.info("👈 在左側設定關鍵字和 subreddits，然後按「開始搜尋」")
