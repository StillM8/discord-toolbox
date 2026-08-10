# Toolbox coding rules

`PLAN.md` is the authoritative modular-monolith specification. Work incrementally: implement one vertical slice, test it, wire it in the composition root, expose it through a thin Discord adapter, and stop before starting unrelated future work.

## Non-negotiable boundaries

1. Discord code maps, acknowledges, delegates, and renders. It does not contain business logic or call provider/storage SDKs.
2. Provider and repository implementations never import Discord.
3. Discord objects, SDK response objects, and SQLAlchemy rows stop at their boundaries.
4. Capabilities do one recognizable thing. Unrelated capabilities never call each other.
5. Workflows coordinate multi-step operations through explicit constructor-injected dependencies.
6. The dispatcher is for external ingress routing only, never an internal service locator.
7. General AI goes through `AIService`/`AIRouter`; features request `AIProfile` values, never models or concrete providers.
8. Codex is isolated in `providers/llm/codex.py` behind `LLMProvider`; requests are bounded, ephemeral, read-only, and tool-free.
9. Only the renderer creates Discord embeds, views, modals, files, or messages.
10. `src/toolbox/app/bootstrap.py` owns concrete dependency construction and lifecycle.
11. Mutations are owner-scoped and re-authorized at execution time.
12. Treat Discord input, attachments, URLs, search pages, provider output, component IDs, and AI output as untrusted.
13. Never use `eval`, `exec`, a self-bot/user token, `shell=True`, arbitrary shell execution, or raw private-content logging.
14. Do not add microservices, Redis/Celery/Kafka/Kubernetes/Postgres, an MCP mesh, an event bus, or a generic workflow engine without measured need.
15. Do not create empty destination packages or hypothetical abstractions.

## Required development procedure

1. Inspect current ownership and contracts.
2. Define the smallest new contract required.
3. Implement core behavior with fakes.
4. Add provider/repository/transport adapters only where needed.
5. Wire concrete dependencies only in bootstrap/wiring.
6. Add the thinnest Discord entry point and generic renderer path.
7. Add unit, workflow/provider/storage/interface tests for the boundary introduced.
8. Run all checks and the relevant smoke test.
9. Remove transitional `_old`, `_new`, `_v2`, or duplicate implementations.

## Required checks

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

Do not claim the live Discord transport spike passed without a real test application/token. The local suite proves the mapper → dispatcher → result → renderer path; live user-install, DM/GDM, permission, and interaction timing behavior must be tested manually or in a separately configured smoke environment.
