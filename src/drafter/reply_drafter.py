"""Reply draft generator using Claude API.

Generates reply drafts based on a configured persona.
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
    persona_id: str
    target_post_title: str
    target_comment_body: str | None
    draft_text: str
    tone: str
    language: str


class ReplyDrafter:
    """Generate reply drafts based on persona configuration."""

    def __init__(self, personas_path: str = "config/personas.yaml"):
        self.client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self.personas_path = personas_path
        self._load_personas()

    def _load_personas(self):
        with open(self.personas_path) as f:
            data = yaml.safe_load(f)
        self.personas = {p["id"]: p for p in data["personas"]}

    def reload_personas(self):
        """Reload personas from disk (call after adding/editing/deleting)."""
        self._load_personas()

    def get_available_personas(self) -> list[dict]:
        """List all configured personas."""
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "tone": p["tone"],
                "background": p.get("background", ""),
                "core_position": p.get("core_position", ""),
            }
            for p in self.personas.values()
        ]

    def generate_draft(
        self,
        persona_id: str,
        post_title: str,
        post_body: str,
        target_comment: str | None = None,
        discussion_context: list[str] | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 600,
    ) -> Draft:
        """
        Generate a reply draft for a specific post/comment.

        Args:
            persona_id: Which persona to use from personas.yaml
            post_title: Title of the discussion post
            post_body: Body text of the post
            target_comment: Specific comment to reply to (None = reply to post)
            discussion_context: Other comments for context
            model: Anthropic model to use
            max_tokens: Max length of generated draft
        """
        persona = self.personas[persona_id]
        language = persona.get("language", "auto")

        system_prompt = self._build_system_prompt(persona)
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
            persona_id=persona_id,
            target_post_title=post_title,
            target_comment_body=target_comment,
            draft_text=draft_text,
            tone=persona["tone"],
            language=language,
        )

    def _build_system_prompt(self, persona: dict) -> str:
        tone_map = {
            "rational": "理性、有條理、引用證據，語氣不帶情緒",
            "passionate": "有熱情但不失禮貌，帶有個人信念感與緊迫感",
            "casual": "輕鬆口語，像朋友聊天，不過度正式",
            "academic": "學術風格，引用研究與數據，措辭精準",
            "sarcastic": "帶點諷刺與幽默，但不至於無禮或人身攻擊",
        }
        tone_desc = tone_map.get(persona["tone"], persona["tone"])

        # Language instruction
        language = persona.get("language", "auto")
        if language == "auto":
            lang_instruction = "用與討論串相同的語言回覆。"
        elif language == "zh-tw":
            lang_instruction = "用繁體中文回覆。"
        else:
            lang_instruction = f"用 {language} 回覆。"

        # Reply length instruction
        length_map = {
            "short": "回覆簡短精煉（1-2 段，約 80-150 字）",
            "medium": "回覆適中（2-3 段，約 150-300 字）",
            "long": "回覆詳細完整（3-5 段，約 300-500 字）",
        }
        length_instruction = length_map.get(persona.get("reply_length", "medium"), "回覆適中")

        # Emoji instruction
        emoji_map = {
            "none": "完全不使用 emoji",
            "minimal": "偶爾使用 1-2 個 emoji，僅在自然的地方",
            "frequent": "適當地使用 emoji 增加表達力",
        }
        emoji_instruction = emoji_map.get(persona.get("emoji_usage", "minimal"), "偶爾使用 emoji")

        # Citation style instruction
        citation_map = {
            "data_driven": "優先引用統計數據、研究報告、具體數字",
            "anecdotal": "多用個人經驗、真實案例、故事性敘述",
            "mixed": "數據與個人經驗並用，視情況選擇最有說服力的方式",
        }
        citation_instruction = citation_map.get(persona.get("citation_style", "mixed"), "數據與案例並用")

        # Key arguments
        arguments_text = "\n".join(f"- {a}" for a in persona.get("key_arguments", []))

        # Avoid topics
        avoid_list = persona.get("avoid_topics", [])
        avoid_text = "\n".join(f"- {t}" for t in avoid_list) if avoid_list else "（無特別禁忌話題）"

        # Catchphrases
        catchphrases = persona.get("catchphrases", [])
        catchphrases_text = (
            "\n".join(f"- {c}" for c in catchphrases)
            if catchphrases
            else "（無特定慣用語）"
        )

        return f"""你是一個論點草稿產生器。你需要完全模擬以下這個人物的說話方式與立場，為使用者草擬一段社群討論回覆。

## 人物：{persona['name']}

### 背景身份
{persona.get('background', '').strip()}

### 核心立場
{persona.get('core_position', '').strip()}

### 可用論點（選擇最相關的 1-2 個深入展開）
{arguments_text}

### 表達風格設定
- **語氣**：{tone_desc}
- **回覆長度**：{length_instruction}
- **Emoji 使用**：{emoji_instruction}
- **引用風格**：{citation_instruction}
- **語言**：{lang_instruction}

### 慣用語 / 口頭禪（自然融入，不要生硬地全部用上）
{catchphrases_text}

### 絕對避免提到的話題
{avoid_text}

## 重要規則
- 產出的是「草稿」，使用者會自行審閱修改後才決定是否使用
- 回覆要像一個真實的人在討論，不要像 AI 生成的制式回覆
- 針對討論內容具體回應，不要泛泛而談
- 不要使用「首先、其次、最後」這種制式條列結構
- 不要在回覆末尾附上「如有需要可以繼續討論」之類的客套話
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

    # Show available personas
    console.print("[bold]Available personas:[/]")
    for p in drafter.get_available_personas():
        console.print(f"  • {p['id']}: {p['name']} ({p['tone']})")

    # Example usage
    draft = drafter.generate_draft(
        persona_id="tech_engineer_ai_skeptic",
        post_title="Should governments regulate AI?",
        post_body="With the rapid advancement of AI, many are debating whether regulation is needed.",
        target_comment="Regulation will kill innovation. Look at what happened to crypto.",
    )

    console.print(Panel(draft.draft_text, title="Generated Draft", border_style="green"))
    console.print("\n[yellow]⚠ This is a DRAFT. Review, edit, and manually post if appropriate.[/]")
