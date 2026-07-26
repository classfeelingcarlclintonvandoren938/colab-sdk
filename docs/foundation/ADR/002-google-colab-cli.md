# ADR-002: google-colab-cli as Backend

**Status:** Accepted

---

## Context

The project needed a way to interact with Google Colab programmatically: provision VMs, execute code, transfer files, and manage session lifecycle.

Four approaches were considered:
1. Manual bootstrap (user pastes code into a Colab notebook cell)
2. Google Colab MCP Server (official MCP protocol)
3. Reverse-engineered Colab API (browser automation, cookie scraping)
4. `google-colab-cli` (official Google CLI tool)

## Decision

Use **`google-colab-cli`** as the sole backend for all Colab interactions. It becomes a required dependency of `colab-client`.

```python
# colab.client delegates to:
#   colab new --gpu T4
#   colab exec -s <name> -f <file>
#   colab upload -s <name> ...
#   colab stop -s <name>
```

## Rationale

- **Official Google tool**: Maintained by Google, guaranteed to work with Colab's API. No ToS risk.
- **No reverse engineering**: The CLI handles authentication (OAuth2/ADC), keep-alive (60s ping via TFE tunnel), session management, and file transfer. Building any of this ourselves would be months of work.
- **No browser automation**: Eliminates Selenium, Playwright, cookie scraping, and all associated brittleness.
- **pip installable**: `pip install google-colab-cli` is a standard Python dependency.
- **Full feature set**: `colab new`, `colab exec`, `colab upload`, `colab download`, `colab install`, `colab console`, `colab stop` — covers every interaction we need.
- **Headless**: Works without a browser. No notebook cell paste required.

## Trade-offs

- **Platform limitation**: `google-colab-cli` currently supports Linux and macOS only. Windows is not supported. This is a Colab CLI limitation, not ours.
- **Extra dependency**: Users must have `google-colab-cli` installed. However, it's a single `pip install` and handles auth itself.
- **Abstraction leak**: The existence of the CLI is an implementation detail. The SDK's `ColabSession` wrapper ensures users never call the CLI directly.

## Consequences

- `google-colab-cli` is listed as a required dependency in `pyproject.toml`.
- The `ColabSession` component wraps CLI commands via `subprocess`. No direct HTTP calls to Google APIs.
- No Cloudflare Tunnel, ngrok, or other network infrastructure is needed — the CLI manages connectivity.
- Authentication is delegated to the CLI's OAuth2 flow (remote copy-paste, same as `gcloud auth application-default login`).
- Keep-alive is managed by the CLI's background daemon.

## Alternatives Considered

**Manual bootstrap (user pastes cell).** Rejected because it requires manual user action, creating friction. The CLI automates the entire flow.

**Colab MCP Server.** Rejected because it requires `uv` as a dependency and is designed for AI agent assistance, not programmatic SDK use. Its `--enable-runtime` mode is limited to a single `execute_code` tool.

**Reverse-engineered Colab API.** Rejected due to ToS violation risk, ongoing maintenance burden, and brittleness. Google actively blocks non-official access methods (see: colab-ssh deprecation, internal API changes).

## References

- CONSTITUTION.md, Rule 3 (Official Integrations First)
- CONSTITUTION.md, Rule 5 (Smart Client)
- Google Colab CLI documentation: https://github.com/googlecolab/google-colab-cli
