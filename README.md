# obsidian-web-mcp

A secure, remote-accessible MCP server that gives LLMs read/write access to your Obsidian vault from anywhere -- your desktop, your phone, a hotel Wi-Fi network. Unlike local-only Obsidian MCP servers, this one runs over HTTPS with real authentication, so Claude (or any MCP client) can reach your vault whether you're at your desk or not.

It reads and writes markdown files on disk, parses YAML frontmatter, maintains an in-memory frontmatter index for fast queries, and handles full-text search -- all behind OAuth 2.0 authentication and a Cloudflare Tunnel that never exposes your machine directly to the internet.

## Why This Exists

There are many Obsidian MCP servers. Most are local stdio servers -- they work when Claude Code is running on the same machine as your vault. That's useful, but it means:

- **Claude.ai (web) can't reach your vault.** The browser-based Claude has no way to connect to a local stdio server.
- **Claude on your phone can't reach your vault.** Same problem.
- **If you use Obsidian Sync, local MCP servers can corrupt files.** Non-atomic writes create partial files that Sync propagates to every device.

This server solves all three. It runs as a persistent HTTP service on the machine where your vault lives, tunneled securely through Cloudflare, and authenticates via OAuth 2.0 -- the same protocol Claude uses for Gmail, Google Calendar, and other integrations. The result: your vault becomes a first-class MCP connector available everywhere Claude is.

## Architecture

```
+----------+     +------------+     +-----------------+     +------------------+
| Obsidian | <-> | Filesystem | <-> | obsidian-web-mcp| <-> | Cloudflare       |
| (app)    |     | (*.md)     |     | (MCP over HTTPS)|     | Tunnel           |
+----------+     +------------+     +-----------------+     +------------------+
                                                                   |
                                                            +------+-------+
                                                            | Claude       |
                                                            | (web/desktop/|
                                                            |  mobile)     |
                                                            +--------------+
```

Your vault files never leave your machine. Cloudflare Tunnel creates an outbound-only connection from your server to Cloudflare's edge -- no inbound ports opened, no public IP exposed, no port forwarding. Claude connects to the Cloudflare edge, which relays requests through the tunnel to your server.

Obsidian and the MCP server both operate on the same directory of markdown files. The server uses atomic writes (write-to-temp-then-rename) so Obsidian Sync and the server never conflict.

## Security Model

This is a server that provides network access to your personal notes. Security is not optional.

**Authentication is enforced on every request.** The server implements the OAuth 2.0 authorization code flow with PKCE (what Claude uses when you connect the integration), plus bearer token validation on every subsequent MCP tool call. No request reaches a tool function without a valid token.

**Client authentication gates the token.** The authorization endpoint auto-approves (single-user model), but auto-approval alone grants nothing: the token endpoint will only issue a bearer token to a caller that proves possession of the OAuth client secret. PKCE is not treated as a standalone boundary, since a caller that reaches the authorization endpoint controls its own PKCE pair. Dynamic client registration issues a unique secret per registration -- the configured shared secret is never returned over the wire.

**Your vault is never exposed directly to the internet.** The recommended deployment uses a Cloudflare Tunnel -- an outbound-only encrypted connection. Your machine opens no inbound ports. You can layer Cloudflare Access on top for additional authentication (SSO, device posture checks, IP restrictions) if you want defense in depth.

**Path traversal is blocked at the filesystem layer.** Every file operation resolves paths against the vault root directory and rejects any attempt to escape it -- `..` traversal, symlink following, null byte injection, and dotfile access (`.obsidian`, `.git`, `.trash`) are all caught before they reach the filesystem. The server will never read or write outside your vault directory.

**Writes are atomic.** Every file write goes to a temporary file first, then atomically replaces the target via `os.replace()`. This guarantees that neither Obsidian nor Obsidian Sync ever sees a partially-written file -- the operation either completes fully or doesn't happen at all.

**Safety limits prevent abuse.** Writes are capped at 1MB per file, batch operations at 20 files per request, and search results at 50 matches. Deletions are soft -- files move to `.trash/` rather than being permanently removed, matching Obsidian's own behavior. The delete tool also requires an explicit `confirm=true` parameter as a safety gate.

**Startup fails closed.** If the authenticated app cannot be built for any reason, the server logs the error and exits rather than falling back to an unauthenticated transport. It will never serve your vault without bearer-token enforcement.

## Tools

| Tool | Description |
|------|-------------|
| `vault_read` | Read a file, returning content, metadata, and parsed YAML frontmatter |
| `vault_batch_read` | Read multiple files in one call; handles missing files gracefully |
| `vault_write` | Write a file with optional frontmatter merging; creates parent dirs |
| `vault_batch_frontmatter_update` | Update YAML frontmatter fields on multiple files without touching body content |
| `vault_search` | Full-text search across vault files (uses ripgrep if available, falls back to Python) |
| `vault_search_frontmatter` | Query the in-memory frontmatter index by field value, substring, or field existence |
| `vault_list` | List directory contents with recursion depth, glob filtering, and file/dir toggles |
| `vault_move` | Move or rename a file or directory within the vault |
| `vault_delete` | Soft-delete a file by moving it to `.trash/` (requires explicit confirmation) |

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Obsidian vault (any directory of markdown files)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (only needed for remote access)
- A domain managed by Cloudflare (only needed for remote access)

## Quick Start

### Local development

```bash
# Clone and enter the project
git clone https://github.com/yourname/obsidian-web-mcp.git
cd obsidian-web-mcp

# Generate auth tokens
export VAULT_MCP_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
export VAULT_OAUTH_CLIENT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Point at your vault
export VAULT_PATH="$HOME/Obsidian/MyVault"

# Run the server
uv run vault-mcp
```

The server starts on port 8420 by default. It serves MCP over Streamable HTTP at `/mcp/`.

## Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VAULT_PATH` | Yes | `~/Obsidian/MyVault` | Absolute path to your Obsidian vault directory |
| `VAULT_MCP_TOKEN` | Yes | (none) | 256-bit bearer token for authenticating MCP requests |
| `VAULT_MCP_PORT` | No | `8420` | Port the HTTP server listens on |
| `VAULT_MCP_HOSTNAME` | For remote | (none) | Public tunnel hostname; added to the DNS-rebinding allow-list so remote requests are accepted |
| `VAULT_OAUTH_CLIENT_ID` | No | `vault-mcp-client` | OAuth 2.0 client ID for Claude integration |
| `VAULT_OAUTH_CLIENT_SECRET` | Yes | (none) | OAuth 2.0 client secret for Claude integration |

Generate tokens with: `python -c "import secrets; print(secrets.token_hex(32))"`

## Connecting to Claude

The Claude desktop and mobile apps can connect to remote MCP servers via OAuth.

1. Start the server (locally or behind a tunnel)
2. Open Claude and go to **Settings > Integrations > Add Integration**
3. Enter your server URL (e.g. `https://vault-mcp.yourdomain.com`)
4. Enter the OAuth client ID and client secret you configured
5. Claude will discover the OAuth endpoints automatically and open a browser window
6. The server auto-approves the authorization (single-user model) and redirects back; Claude then exchanges the code for a bearer token by presenting the client secret you configured
7. Claude now has access to all nine vault tools -- on desktop and mobile

For local-only use (no tunnel), point Claude at `http://localhost:8420`.

## Remote Access with Cloudflare Tunnel

To make the server accessible from anywhere:

```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared

# Set your desired hostname and run the interactive setup
export VAULT_MCP_HOSTNAME="vault-mcp.yourdomain.com"
./scripts/setup-tunnel.sh
```

The script authenticates with Cloudflare, creates a tunnel, writes the config, and sets up the DNS record. You will need a domain managed by Cloudflare.

The `VAULT_MCP_HOSTNAME` you exported above is also read by the server: it adds your tunnel hostname to the MCP library's DNS-rebinding allow-list so requests from your domain are accepted. Make sure the same value is set in the server's environment (the launchd plist below passes it through). No source edits required.

## Production Deployment (macOS)

For always-on operation, use launchd to run both the MCP server and the Cloudflare Tunnel as persistent background services that start at login and restart on failure.

### 1. Edit the plist templates

```bash
cp scripts/launchd/com.example.vault-mcp.plist ~/Library/LaunchAgents/
cp scripts/launchd/com.example.cloudflared-vault.plist ~/Library/LaunchAgents/
```

Open each plist and replace the placeholder tokens:
- `REPLACE_WITH_UV_PATH` -- path to `uv` binary (run `which uv`)
- `REPLACE_WITH_PROJECT_PATH` -- absolute path to this project directory
- `REPLACE_WITH_VAULT_PATH` -- absolute path to your Obsidian vault
- `REPLACE_WITH_TOKEN` -- your `VAULT_MCP_TOKEN` value
- `REPLACE_WITH_OAUTH_SECRET` -- your `VAULT_OAUTH_CLIENT_SECRET` value
- `REPLACE_WITH_HOSTNAME` -- your public tunnel hostname (e.g. `vault-mcp.yourdomain.com`); leave empty for local-only use
- `REPLACE_WITH_HOME` -- your home directory (e.g. `/Users/yourname`)
- `REPLACE_WITH_CLOUDFLARED_PATH` -- path to `cloudflared` binary (run `which cloudflared`)

### 2. Load the services

```bash
launchctl load ~/Library/LaunchAgents/com.example.vault-mcp.plist
launchctl load ~/Library/LaunchAgents/com.example.cloudflared-vault.plist
```

Both services are configured with `RunAtLoad` (start at login) and `KeepAlive` (restart on failure). They will survive reboots.

### 3. Verify

```bash
# Check both services are running
launchctl list | grep vault

# Test the server responds
curl -s http://localhost:8420/.well-known/oauth-authorization-server

# Check logs
tail -f ~/Library/Logs/vault-mcp-error.log
```

## Production Deployment (Linux / systemd + Tailscale Funnel)

For a Debian/Ubuntu VPS, run the server and the Obsidian Sync CLI as a dedicated
`obsidian` system user via hardened systemd units, exposed through Tailscale Funnel.

1. Create the `obsidian` user and layout (`/srv/obsidian/vault`, `/opt/obsidian-web-mcp`).
2. Install Python 3.12 via `uv` (pin `UV_PYTHON_INSTALL_DIR=/opt/obsidian-runtime/python`) and `uv sync`.
3. Put secrets in `/etc/vault-mcp/env` (root-owned `0600`): `VAULT_MCP_TOKEN`,
   `VAULT_OAUTH_CLIENT_SECRET`, `VAULT_OAUTH_CLIENT_ID`, `VAULT_PATH=/srv/obsidian/vault`,
   `VAULT_MCP_PORT=8420`, `VAULT_MCP_HOSTNAME=<your-host>.ts.net`.
4. Install the unit templates from `scripts/systemd/`, then `systemctl enable --now vault-mcp obsidian-sync`.
5. Expose via Funnel: `tailscale funnel --bg --https=443 127.0.0.1:8420`.

The server binds `127.0.0.1` only; Funnel is the sole public ingress. SSH should be
restricted to the Tailscale interface and a default-deny host firewall applied.

## Obsidian Sync Compatibility

The server coexists with Obsidian Sync (or any file-based sync mechanism) without conflict. All writes use atomic file replacement (`write-to-temp-then-rename`), which means:

- Obsidian never sees a half-written file
- If Sync and the MCP server write to the same file simultaneously, the last write wins (standard filesystem semantics) but neither write is corrupted
- The frontmatter index watches for filesystem changes via `watchdog` and updates automatically when Sync brings in new files

## Development

### Running tests

```bash
uv run pytest tests/ -v
```

Tests use temporary directories and never touch your real vault.

### Project structure

```
src/obsidian_vault_mcp/
    auth.py                 # Bearer token middleware (Starlette)
    config.py               # Environment variable configuration
    frontmatter_index.py    # In-memory YAML frontmatter index with filesystem watcher
    models.py               # Pydantic input validation models
    oauth.py                # OAuth 2.0 authorization code flow with PKCE
    server.py               # FastMCP server setup, tool registration, entry point
    vault.py                # Core filesystem operations (path security, atomic writes)
    tools/
        manage.py           # list, move, delete tools
        read.py             # read, batch_read tools
        search.py           # full-text search, frontmatter search tools
        write.py            # write, batch_frontmatter_update tools
tests/
    conftest.py             # Shared fixtures (temp vault with sample files)
    test_frontmatter.py     # Frontmatter index and query tests
    test_tools.py           # Integration tests for tool functions
    test_vault.py           # Path resolution and file operation tests
scripts/
    setup-tunnel.sh         # Interactive Cloudflare Tunnel setup
    launchd/                # macOS launchd plist templates
```

## License

MIT -- see [LICENSE](LICENSE).
