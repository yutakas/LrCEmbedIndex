# Changelog

All notable changes to LrCEmbedIndex will be documented in this file.

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
