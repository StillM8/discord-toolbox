# Hosting a personal Toolbox instance

Toolbox is a Discord Gateway application for a host's personal utility layer. It does not use a Discord user token, does not passively read messages, and does not require a public HTTP endpoint.

## 1. Create the Discord application

In the Discord Developer Portal:

1. Create an application and copy its application ID.
2. Create a bot user and copy its bot token.
3. In Installation, enable **User Install** and add the `applications.commands` scope.
4. Enable the intended interaction contexts: guilds, bot DMs, and private channels.
5. If you want shared results in a server, the server/role/channel must permit **Use External Apps**. Discord can still force an account-installed app response to remain private in a particular context; this is a platform decision, not an application error.

Put only these values in `.env`:

```env
DISCORD_TOKEN=...
DISCORD_APPLICATION_ID=...
OWNER_DISCORD_ID=...
```

`OWNER_DISCORD_ID` is the only account allowed to use owner-only status, Codex login, private vault operations, preferences, reminders, and saved-item delivery.

## 2. Start the stack

```bash
cp .env.example .env
# edit .env
docker compose up -d --build
docker compose logs -f toolbox
```

There are exactly two services by default:

```text
toolbox → Discord, Codex, SQLite, local tools
searxng  → private Docker-network search
```

The named volumes preserve `/data/toolbox.db`, assets, Codex authentication state, and SearXNG configuration. Do not use `docker compose down -v` unless you intentionally want to erase that host's data.

## 3. Authenticate Codex from Discord

After the bot is online, use:

```text
/me codex-login
```

The owner receives a private device-login link/code. Complete it, then wait for `/me status` to show Codex as healthy. The application stores the authenticated SDK state in the `codex_home` volume. No Codex token belongs in `.env`.

## 4. Use the personal vault

```text
/save text:"something to remember" title:"Idea" tags:"ideas,read"
/bookmark text:"same operation with a shorter name"
/bookmarks query:"ideas"
/send-saved item_id:<id>
/export-bookmarks
```

For an existing message, right-click it and choose `Apps → Toolbox → Save`. A saved message keeps the selected content, optional validated attachment, source jump link where Discord supplies one, and owner-defined tags. A private result has a `Send to DM` button; the button's custom ID is opaque and every click is re-authorized against the owner and expiring session.

All slash commands can be used in DMs. The app receives only the interaction input, selected target, or attachment that Discord provides. It never assumes that typing a slash command as a reply grants access to nearby history.

### Accessibility

Accessibility preferences are owner-scoped and survive restarts:

```text
/me accessibility
/me accessibility setting:Plain text value:on
/me accessibility setting:High contrast value:on
/me accessibility setting:Reduce motion value:on
/me accessibility setting:Verbose descriptions value:on
```

Plain-text mode provides screen-reader-friendly message content instead of embeds. Reduced motion suppresses search preview images, high contrast brightens embed accents, and verbose descriptions include direct URLs. Discord's client-level font, theme, zoom, and screen-reader settings remain separate.

## 5. Diagnose a host

Use:

```text
/help
/me status
```

The status report separates required and optional components: Discord, SQLite, assets, SearXNG, Codex text, Codex ImageGen, OCR, ffmpeg, optional GIPHY, optional local media, and paid fallbacks. Structured logs include request IDs, capability names, interaction surface, defer timing, result type, and latency, but not raw prompts, private message text, attachments, or credentials.

```bash
docker compose logs -f toolbox
```

## 6. Back up before upgrades

Stop the app for a restore and keep a pre-restore copy. Bookmark export is a convenient user-level backup; the SQLite backup procedure in [`operations.md`](operations.md) is the host-level backup.
