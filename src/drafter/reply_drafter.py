"""Reply draft generator using Claude API.

Generates reply drafts based on a configured stance.
The user must manually review, edit, and post any generated drafts.
"""

import os
from dataclasses import dataclass

import yaml
import anthropic
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Draft:
    """A generated reply draft."""
    stance_id: str
    target_post_title: str
    target_comment_body: str | None
    draft_text: str
    tone: str
    language: str


class ReplyDrafter:
    """Generate reply drafts based on stance configuration."""

    def __init__(self, stances_path: str = "config/stances.yaml"):
        self.client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        with open(stances_path) as f:
            data = yaml.safe_load(f)
        self.stances = {s["id"]: s for s in data["stances"]}

    def get_available_stances(self) -> list[dict]:
        """List all configured stances."""
        return [
            {"id": s["id"], "name": s["name"], "tone": s["tone"]}
            for s in self.stances.values()
        ]

    def generate_draft(
        self,
        stance_id: str,
        post_title: str,
        post_body: str,
        target_comment: str | None = None,
        discussion_context: list[str] | None = None,
        language: str = "auto",
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 500,
    ) -> Draft:
        """
        Generate a reply draft for a specific post/comment.

        Args:
            stance_id: Which stance to use from stances.yaml
            post_title: Title of the discussion post
            post_body: Body text of the post
            target_comment: Specific comment to reply to (None = reply to post)
            discussion_context: Other comments for context
            language: "auto", "en", "zh-tw", etc.
            model: Anthropic model to use
            max_tokens: Max length of generated draft
        """
        stance = self.stances[stance_id]

        system_prompt = self._build_system_prompt(stance, language)
        user_prompt = self._build_user_prompt(
            post_title, post_body, target_comment, discussion_context
        )

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        draft_text = response.content[0].text

        return Draft(
            stance_id=stance_id,
            target_post_title=post_title,
            target_comment_body=target_comment,
            draft_text=draft_text,
            tone=stance["tone"],
            language=language,
        )

    def _build_system_prompt(self, stance: dict, language: str) -> str:
        tone_map = {
            "rational": "理性、有條理、引用證據",
            "passionate": "有熱情但不失禮貌，帶有個人經驗感",
            "casual": "輕鬆口語，像朋友聊天",
            "academic": "學術風格，引用研究與數據",
        }
        tone_desc = tone_map.get(stance["tone"], stance["tone"])

        constraints_text = "\n".join(f"- {c}" for c in stance.get("constraints", []))
        arguments_text = "\n".join(f"- {a}" for a in stance["key_arguments"])

        lang_instruction = ""
        if language == "auto":
            lang_instruction = "用與討論串相同的語言回覆。"
        elif language == "zh-tw":
            lang_instruction = "用繁體中文回覆。"
        else:
            lang_instruction = f"用 {language} 回覆。"

        return f"""你是一個論點草稿產生器。根據以下立場設定，為使用者草擬一段社群討論回覆。

## 立場：{stance['name']}

### 核心主張
{stance['core_position']}

### 可用論點
{arguments_text}

### 語氣
{tone_desc}

### 限制
{constraints_text}

### 語言
{lang_instruction}

## 重要規則
- 產出的是「草稿」，使用者會自行審閱修改後才決定是否使用
- 回覆要像一個真實的人在討論，不要像 AI 生成的
- 長度適中（2-4 段），不要太長
- 不要用「首先、其次、最後」這種制式結構
- 針對討論內容具體回應，不要泛泛而談
- 選擇最相關的 1-2 個論點深入展開，不要把所有論點都塞進去
"""

    def _build_user_prompt(
        self,
        post_title: str,
        post_body: str,
        target_comment: str | None,
        discussion_context: list[str] | None,
    ) -> str:
        parts = [f"## 討論貼文\n標題：{post_title}\n內容：{post_body}"]

        if discussion_context:
            context_text = "\n---\n".join(discussion_context[:5])
            parts.append(f"## 其他留言（作為背景脈絡）\n{context_text}")

        if target_comment:
            parts.append(f"## 要回覆的目標留言\n{target_comment}")
            parts.append("請針對上述目標留言草擬一段回覆。")
        else:
            parts.append("請針對這篇貼文草擬一段回覆。")

        return "\n\n".join(parts)


# ── CLI entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    drafter = ReplyDrafter()

    # Show available stances
    console.print("[bold]Available stances:[/]")
    for s in drafter.get_available_stances():
        console.print(f"  • {s['id']}: {s['name']} ({s['tone']})")

    # Example usage
    draft = drafter.generate_draft(
        stance_id="pro_ai_regulation",
        post_title="Should governments regulate AI?",
        post_body="With the rapid advancement of AI, many are debating whether regulation is needed.",
        target_comment="Regulation will kill innovation. Look at what happened to crypto.",
    )

    console.print(Panel(draft.draft_text, title="Generated Draft", border_style="green"))
    console.print("\n[yellow]⚠ This is a DRAFT. Review, edit, and manually post if appropriate.[/]")
