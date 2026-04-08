# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LrCEmbedIndex, please report it responsibly.

**Email:** Open a private issue on GitHub or contact the maintainer directly.

**Do not** open a public GitHub issue for security vulnerabilities.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- Acknowledgment within 48 hours
- Fix or mitigation within 7 days for critical issues

## Security Considerations

### API Keys

- API keys (OpenAI, Claude, Voyage AI) are encrypted at rest using Fernet symmetric encryption and stored in `lrcembedindex_config.json` with an `ENC:` prefix.
- The encryption key is stored in `~/.lrcembedindex_key` with restrictive file permissions (0600).
- API keys are redacted from `/stats` and `GET /settings` responses (masked to last 4 characters).
- The `/settings/sync` endpoint returns **unmasked** API keys for Lightroom plugin synchronization. See Docker security below.
- API keys are **never** logged.

### Data Transmission

- When using **Ollama** (default), all processing is local — no data leaves your machine.
- When using **OpenAI**, **Claude**, or **Voyage AI** backends, photo images and/or description text are sent to third-party API servers. See [PRIVACY.md](PRIVACY.md).
- GPS data is stripped from cloud API requests by default (`strip_gps_for_cloud`).

### Local Server

- The Python server binds to `localhost:8600` by default and is not exposed to the network.
- No authentication is required for the local server API (it is intended for local use only).
- Cross-origin requests are restricted to localhost origins.

### Docker / Network Deployment

When running the server in Docker with `--host 0.0.0.0`, additional security considerations apply:

- **No authentication**: The server has no authentication mechanism. Anyone on the network can access all endpoints, including `/settings/sync` which returns unmasked API keys.
- **Restrict network access**: Bind to a specific interface or use firewall rules to limit access. See [docker/README.md](docker/README.md) for configuration examples.
- **Encryption key persistence**: The Docker setup uses a named volume (`lrcembedindex-key`) to persist the Fernet encryption key across container rebuilds. Do not share this volume with untrusted containers.
