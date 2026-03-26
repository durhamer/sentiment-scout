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

PERSONAS_PATH = "config/personas.yaml"

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


def load_personas_yaml() -> dict:
    with open(PERSONAS_PATH) as f:
        return yaml.safe_load(f)

def save_personas_yaml(data: dict):
    with open(PERSONAS_PATH, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

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

    # ── Persona management ────────────────────────────────────────
    st.header("🎭 人物管理")

    personas_data = load_personas_yaml()
    personas_list = personas_data.get("personas", [])
    persona_names = [p["name"] for p in personas_list]
    persona_ids = [p["id"] for p in personas_list]

    if not personas_list:
        st.warning("尚無人物設定，請先新增一個人物。")
        selected_persona_idx = None
        selected_persona_id = None
    else:
        selected_persona_name = st.selectbox(
            "選擇人物",
            persona_names,
            key="sidebar_persona_select",
        )
        selected_persona_idx = persona_names.index(selected_persona_name)
        selected_persona = personas_list[selected_persona_idx]
        selected_persona_id = selected_persona["id"]

        # Summary card
        with st.container(border=True):
            st.markdown(f"**{selected_persona['name']}**")
            st.caption(selected_persona.get("background", "").strip()[:120] + "...")
            st.markdown(f"立場：{selected_persona.get('core_position', '').strip()[:80]}...")
            cols = st.columns(3)
            cols[0].caption(f"語氣：{selected_persona.get('tone', '-')}")
            cols[1].caption(f"長度：{selected_persona.get('reply_length', '-')}")
            cols[2].caption(f"語言：{selected_persona.get('language', '-')}")

        # Edit button
        if st.button("✏️ 編輯此人物", use_container_width=True):
            st.session_state["editing_persona_idx"] = selected_persona_idx

        # Delete button with confirmation
        if st.button("🗑️ 刪除此人物", use_container_width=True):
            st.session_state["confirm_delete_persona_id"] = selected_persona_id

        if st.session_state.get("confirm_delete_persona_id") == selected_persona_id:
            st.warning(f"確定要刪除「{selected_persona_name}」嗎？此操作無法復原。")
            col_yes, col_no = st.columns(2)
            if col_yes.button("確定刪除", type="primary", use_container_width=True):
                personas_data["personas"] = [
                    p for p in personas_list if p["id"] != selected_persona_id
                ]
                save_personas_yaml(personas_data)
                components["drafter"].reload_personas()
                st.session_state.pop("confirm_delete_persona_id", None)
                st.success("已刪除人物。")
                st.rerun()
            if col_no.button("取消", use_container_width=True):
                st.session_state.pop("confirm_delete_persona_id", None)
                st.rerun()

    # ── Edit persona form ─────────────────────────────────────────
    edit_idx = st.session_state.get("editing_persona_idx")
    if edit_idx is not None and edit_idx < len(personas_list):
        ep = personas_list[edit_idx]
        with st.expander("✏️ 編輯人物", expanded=True):
            with st.form("edit_persona_form"):
                e_name = st.text_input("名稱", value=ep["name"])
                e_background = st.text_area("背景身份", value=ep.get("background", ""), height=80)
                e_core_position = st.text_area("核心立場", value=ep.get("core_position", ""), height=80)
                e_key_arguments = st.text_area(
                    "支持論點（每行一個）",
                    value="\n".join(ep.get("key_arguments", [])),
                    height=100,
                )
                e_tone = st.selectbox(
                    "語氣風格",
                    ["rational", "passionate", "casual", "academic", "sarcastic"],
                    index=["rational", "passionate", "casual", "academic", "sarcastic"].index(
                        ep.get("tone", "rational")
                    ),
                )
                e_reply_length = st.selectbox(
                    "回覆長度",
                    ["short", "medium", "long"],
                    index=["short", "medium", "long"].index(ep.get("reply_length", "medium")),
                )
                e_language = st.selectbox(
                    "語言",
                    ["auto", "zh-tw", "en"],
                    index=["auto", "zh-tw", "en"].index(ep.get("language", "auto")),
                )
                e_emoji_usage = st.selectbox(
                    "Emoji 使用",
                    ["none", "minimal", "frequent"],
                    index=["none", "minimal", "frequent"].index(ep.get("emoji_usage", "minimal")),
                )
                e_citation_style = st.selectbox(
                    "引用風格",
                    ["data_driven", "anecdotal", "mixed"],
                    index=["data_driven", "anecdotal", "mixed"].index(ep.get("citation_style", "mixed")),
                )
                e_avoid_topics = st.text_area(
                    "避免話題（每行一個）",
                    value="\n".join(ep.get("avoid_topics", [])),
                    height=80,
                )
                e_catchphrases = st.text_area(
                    "慣用語 / 口頭禪（每行一個）",
                    value="\n".join(ep.get("catchphrases", [])),
                    height=60,
                )
                submitted = st.form_submit_button("💾 儲存修改", use_container_width=True)
                cancelled = st.form_submit_button("取消", use_container_width=True)

            if submitted:
                personas_data["personas"][edit_idx].update({
                    "name": e_name,
                    "background": e_background.strip(),
                    "core_position": e_core_position.strip(),
                    "key_arguments": [a.strip() for a in e_key_arguments.split("\n") if a.strip()],
                    "tone": e_tone,
                    "reply_length": e_reply_length,
                    "language": e_language,
                    "emoji_usage": e_emoji_usage,
                    "citation_style": e_citation_style,
                    "avoid_topics": [t.strip() for t in e_avoid_topics.split("\n") if t.strip()],
                    "catchphrases": [c.strip() for c in e_catchphrases.split("\n") if c.strip()],
                })
                save_personas_yaml(personas_data)
                components["drafter"].reload_personas()
                st.session_state.pop("editing_persona_idx", None)
                st.success("人物已更新！")
                st.rerun()
            if cancelled:
                st.session_state.pop("editing_persona_idx", None)
                st.rerun()

    # ── Add new persona form ──────────────────────────────────────
    with st.expander("➕ 新增人物"):
        with st.form("add_persona_form"):
            n_id = st.text_input("ID（英文，不含空格）", placeholder="e.g. startup_founder")
            n_name = st.text_input("人物名稱", placeholder="e.g. 新創創辦人")
            n_background = st.text_area("背景身份描述", height=80)
            n_core_position = st.text_area("核心立場", height=80)
            n_key_arguments = st.text_area("支持論點（每行一個）", height=100)
            n_tone = st.selectbox(
                "語氣風格",
                ["rational", "passionate", "casual", "academic", "sarcastic"],
            )
            n_reply_length = st.selectbox("回覆長度", ["short", "medium", "long"], index=1)
            n_language = st.selectbox("語言", ["auto", "zh-tw", "en"])
            n_emoji_usage = st.selectbox("Emoji 使用", ["none", "minimal", "frequent"], index=1)
            n_citation_style = st.selectbox("引用風格", ["data_driven", "anecdotal", "mixed"], index=2)
            n_avoid_topics = st.text_area("避免話題（每行一個）", height=60)
            n_catchphrases = st.text_area("慣用語 / 口頭禪（每行一個）", height=60)
            add_submitted = st.form_submit_button("✅ 建立人物", use_container_width=True)

        if add_submitted:
            if not n_id or not n_name:
                st.error("ID 和人物名稱不能為空。")
            elif any(p["id"] == n_id for p in personas_list):
                st.error(f"ID「{n_id}」已存在，請使用其他 ID。")
            else:
                new_persona = {
                    "id": n_id,
                    "name": n_name,
                    "background": n_background.strip(),
                    "core_position": n_core_position.strip(),
                    "key_arguments": [a.strip() for a in n_key_arguments.split("\n") if a.strip()],
                    "tone": n_tone,
                    "reply_length": n_reply_length,
                    "language": n_language,
                    "emoji_usage": n_emoji_usage,
                    "citation_style": n_citation_style,
                    "avoid_topics": [t.strip() for t in n_avoid_topics.split("\n") if t.strip()],
                    "catchphrases": [c.strip() for c in n_catchphrases.split("\n") if c.strip()],
                }
                personas_data["personas"].append(new_persona)
                save_personas_yaml(personas_data)
                components["drafter"].reload_personas()
                st.success(f"人物「{n_name}」已建立！")
                st.rerun()


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

    # Reload personas for per-post selector (may have changed)
    current_personas = load_personas_yaml().get("personas", [])
    current_persona_names = [p["name"] for p in current_personas]
    current_persona_ids = [p["id"] for p in current_personas]

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

            if not current_personas:
                st.warning("尚無人物設定，請先在 sidebar 新增人物。")
            else:
                # Per-post persona selector，預設為 sidebar 選中的人物
                default_persona_idx = 0
                if selected_persona_id and selected_persona_id in current_persona_ids:
                    default_persona_idx = current_persona_ids.index(selected_persona_id)

                post_persona_name = st.selectbox(
                    "使用人物",
                    current_persona_names,
                    index=default_persona_idx,
                    key=f"persona_{post.id}",
                )
                post_persona_id = current_persona_ids[current_persona_names.index(post_persona_name)]

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
                        all_top = analysis["top_positive"] + analysis["top_negative"]
                        for c in all_top:
                            if reply_target.startswith(f"留言: {c['sentiment'].text_preview[:60]}"):
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
                            persona_id=post_persona_id,
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
