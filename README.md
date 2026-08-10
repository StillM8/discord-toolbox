# Toolbox

Toolbox is a summon-only personal Discord utility layer. You explicitly give it a command, selected message, user, image, or attachment; it returns a private preview that can be shared when Discord permits it.

```text
Discord → mapper → ingress dispatcher → capability/workflow
                                      ↓
                         providers / storage / local tools
                                      ↓
                              generic result → renderer
```

Discord is only an interface adapter. Codex is the default text/reasoning provider through `AIRouter`; the official `openai-codex` SDK is isolated in `providers/llm/codex.py`. SearXNG is the default local search service. Optional paid OpenAI integrations are disabled unless explicitly enabled.

## Current capabilities

- `/ping`, `/toolbox`, and `/find` for web, image, news, and video search through SearXNG, plus optional GIF search;
- `/ask`, `/what`, `/research`, `/factcheck`, `/link`, and `/translate`;
- `/tool calc`, `/tool convert`, `/tool time`, `/tool timestamp`, `/tool weather`, `/tool qr`, `/tool background`, and `/tool file`;
- a deterministic utility pack: `/tool random`, `/tool text`, `/tool encode`, `/tool json`, `/tool color`, `/tool image`, and `/tool fileinfo`;
- `/tool ocr` for images and `/tool transcribe` for audio attachments;
- `/create image` through Codex ImageGen with an explicit, opt-in paid OpenAI fallback;
- a compact, reusable Toolbox dashboard for slash commands, selected messages, and selected users; actions are grouped into Ask/Understand, Search, Create, Utilities, and Personal sections instead of a button wall;
- a `Toolbox` message/user context panel for Ask, What is this, Search, Translate, Fact check, Save, Add context, OCR, image questions, image transforms, memes, transcription, and configurable reference-style quote cards (font, alignment, color, and image placement);
- owner-scoped saved items, context basket, preferences, durable reminders, and `/me` subcommands for status/preferences/saved/reminders/context;
- accessibility preferences through `/me accessibility`: plain-text output for screen readers, high-contrast embeds, reduced-motion search previews, and verbose descriptions/URLs;
- a reusable personal vault: `/save`, `/bookmark`, `/bookmarks`, `/send-saved`, tags, attachment bookmarks, source jump links, and owner-authorized “Send to DM” delivery;
- private previews with opaque, owner-authorized Share sessions;
- SQLite/Alembic persistence with FTS5 saved search, expiring local assets, bounded jobs, URL/attachment safety checks, Pillow transforms, Tesseract OCR, HEIC support, and structured Discord lifecycle/interaction logging.

GIF search, richer movie/places APIs, and paid media fallbacks are intentionally optional integrations. The Docker image includes the optional OpenAI client, local-media provider packages, and Urdu/Arabic OCR language data, but paid/API and model-backed features remain disabled until their flags and credentials are enabled; model weights load only when used. The image also includes the deterministic utility, image, PDF, OCR, audio/video conversion, and search stack.

## Runtime stack

The default deployment is one Docker Compose stack with exactly two services:

```text
toolbox  → Python application, Discord Gateway, Codex SDK, SQLite, local tools
searxng  → private Docker-network search aggregator
```

The application talks to SearXNG at `http://searxng:8080`. Its port is not published to the host by default. Persistent named volumes hold application data, assets, Codex authentication state, and SearXNG configuration.

Required accounts:

- Discord Developer application configured for user installation and the intended interaction contexts;
- a ChatGPT/Codex account for the default text provider.

No search, weather, currency, or OpenAI API key is required for the default local-search/Codex-text setup. OpenAI API, GIPHY, TMDB, and YouTube credentials are optional and feature-gated.

## Local setup

Requirements: Python 3.12+, `uv`, Tesseract, and ffmpeg for local file/media conversion.

```bash
uv sync --extra dev
cp .env.example .env
# edit .env with Discord credentials and OWNER_DISCORD_ID
uv run alembic upgrade head
uv run python -m toolbox.app.bootstrap
```

Codex is authenticated once through the official SDK. For a headless Docker host:

```bash
docker compose build
docker compose run --rm toolbox \
  /app/.venv/bin/python -m toolbox.app.codex_login --device-code
docker compose up -d
```

The `codex_home` volume preserves that login. The normal application process never receives host `HOME`, shell credentials, database credentials, or unrestricted tools through a Discord prompt. On startup, an authenticated deployment runs a small text probe and an artifact-level Codex ImageGen probe; `/me status` reports them separately. Codex ImageGen is the primary image provider; paid OpenAI image fallback is opt-in. Text turns use `CODEX_TIMEOUT_SECONDS` (90 seconds by default), while AI image generation/editing uses the separate `CODEX_IMAGE_TIMEOUT_SECONDS` budget (300 seconds by default) because artifact generation is slower.

## Docker setup

```bash
cp .env.example .env
# set DISCORD_TOKEN, DISCORD_APPLICATION_ID, OWNER_DISCORD_ID
docker compose up -d --build
docker compose logs -f toolbox
```

The Compose file is [`docker-compose.yml`](docker-compose.yml). SQLite, assets, and Codex authentication survive container replacement through named volumes. Application startup runs Alembic migrations. SearXNG JSON output is enabled in [`searxng/settings.yml`](searxng/settings.yml); see the [SearXNG search API documentation](https://docs.searxng.org/dev/search_api.html).

## Logging and diagnostics

Logs are structured JSON on stdout. Discord interaction records include request ID, actor, guild/channel, surface, capability, attachment counts, defer state, result type, and latency. Gateway connect/ready/resume/disconnect/close, command registration/sync, mapping failures, component errors, reminder delivery, and uncaught Discord event failures are also recorded. Raw prompts, private message text, attachments, tokens, and credentials are not logged by default.

Use:

```text
LOG_LEVEL=DEBUG
```

only when tuning behavior. The owner-only `/me status` command reports Discord, authenticated Codex probe state, SearXNG, SQLite, assets, ffmpeg, Tesseract, ImageGen, GIPHY, background removal, transcription, and optional-provider state without exposing secrets.

## Personal vault and DMs

Toolbox is designed to be hosted by one person and used from servers, DMs, and private channels without passive message reading. A command only receives the text, message, user, or attachment that you explicitly provide.

Save text from any supported command surface:

```text
/save text:"read this later" title:"Useful idea" tags:"ideas,read"
/save text:"send me a copy" send_to_dm:true
/bookmark text:"same feature, shorter name"
/bookmarks query:"ideas"
/send-saved item_id:<id shown by /bookmarks>
```

For a message, use `Apps → Toolbox → Save`. The saved item keeps a bounded text copy, optional validated attachment, tags, and a Discord jump link when Discord supplied enough coordinates. The result includes a private `Send to DM` action; the action is backed by an opaque expiring session and re-authorizes the owner again when clicked. Attachments are delivered from the application-owned asset store, not fetched from Discord a second time.

Accessibility settings are personal and persist across restarts:

```text
/me accessibility
/me accessibility setting:Plain text value:on
/me accessibility setting:High contrast value:on
/me accessibility setting:Reduce motion value:on
/me accessibility setting:Verbose descriptions value:on
```

Plain-text mode avoids embeds and presents requests, sources, and attached-file descriptions as readable message content. Reduced-motion mode avoids image-search preview thumbnails. High-contrast mode uses a bright embed accent, and verbose descriptions include direct URLs where useful. These settings change Toolbox output; Discord's own font size, theme, and screen-reader controls remain controlled by the Discord client.

Every slash command is configured for the supported user-install contexts, including DMs. If a command is missing from a particular context, resync the application commands after changing Developer Portal installation/context settings; Toolbox does not use `on_message` or a self-bot to work around Discord's interaction model.

Use `/toolbox` to open the private dashboard. Its section and action menus are shared with the right-click `Apps → Toolbox` panels, so new capabilities can be added to one action catalog and exposed through multiple entry points without duplicating UI logic. `/help` is also navigable by section rather than posting every command at once.

## Verification

Every implemented vertical slice has tests at its application/provider/storage/interface boundary.

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

A real Discord user-install smoke test and real Codex login remain deployment checks because they require your Discord application and account. They are deliberately not faked as CI success.

## Architecture

See [`PLAN.md`](PLAN.md) for the detailed architecture and delivery plan and [`AGENTS.md`](AGENTS.md) for coding-agent rules. The hard boundaries are:

1. Discord never calls providers or storage directly.
2. Providers and repositories normalize their external data at the boundary.
3. Capabilities do not call unrelated capabilities; workflows coordinate.
4. General AI goes through `AIRouter` and intent profiles, never model names in feature logic.
5. The dispatcher is ingress-only.
6. `bootstrap.py` owns concrete dependency construction.
7. Only the Discord renderer creates Discord embeds, views, files, or messages.
8. Every new slice adds tests before the next slice begins.

For reusable-host deployment, Discord setup, Codex login, DM usage, vault usage, and diagnostics, see [`docs/hosting.md`](docs/hosting.md).
