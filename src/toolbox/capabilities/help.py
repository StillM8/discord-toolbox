"""User-facing command reference for the Discord interface."""

from __future__ import annotations

from toolbox.core.models import HelpResult, HelpSection, ToolRequest


class HelpCapability:
    """Return the complete command catalog as structured application data."""

    async def execute(self, request: ToolRequest) -> HelpResult:
        """Return help without inspecting Discord or provider state."""

        del request
        return HelpResult(
            sections=(
                HelpSection(
                    title="General",
                    lines=(
                        "`/help` — Show this complete command list.",
                        "`/ping` — Check whether Toolbox is online.",
                    ),
                ),
                HelpSection(
                    title="Search and AI",
                    lines=(
                        "`/search <query> [mode]` — Search web, images, news, video, or GIFs.",
                        "`/find <query> [mode]` — Alias for `/search`.",
                        "`/ask <question>` — Ask Codex.",
                        "`/translate <text> [language] [source]` — Translate text; source can be "
                        "`Pashto` when auto-detection needs help.",
                        "`/what <subject>` — Explain a term, claim, phrase, or link.",
                        "`/research <question>` — Search sources and synthesize an answer.",
                        "`/factcheck <claim>` — Check a claim against web sources.",
                        "`/link <url>` — Summarize a web page.",
                        "`/time <places>` — Get the time in places like `UK Islamabad`.",
                    ),
                ),
                HelpSection(
                    title="Personal",
                    lines=(
                        "`/remind <when> <note>` — Create a durable reminder.",
                        "`/reminders` — List active reminders.",
                        "`/cancel-reminder <id>` — Cancel a reminder.",
                        "`/saved [query]` — Search saved items.",
                        "`/save <text> [title] [tags]` — Save text or an attachment to your "
                        "personal vault.",
                        "`/bookmark ...` — Alias for `/save`.",
                        "`/bookmarks [query]` — Search your bookmarks by text or tag.",
                        "`/send-saved <id>` — Send one saved item to your Discord DMs.",
                        "`/export-bookmarks` — Download your bookmark vault as Markdown.",
                        "`/unsave <id>` — Delete a saved item.",
                        "`/me preferences` — View or update preferences.",
                        "`/me accessibility` — Toggle plain text, high contrast, reduced motion, "
                        "and verbose descriptions.",
                        "`/me status` — Show owner-only runtime status.",
                        "`/me codex-login` — Start Codex authentication.",
                        "`/me saved` — Search your saved items.",
                        "`/me bookmarks` — Search your saved bookmarks.",
                        "`/me export` — Download your bookmark vault as Markdown.",
                        "`/me reminders` — List your reminders.",
                        "`/me context` — List or clear your context basket.",
                    ),
                ),
                HelpSection(
                    title="Create",
                    lines=(
                        "`/create image <prompt>` — Generate an image.",
                        "`/create meme <attachment>` — Caption an image.",
                        "`/create caption <attachment> <caption>` — Add text above an image.",
                        "`/create quote <attachment>` — Make a quote card; choose font, "
                        "alignment, photo color, and photo placement.",
                        "Message Toolbox → **Quote** — Configure a quote from the message "
                        "or its author avatar.",
                        "`/create qr <value>` — Generate a QR code.",
                    ),
                ),
                HelpSection(
                    title="Tools",
                    lines=(
                        "`/tool calc <expression>` — Safely calculate.",
                        "`/tool convert <expression>` — Convert units or currency.",
                        "`/tool time <places>` — Current time for friendly places, "
                        "e.g. `UK Islamabad`.",
                        "`/tool weather <location>` — Check current weather.",
                        "`/tool ocr <attachment>` — Extract text from an image.",
                        "`/tool transcribe <attachment>` — Transcribe audio.",
                        "`/tool background <attachment>` — Remove an image background.",
                        "`/tool file <attachment> <target>` — Convert a file.",
                        "`/tool qr <value>` — Generate a QR code.",
                        "`/tool emoji <emoji>` — Render Unicode or custom Discord emoji.",
                    ),
                ),
                HelpSection(
                    title="Discord context actions",
                    lines=(
                        "Right-click a message → **Apps → Toolbox** for Ask, Search, "
                        "Translate, Fact Check, Quote, Save, and context actions. Save can "
                        "also send a private copy to your DMs.",
                        "Right-click a user → **Apps → Toolbox User** for user utilities "
                        "and avatar quotes.",
                    ),
                ),
                HelpSection(
                    title="Output",
                    lines=(
                        "Results are private by default; use **Share** when Discord "
                        "allows public external-app responses. All commands are available "
                        "in DMs and private channels when Discord exposes them to your app.",
                    ),
                ),
            ),
        )
