# Changelog

All notable changes to LrCEmbedIndex will be documented in this file.

## [1.2.0] - 2026-04-07

### Added
- **Standalone server mode** — server runs independently without Lightroom plugin
- **Settings Web UI** (`/settings-ui`) — configure all models, API keys, and patrol settings from the browser
- **Auto patrol** — background worker scans configured folders and indexes new/changed photos automatically
- **Encrypted API key storage** — API keys encrypted at rest using Fernet symmetric encryption
- **Docker deployment** — Dockerfile, docker-compose.yml, and rebuild.sh for containerized deployment
- **Content hash deduplication** — SHA-256 content hash used as ChromaDB document ID to prevent duplicates
- **X-Content-Hash header** — Lightroom plugin computes and sends content hash for remote Docker scenarios
- **Photo detail hash display** — content hash shown on photo detail web page
- **PHOTO_FOLDER volume mount** — configurable photo folder for Docker auto patrol
- **`--host` / `--port` CLI args** — configurable bind address for Docker (0.0.0.0) vs local (127.0.0.1)
- **Patrol status auto-refresh** — settings UI refreshes patrol status every 60 seconds
- **"Load from Server" button** — Lightroom plugin can pull settings from the server

### Changed
- Index folder setting removed from Lightroom plugin UI (now configured via web Settings UI only)
- API keys encrypted before writing to config file on disk
- Patrol worker gracefully skips unsupported RAW formats (e.g. Nikon Z9/Z8 compressed NEF)

### Fixed
- Division by zero in EXIF extraction when exposure time is 0
- Patrol status stuck on "idle" after pressing Start
- Race condition in Fernet key initialization with double-checked locking

## [1.1.0] - 2026-03-30

### Added
- **MCP server** — Model Context Protocol integration for Claude and other MCP clients
- MCP tools: `search_photos`, `get_photo_info`, `get_stats`

## [1.0.0] - 2026-03-23

### Added
- Initial release of LrCEmbedIndex
- Lightroom Classic plugin with five menu items:
  - **Generate Index** — batch index all photos in a folder (vision + embedding)
  - **Batch Describe (Vision Only)** — batch vision descriptions without embedding
  - **Search Photo** — semantic search with relevance filtering and collection results
  - **Describe Selected Photo** — view all cached descriptions for a single photo
  - **Show Index Stats** — display metadata, ChromaDB, and config statistics
- Python Flask server with REST API endpoints (`/index`, `/search`, `/describe`, `/stats`, `/settings`)
- Multi-backend support:
  - Vision: Ollama (local), OpenAI API, Claude API (Anthropic)
  - Embedding: Ollama (local), OpenAI API, Voyage AI
- Multi-model metadata caching — switching models preserves all prior results
- Sharded JSON metadata storage for 10,000+ photo scalability
- Per-embedding-model ChromaDB vector stores
- Three-stage relevance filtering (absolute threshold, gap detection, relative-to-best)
- Folder-based photo lookup optimization for search results
- Threading lock for serializing Ollama API calls
- Plugin settings UI with conditional visibility per backend
- Configurable HTTP timeouts (1000s default)
