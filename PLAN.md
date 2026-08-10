# Toolbox — Implementation Plan

Status: authoritative architecture, runtime, safety, testing, and delivery plan. The local implementation currently covers the transport path, deterministic core, search/AI boundaries, persistence, assets, media, reminders, preferences, and structured Discord logging. Live Discord installation/context validation still requires a real test application and token.

Working name: **Toolbox**.

## 1. Product decision

Toolbox is a personal, summon-only Discord utility layer:

```text
Discord interaction
    ↓
explicit message / image / user / attachment / text input
    ↓
Toolbox dispatcher
    ↓
search, AI, media, or deterministic utility
    ↓
private preview
    ↓
optional Share/Post action
```

The app does not passively monitor messages, scrape nearby history, impersonate a user account, or become a moderation/music/server-management bot.

The product is intentionally built around explicit inputs because user-installed apps only receive the interaction and data Discord provides for that interaction. A message context command, attachment, or manually selected context item is the source of truth.

## Current implementation status

Implemented and covered by the automated suite:

- modular dispatcher, generic core requests/results/actions, provider/storage contracts, and composition-root lifecycle;
- `discord.py` Gateway adapter with user-install command metadata, message Toolbox context UI, opaque share sessions, deferred long-running interactions, and structured JSON interaction/lifecycle/error logs;
- safe calculator, Pint units/time/currency conversion, weather, QR, preferences, SearXNG web/images/news/video search, Ask/Translate, fact-check workflow, context basket, save/share, reminders, and durable scheduler;
- bounded research/what-is-this workflows with citable source data, optional OpenAI or faster-whisper audio transcription for selected attachments, and owner-only runtime health status;
- official `openai-codex` SDK provider through `AIRouter`, with ephemeral read-only bounded Codex turns, separate text/ImageGen startup probes, and optional OpenAI Responses fallback/vision;
- local asset store with expiring sidecar metadata, validated attachment ingestion, libmagic/pillow-heif support, URL policy, Pillow image transforms, OCR, image questions, meme/quote generation, bounded ffmpeg/PDF/file conversion, optional GIPHY search, optional rembg background removal, and Codex ImageGen with an explicitly gated paid OpenAI fallback;
- SQLite/Alembic storage adapters with FTS5 saved-item search, a two-service Docker Compose deployment with private SearXNG, a persisted Codex home/login helper, startup Codex probing, and tests for every implemented boundary.

Still dependent on external smoke/configuration work or intentionally gated: live Discord user-install behavior, real Codex authentication, optional provider credentials/terms, DNS-level SSRF resolution, and backup/restore execution on the deployment host. TMDB/YouTube/places enrichments remain intentionally outside the default release.

## 2. Non-negotiable architecture rules

1. Discord code never calls OpenAI, Codex, search, image, OCR, or database implementations directly.
2. Providers never import Discord code.
3. Capabilities do not call unrelated capabilities; workflows coordinate multi-step operations.
4. Core objects contain no Discord, OpenAI, SQLAlchemy, or provider SDK types.
5. Prompt builders receive structured context and never query storage.
6. Results are generic application results; only the Discord renderer creates embeds, views, modals, and messages.
7. Concrete dependencies are created in one composition root: `src/toolbox/app/bootstrap.py`.
8. Application state belongs to Toolbox, not to a Codex thread or provider session.
9. Mutations require explicit authorization and an obvious owner.
10. No Redis, Celery, Postgres, MCP mesh, generic workflow engine, or microservice is added without a demonstrated need.

## 3. Important Codex decision

Codex is an intentional runtime dependency for this personal, owner-controlled application. The plan must not silently replace it with the Responses API.

The neutral application boundary is:

```text
capabilities/workflows
          ↓ profile + LLMRequest
       AIService / AIRouter
          ↓
       LLMProvider
       ┌──┴────────────────────┐
       ▼                       ▼
 CodexProvider       OpenAIResponsesProvider
       │                       │
 Codex / Luna          OpenAI API / fallback
```

The configured default is:

```text
fast     → Codex / GPT-5.6 Luna / low effort
normal   → Codex / GPT-5.6 Luna / medium effort
research → Codex / GPT-5.6 Luna / high effort
vision   → Codex multimodal when no OpenAI API key is configured; optional OpenAI Responses otherwise
image    → Codex built-in ImageGen; optional paid OpenAI image fallback
```

Features request a profile, never a model name or Codex-specific option. `OpenAIResponsesProvider` remains an implemented or immediately implementable fallback for rate limits, unavailable Codex sessions, vision, and future deployment changes.

`CodexProvider` uses the official `AsyncCodex` SDK with ephemeral, stateless requests, a dedicated empty working directory, read-only/no-write permissions, no MCP servers, no project repository, no host credentials, and strict timeouts. On the POSIX/Docker runtime, the adapter launches the bundled app-server through an `env -i` allowlist so Discord tokens, database URLs, optional API keys, and the host environment cannot be inherited. The process receives an explicit `CODEX_HOME`, not the host `HOME`. Codex threads are transport state only; Toolbox’s database remains the source of truth.

This is still a public-facing application boundary, so arbitrary users must not gain shell, filesystem, tool-calling, or provider-credential access merely because their text reaches Codex. The runtime container/process is isolated, and the provider adapter accepts only a bounded `LLMRequest`.

Model names are configuration, not feature code. At deployment time, verify the current catalog and configure the profiles above; the current official model guidance lists GPT-5.6 Luna for cost-sensitive/high-volume work and GPT-5.6 Sol for complex reasoning. Image generation remains isolated behind an image provider, currently targeting `gpt-image-2`.

The intended configuration shape is:

```toml
[ai]
default_text_provider = "codex"

[ai.profiles.fast]
provider = "codex"
model = "gpt-5.6-luna"
effort = "low"

[ai.profiles.normal]
provider = "codex"
model = "gpt-5.6-luna"
effort = "medium"

[ai.profiles.research]
provider = "codex"
model = "gpt-5.6-luna"
effort = "high"

[ai.profiles.vision]
provider = "openai_responses"

[ai.fallbacks]
codex = "openai_responses"
```

The exact Codex SDK/CLI flags are isolated inside `providers/codex/`; this TOML is application configuration, not a promise that capabilities know how Codex is invoked.

## 4. Discord transport decision gate

Discord supports Gateway and outgoing-webhook interaction delivery, but an app must choose one interaction delivery method. `discord.py` is the preferred Gateway implementation.

The first engineering spike must verify all of these with a real Discord test application:

- user installation works;
- global commands appear in guilds, the app DM, DMs, and group DMs where intended;
- message context commands receive the targeted message/attachment data;
- buttons and modals continue to work for user-installed responses;
- private responses work where public responses are not permitted;
- long-running work can be deferred and completed within interaction-token limits.

Default implementation path:

```text
discord.py 2.x Gateway adapter
```

Fallback path if the account-wide user-install behavior is not delivered reliably through the Gateway setup:

```text
FastAPI HTTP interaction adapter
    + Discord signature verification
    + the same mapper, dispatcher, capabilities, and renderer contracts
```

The two transports are alternatives for a deployment, not two simultaneous interaction consumers. The core application is independent of this choice.

## 5. Selected stack

### Runtime and Python

- Python 3.12, with a narrow supported range documented in `pyproject.toml`.
- `uv` for dependency resolution and a committed lockfile.
- `discord.py` 2.x, pinned by the lockfile; require at least the release that supports user-install contexts (`2.4+`).
- `openai-codex` Python SDK for the default `CodexProvider`; it is treated as a pinned, isolated dependency rather than a hidden global executable. The persisted `CODEX_HOME` is authenticated separately through `toolbox.app.codex_login`.
- `httpx` for one shared async HTTP client.
- `pydantic` and `pydantic-settings` for typed configuration and boundary validation.

### Application and persistence

- `SQLAlchemy` 2.x async ORM plus `aiosqlite`.
- `Alembic` from the first schema version onward.
- SQLite in the first deployment, stored on a mounted volume.
- An `AssetStore` abstraction with a local filesystem implementation.
- PostgreSQL and object storage remain later replacement adapters, not MVP requirements.

### AI and media

- Optional official `openai` Python SDK for Responses, image generation/editing, vision, moderation, and transcription when explicitly enabled. It is not a required import or default dependency.
- `Pillow` plus `pillow-heif` for local image transformations, thumbnails, memes, metadata, compression, and phone-uploaded HEIC/HEIF files.
- `qrcode[pil]` for QR generation.
- `ffmpeg` is installed in the application image for bounded audio/video conversion.
- Tesseract OCR as an optional local processor; OpenAI vision is the fallback for screenshot understanding and image explanation.
- `selectolax`/`trafilatura`-style HTML extraction only inside a link-fetching provider; never in a Discord adapter.

### Quality and operations

- `pytest`, `pytest-asyncio`, and `respx` for tests around async providers.
- `ruff` for formatting/linting.
- `pyright` in strict mode for contract/type checking.
- `structlog` is part of the runtime dependency set; the current adapter emits equivalent structured JSON through the stdlib logging bridge so Discord library records remain visible and safe.
- Docker and Docker Compose for repeatable two-service deployment (`toolbox` and private `searxng`).
- Sentry is optional after the first working deployment; do not make the app depend on a hosted observability service.

## 6. External services

| Service | Use | Phase | Decision |
|---|---|---:|---|
| Discord Developer Platform | user/guild install, interactions, component UI | 0 | required |
| Codex runtime | default text/reasoning provider using the owner-controlled Codex allowance | 1 | required for text AI |
| OpenAI API | optional vision, structured fallback, transcription, paid image fallback | 1–2 | disabled unless explicitly configured |
| SearXNG | raw web/image/news/video search | 1 | required local Compose service |
| Open-Meteo | weather and geocoding | 2 | no-key, non-commercial candidate |
| Frankfurter + keyless exchange-rate fallback | currency rates | 2 | Frankfurter is preferred; fallback covers currencies outside its ECB dataset |
| GIPHY | GIF search | optional | disabled unless explicitly enabled with a configured key; keep attribution/rate terms current |
| Local Pillow/Tesseract/ffmpeg | transformations, OCR, media conversion | 2 | preferred for privacy/cost |

SearXNG is private to the Compose network. The `SearXNGSearchProvider` consumes its JSON endpoint and returns normalized provider data; application result/rendering models remain separate. Search engine availability varies by SearXNG configuration and upstream behavior.

GIF search has a real provider/capability path but is disabled by default. GIPHY terms, attribution, caching, and quota rules must be reviewed before enabling it. Tenor is not a default provider.

No Google Places, YouTube transcript scraper, reverse-image scraper, or hosted vector database is assumed in MVP. Each would require a separate terms, quota, and privacy decision.

## 7. Repository layout

The full structure is a destination, not a day-one scaffold. Do not create empty architectural packages. A folder or class is introduced only when a vertical slice needs it.

### First slice — only these files

```text
toolbox/
├── PLAN.md
├── README.md
├── AGENTS.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── src/toolbox/
│   ├── app/
│   │   ├── bootstrap.py
│   │   └── dispatcher.py
│   ├── core/
│   │   ├── models.py
│   │   └── contracts.py
│   ├── capabilities/
│   │   └── ping.py
│   └── interfaces/
│       └── discord/
│           ├── bot.py
│           ├── mapper.py
│           └── renderer.py
└── tests/
    └── unit/
```

This slice proves:

```text
Discord interaction
    → mapper
    → dispatcher
    → dummy capability
    → generic result
    → renderer
```

### Growth path

Only after a slice needs them, add cohesive modules such as:

```text
src/toolbox/
├── app/
│   └── registry.py                 # only when more than one handler exists
├── core/
│   ├── requests.py
│   ├── results.py
│   ├── context.py
│   └── errors.py
├── capabilities/
│   ├── ask/
│   ├── search/
│   ├── images/
│   ├── translate/
│   ├── fact_check/
│   ├── ocr/
│   ├── tools/
│   └── personal/
├── workflows/
├── providers/
│   ├── codex.py
│   ├── openai_responses.py
│   ├── search/
│   ├── weather/
│   └── currency/
├── storage/
├── infrastructure/
├── interfaces/discord/
└── config/
```

There is deliberately no `application.py` in the initial shape. If an application facade would only expose `application.dispatcher`, it is not needed; the Discord adapter can receive the dispatcher directly. Add an application facade only when it owns a real lifecycle or boundary responsibility.

## 8. Core contracts

The first contracts will be small and typed. Representative concepts:

```python
MessageContext
AttachmentRef
UserContext
InteractionContext
ToolRequest
Visibility
ToolAction

TextResult
SearchPage
SearchHit
SearchResults
ImageGalleryResult
ImageResult
FileResult
ChoiceResult
PendingResult
NoAction
ErrorResult
```

Provider contracts:

```python
class AIService(Protocol):
    async def generate(
        self,
        profile: AIProfile,
        request: LLMRequest,
    ) -> LLMResponse: ...

class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...

class WebSearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchPage: ...

class ImageSearchProvider(Protocol):
    async def search(self, request: ImageSearchRequest) -> ImageSearchPage: ...

class ImageGenerationProvider(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> GeneratedAsset: ...
    async def edit(self, request: ImageEditRequest) -> GeneratedAsset: ...

class OCRProvider(Protocol):
    async def extract(self, asset: AssetRef) -> OCRResult: ...

class AssetStore(Protocol):
    async def put(self, data: bytes, metadata: AssetMetadata) -> AssetRef: ...
    async def open(self, asset: AssetRef) -> AsyncIterator[bytes]: ...
    async def delete(self, asset: AssetRef) -> None: ...
```

The distinction between provider data and application results is intentional:

```text
SearXNG/search API
    ↓
SearchPage
    ├── SearchHit
    ├── SearchHit
    └── SearchHit
    ↓
SearchCapability
    ↓
SearchResults + application actions
    ↓
DiscordRenderer
```

`SearchPage`, `SearchHit`, and provider metadata describe retrieved data. `SearchResults` describes what the application wants to show and what actions are allowed. Provider contracts must not slowly become UI contracts.

`AIService`/`AIRouter` is a narrow profile-routing facade, not a universal manager. It maps `fast`, `normal`, `research`, and `vision` to concrete `LLMProvider` instances in bootstrap. Capabilities never import `CodexProvider` or `OpenAIResponsesProvider`.

Repository contracts belong in the application/core boundary. SQLAlchemy models and sessions stay in storage.

## 9. User experience surface

Keep the visible command surface small:

```text
/find       web, image, GIF, video, news search
/ask        general question or ask about selected/context items
/translate  translate explicit text or a selected message
/create     image, meme, QR, quote image
/tool       calc, convert, time, weather, file utilities
/me         saved items, context basket, reminders, preferences
```

Context commands:

```text
Message → Apps → Toolbox
User    → Apps → Toolbox
```

The message Toolbox panel exposes a small set of actions:

```text
Ask · Search · Fact Check · Translate · Create from this · Save · Add Context · More
```

For images attached to a selected message:

```text
Ask about image · OCR · Edit · Meme · Remove background · Upscale · Convert · Add Context
```

Do not depend on a slash command typed as a reply automatically carrying arbitrary nearby history. The supported path is a message context command or explicit context basket.

Every result defaults to private preview where Discord permits it. Results expose generic actions such as `share`, `refine`, `save`, `ask`, `next`, `regenerate`, and `delete`; the Discord renderer turns these into buttons/selects/modals.

The renderer must inspect interaction context and permissions. If a public response is not allowed, it remains private and explains why. All buttons are authorization-checked again when clicked.

## 10. Context basket and session state

The context basket is the product’s privacy-preserving answer to limited message history:

```text
Message A → Add Context
Message B → Add Context
Image     → Add Context
/ask      → question over exactly those selected items
```

Rules:

- keyed by authorizing Discord user ID;
- max item count, max bytes, and max age;
- expires after 30 minutes by default;
- cleared after successful execution unless the user chooses Keep;
- stored as normalized text/asset references, never raw Discord objects;
- never used as hidden global context for another user;
- UI component IDs contain only opaque, signed/validated session references.

## 11. Capability delivery order

### Phase 0 — foundation and Discord spike (local implementation complete)

Deliver:

- only the minimal first-slice tree shown above;
- `AGENTS.md` architecture rules and `uv` project commands;
- typed settings, secret loading, logging, and request IDs;
- Discord installation configuration;
- `/ping` and one `Toolbox` message context command;
- a dummy capability returning `TextResult`;
- transport spike covering user install, GDM, DM, guild, private/public response behavior.

The local mapper → dispatcher → capability → result → renderer path is complete and covered by tests. The remaining gate is a live test of user-install, guild/DM/GDM, public/private permissions, components, and interaction timing. Do not claim that live gate passed without real Discord evidence.

Exit criteria: a real account-installed interaction maps to `ToolRequest`, passes through the dispatcher, returns `TextResult`, and renders without business logic in the Discord adapter in every target Discord context.

### Phase 1 — useful core

Deliver vertical slices, in this order:

1. `/tool calc` using a safe deterministic parser; never evaluate arbitrary Python.
2. `/tool convert` for units, time zones, and currency through explicit providers.
3. `/find web/image/news/video` using the private `SearXNGSearchProvider`, normalized sources, and private preview/share with server-side pagination; optional `/find gif` through GIPHY. **Implemented.**
4. `/ask` using `AIService` with the `normal` profile, bounded input, structured result metadata, and provider-safe error handling.
5. Message Toolbox → Ask, Search, Translate, Add Context.
6. Add SQLite/Alembic and a `SaveRepository` only when the Save vertical slice begins. **Implemented.**
7. Preferences for timezone, language, currency, visibility, and default profile. **Implemented.**

Exit criteria: the same capability works from slash command, message context command, and component action without duplicated business logic.

### Phase 2 — images and local media

Deliver:

- attachment download validation and asset lifecycle;
- image vision: describe, explain, OCR fallback, ask about image;
- local image transforms: resize, compress, convert, rotate, mirror, blur, pixelate, deep-fry;
- `/create qr`, quote image, and meme;
- Codex ImageGen image generate/edit behind `ImageGenerationProvider`, with optional paid OpenAI fallback;
- preview gallery, post/share, regenerate, and edit actions;
- optional ffmpeg-backed media conversion with strict size/time limits.

Exit criteria: no provider response or local file path leaks into core/capabilities; all generated/intermediate assets expire or are saved intentionally. The current implementation covers local transforms, OCR, image questions, memes, quote cards, QR, HEIC-aware attachment ingestion, bounded ffmpeg/PDF/file conversion, Codex ImageGen, optional rembg background removal, and an explicitly gated paid image fallback.

### Phase 3 — search/research/social utilities

Deliver:

- image search and source attribution;
- news/video search if the selected search provider supports it;
- link inspection and bounded article extraction;
- fact-check workflow: search evidence → structured LLM verdict → citations;
- research workflow with explicit source limits and a background job path;
- optional GIF provider with explicit feature/key gating and source attribution;
- translation, definition, and universal “What is this?” routing.

Exit criteria: AI never presents unsourced current claims as verified; source links and uncertainty are visible.

### Phase 4 — personal layer

Deliver:

- saved items with tags/full-text search;
- reminders tied to user timezone;
- context basket management;
- usage limits and owner-only private tools;
- asset cleanup and backup/restore commands;
- optional OpenAI or local faster-whisper audio transcription.

Exit criteria: personal data is isolated by Discord user ID and all owner-only actions are enforced server-side.

### Phase 5 — production hardening

Deliver:

- deployment backup/restore runbook;
- structured logs and error reporting;
- provider health checks and fallback policy;
- rate/concurrency limits by user, provider, and operation;
- contract tests for every provider;
- Discord regression suite against a dedicated test server/user account;
- cost dashboard from usage events;
- documented migration path to Postgres/object storage if needed.

## 12. Workflows

Atomic capabilities do one recognizable thing. Workflows own sequencing.

### `AskAboutMessageWorkflow`

```text
validated message context
    ↓
optional context basket
    ↓
prompt/context builder
    ↓
LLMProvider
    ↓
TextResult + actions
```

### `FactCheckWorkflow`

```text
claim extraction/validation
    ↓
WebSearchProvider
    ↓
source normalization and limits
    ↓
LLMProvider structured verdict
    ↓
FactCheckResult with citations and confidence
```

### `ImageToMemeWorkflow`

```text
AttachmentRef
    ↓
AssetStore validation
    ↓
caption input
    ↓
Pillow renderer
    ↓
Generated asset
    ↓
ImageResult
```

No generic graph engine is planned. These remain readable Python classes/functions.

## 13. Storage model

Initial tables:

```text
users
user_preferences
interaction_sessions
context_items
assets
saved_items
reminders
usage_events
```

Important ownership:

- preferences, saved items, reminders, and context baskets belong to a Discord user;
- assets belong to an owner/session and have an expiry;
- usage events contain provider/model/operation and timing metadata, not raw prompts by default;
- provider caches are disposable and never the source of truth;
- repositories load/save domain objects, not SQLAlchemy models outside storage.

Reminders are durable records, not in-memory tasks:

```text
SQLite reminder row
    ├── owner_id
    ├── due_at_utc
    ├── payload/reference
    ├── status
    ├── attempt_count
    └── last_attempt_at
          ↓
periodic scheduler tick
          ↓
atomically claim due rows
          ↓
JobRunner executes delivery
```

On restart, the scheduler reloads pending rows. Delivery is idempotent, failures use bounded retry/backoff, and completed/expired rows remain auditable until cleanup. The in-memory runner executes work; SQLite owns reminder state.

## 14. Security and privacy

- Never use a Discord user token or self-bot technique. Use a proper Discord application/bot token and supported installation flow.
- Keep Discord, OpenAI, search, and service keys in environment/secret storage; never commit them.
- Default to private preview and explicit Share.
- Owner-only checks use the authorizing installation owner plus the triggering user; never trust a button’s custom ID alone.
- Disable `@everyone`/role mentions in rendered output unless explicitly required.
- Enforce maximum text, attachment size, image dimensions, download bytes, redirects, and processing time.
- Allow only `http`/`https`; block localhost, private IPs, link-local ranges, metadata endpoints, and unsafe redirects in URL fetchers.
- Validate MIME type from bytes, not only file extension.
- Strip or avoid storing EXIF/metadata unless the user explicitly requests it.
- Moderate user text and generated media at the appropriate boundary; expose provider refusal as a safe `ErrorResult`.
- Never give the runtime AI provider shell, filesystem, Discord token, database credentials, or arbitrary network tools.
- Do not log prompt contents, attachments, secrets, or private saved items by default.

## 15. Reliability and lifecycle

Startup:

```text
load settings
→ configure logging
→ create HTTP client
→ open database/run migrations
→ create asset store/cache/job runner
→ create providers
→ create repositories
→ create capabilities/workflows
→ register dispatcher handlers
→ create Discord transport
→ start
```

Shutdown:

```text
stop accepting work
→ drain/cancel jobs
→ close Discord transport
→ close providers/HTTP client
→ close database
```

Technical timeouts belong in provider/infrastructure code. Workflow code decides whether to retry, fall back, or return a user-facing error. Retry only idempotent operations and never blindly retry image generation or state mutations.

Start with an in-process `JobRunner` and bounded semaphore. Add one small scheduler for durable reminders that periodically claims due SQLite rows. Move expensive media work to a worker only when measurements show the Discord process is being blocked.

## 16. Testing strategy

### Unit tests

- policies: pure tests for visibility, limits, routing, owner checks, and result actions;
- deterministic tools: calculator, conversions, timestamps, QR, image transforms;
- mappers/renderers: normalized Discord input and generic result output;
- structured parsing: provider payload → normalized response.

### Contract/provider tests

- fake provider tests for capabilities/workflows;
- HTTP fixtures with `respx` for SearXNG/OpenAI/weather/currency;
- live smoke tests opt-in and never required for normal CI;
- repository tests against temporary SQLite database.

### Workflow tests

Verify order and stop conditions using fakes:

```text
disabled feature → no provider call
unauthorized action → no mutation
search failure → correct fallback/error
fact check → evidence passed to LLM
share action → only allowed result is posted
```

### Discord tests

- command registration snapshots;
- message/user/attachment mapping;
- component authorization and expired sessions;
- renderer snapshots for each result type;
- manual/automated smoke tests against a dedicated Discord test app.

## 17. Codex-assisted development workflow

`AGENTS.md` contains the architecture invariants, commands, and verification rules. Codex work is split into vertical slices:

1. write/confirm the smallest contract needed by the slice;
2. implement the core behavior with fakes;
3. implement one provider adapter only if the slice requires it;
4. wire it in `bootstrap.py`;
5. add one Discord entry point;
6. add renderer/component tests;
7. run lint, type checks, unit tests, and a smoke test;
8. remove transitional code before starting the next slice;
9. add the next package/class only when the next slice proves it is needed.

Codex should not be asked to generate the entire application or full folder tree in one pass. Each change must have one capability/workflow owner, one acceptance test path, and the smallest possible file set. The initial transport gate was implemented locally; subsequent work continues one tested vertical slice at a time.

For runtime Codex work, use the same vertical-slice discipline: `FakeLLMProvider` first, then `CodexProvider`, then the `AIRouter` profile mapping, then the OpenAI fallback. No feature imports a concrete AI provider.

## 18. Definition of done for the first release

The first release is ready when:

- the user-installed Discord flow works in the tested contexts;
- `/find`, `/ask`, `/tool calc`, `/tool convert`, and message Toolbox work;
- private preview → Share works and respects Discord permissions;
- one message can be explicitly added to a context basket;
- OpenAI/search failures become safe generic error results;
- no interface module imports provider SDKs or storage implementations;
- all long-lived dependencies are visible in `bootstrap.py`;
- tests cover policies, mappers, renderer, workflows, provider parsing, and repositories;
- Docker deployment, backup, secret rotation, and shutdown are documented.

## 19. Explicitly deferred

These are not part of the first implementation unless a concrete need appears:

```text
server moderation
music playback
passive message listening
self-bot behavior
automatic replies
home automation
full browser automation
multi-agent runtime
MCP for internal module calls
Redis/Celery/Kafka/Kubernetes
Postgres/object storage
hosted vector database
plugin marketplace
```

## 20. References checked

- [Discord application commands](https://docs.discord.com/developers/interactions/application-commands)
- [Discord user-installable app tutorial](https://docs.discord.com/developers/tutorials/developing-a-user-installable-app)
- [Discord receiving and responding to interactions](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [discord.py interaction API](https://discordpy.readthedocs.io/en/stable/interactions/api.html)
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk.md)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)
- [OpenAI models](https://developers.openai.com/api/docs/models)
- [OpenAI images and vision](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation)
- [SearXNG search API](https://docs.searxng.org/dev/search_api.html)
- [SearXNG Docker installation](https://docs.searxng.org/admin/installation-docker)
- [Open-Meteo](https://open-meteo.com/en/docs)
- [Frankfurter](https://frankfurter.dev/)
- [GIPHY API terms/guidance](https://developers.giphy.com/docs/api/)
- [Tenor API quickstart](https://developers.google.com/tenor/guides/quickstart)
