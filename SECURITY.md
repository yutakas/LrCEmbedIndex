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

- API keys (OpenAI, Claude, Voyage AI) are stored only in Lightroom plugin preferences and in-memory on the Python server at runtime.
- API keys are **never** written to config files on disk (filtered by `config.py`).
- API keys are **never** logged or exposed via the `/stats` endpoint.

### Data Transmission

- When using **Ollama** (default), all processing is local — no data leaves your machine.
- When using **OpenAI**, **Claude**, or **Voyage AI** backends, photo images and/or description text are sent to third-party API servers. See the [Privacy Notice](#privacy-notice) in README.md.

### Local Server

- The Python server binds to `localhost:8600` by default and is not exposed to the network.
- No authentication is required for the local server API (it is intended for local use only).
