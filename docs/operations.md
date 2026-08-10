# Toolbox operations

## Run locally

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run python -m toolbox.app.bootstrap
```

Keep `.env` outside version control. The Codex SDK uses the authenticated account session; OpenAI/GIPHY credentials are optional for the corresponding gated adapters.

## Run with Docker

```bash
docker compose up -d --build
docker compose logs -f toolbox
```

The Compose file uses named volumes for `/data`, `/data/assets`, and `/data/codex`. They contain the SQLite database, expiring/generated assets, and durable reminder/Codex state. Do not remove those volumes during upgrades.

## Backup

Create a consistent SQLite backup while the application is running:

```bash
uv run python scripts/database_backup.py backup \
  --database data/toolbox.sqlite3 \
  --output backups/toolbox-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
```

For Docker's named volume, run the backup utility inside a temporary application container and copy the output out using your deployment's volume-backup procedure. Keep backups encrypted and access-controlled because saved items and reminders are personal data.

## Restore

Stop the application first, preserve the current database, then restore a known-good backup:

```bash
docker compose stop toolbox
cp data/toolbox.sqlite3 data/toolbox.sqlite3.before-restore
uv run python scripts/database_backup.py restore \
  --input backups/known-good.sqlite3 \
  --database data/toolbox.sqlite3
docker compose up -d toolbox
```

Validate the restored database with the test suite or a read-only `/reminders` and `/me` check before deleting the pre-restore copy.

## Logs

```bash
docker compose logs -f toolbox
```

Logs are structured JSON. Interaction logs intentionally omit prompts, message content, attachments, tokens, and saved private data. Use request IDs and capability/provider fields to correlate latency or provider failures.

## Live Discord smoke test

Use a dedicated test application and account. Verify user installation, guild, DM, group-DM/private-channel availability, message context target mapping, private/public responses, button/modal callbacks, deferred AI/image work, and reconnect logs. Do not use a user token or production data for this test.
