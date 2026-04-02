# LrCEmbedIndex

A Lightroom Classic plugin and Python server for AI-powered photo indexing and semantic search. Supports **Ollama** (local), **OpenAI**, and **Claude/Voyage AI** backends for vision and embedding models.

## Overview

- **Lightroom Classic Plugin** generates JPEG thumbnails and extracts EXIF metadata from your photo library, sending them to a local Python server.
- **Python Server** describes each photo using a vision model, generates vector embeddings, and stores everything in ChromaDB for fast semantic search.
- **Multi-backend support** — choose between Ollama, OpenAI, and Claude for vision; Ollama, OpenAI, and Voyage AI for embedding. Vision and embedding backends can be mixed independently.

## Architecture

```
Lightroom Classic
  ├── Generate Index         ──►  POST /index    (JPEG + EXIF + image path)
  ├── Search Photo           ──►  POST /search   (query text + relevance + max)
  ├── Describe Selected Photo──►  POST /describe (JPEG + EXIF, vision only)
  ├── Show Index Stats       ──►  GET  /stats    (DB & metadata statistics)
  └── Settings UI            ──►  POST /settings (all configuration)
                                   │
                              Python Server (Flask, port 8600)
                                   │
                         ┌─────────┼─────────┐
                         ▼         ▼         ▼
               Ollama/OpenAI/ ChromaDB   Metadata
               Claude/Voyage  (per-model  (sharded
               (vision+embed) vector DB)  JSON files)
```

## Project Structure

```
LrCEmbedIndex/
├── lrcembedindex.lrplugin/
│   ├── Info.lua                 # Plugin manifest
│   ├── GenerateIndex.lua        # Menu: index all photos in selected folder
│   ├── BatchDescribe.lua        # Menu: vision-only batch processing
│   ├── SearchPhoto.lua          # Menu: semantic search with collection results
│   ├── DescribePhoto.lua        # Menu: describe a single selected photo
│   ├── ShowStats.lua            # Menu: show ChromaDB & metadata statistics
│   ├── PluginInfoProvider.lua   # Settings UI
│   └── dkjson.lua               # JSON library
├── server/
│   ├── server.py                # Flask app entry point
│   ├── routes.py                # API route handlers
│   ├── config.py                # Configuration management
│   ├── vision.py                # Vision model integration (Ollama/OpenAI/Claude)
│   ├── embedding.py             # Embedding model integration (Ollama/OpenAI/Voyage AI)
│   ├── vectorstore.py           # ChromaDB vector store with relevance filtering
│   ├── metadata.py              # Sharded JSON metadata storage
│   ├── helpers.py               # EXIF-to-text conversion, utilities
│   ├── ollama_lock.py           # Threading lock for Ollama call serialization
│   ├── requirements.txt         # Python dependencies
│   └── requirements-lock.txt    # Pinned dependency versions
├── .github/workflows/lint.yml  # CI: Python linting
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── SECURITY.md
```

## Prerequisites

- Python 3.11+
- Adobe Lightroom Classic
- **For Ollama mode:** [Ollama](https://ollama.ai/) running with models pulled:
  - `qwen3.5` (vision) and `nomic-embed-text` (embedding), or your preferred models
- **For OpenAI mode:** An OpenAI API key ([get one here](https://platform.openai.com/api-keys))
- **For Claude mode:** An Anthropic API key ([get one here](https://console.anthropic.com/settings/keys))
- **For Voyage AI mode:** A Voyage AI API key ([get one here](https://dash.voyageai.com/api-keys))

## Setup

### Python Server

```bash
# Create and activate conda environment
conda create -n lrcembedindex python=3.11 -y
conda activate lrcembedindex

# Install dependencies
cd server
pip install -r requirements.txt

# Start the server
python server.py
```

The server runs on port 8600 by default.

### Lightroom Plugin

1. Open Lightroom Classic
2. Go to **File > Plug-in Manager**
3. Click **Add** and select the `lrcembedindex.lrplugin` folder
4. In the plugin settings, configure:

   **General Settings:**
   - **Python Server URL** (default: `http://localhost:8600`)
   - **Index & Metadata Folder** — where metadata and ChromaDB data are stored
   - **Search Max Results** — max candidates from vector DB per search (default: 10)
   - **Relevance Threshold** — slider (0–100) controlling how strict the relevance filter is

   **Vision Model:**
   - Choose between **Ollama**, **OpenAI API**, or **Claude API**
   - Ollama: endpoint URL + model name (default: `qwen3.5`)
   - OpenAI: API key + model name (default: `gpt-4o`)
   - Claude: API key + model name (default: `claude-sonnet-4-6`)

   **Embedding Model:**
   - Choose between **Ollama**, **OpenAI API**, or **Voyage AI**
   - Ollama: endpoint URL + model name (default: `nomic-embed-text`)
   - OpenAI: API key + model name (default: `text-embedding-3-small`)
   - Voyage AI: API key + model name (default: `voyage-3.5`)

5. Click **Save & Apply Settings**

## Usage

### Generate Index

1. Select a folder in Lightroom's Library module
2. Go to **Library > Plug-in Extras > Generate Index**
3. All photos in the selected folder will be processed:
   - JPEG thumbnail generated and sent to the server
   - EXIF metadata (camera, lens, settings, GPS, keywords, etc.) extracted and sent
   - Vision model describes the image
   - EXIF text is appended to the description
   - Combined text is embedded and stored in ChromaDB
4. Photos already indexed with the same vision and embedding models are automatically skipped

### Search Photo

1. Go to **Library > Plug-in Extras > Search Photo**
2. Enter a natural language description (e.g., "sunset over the ocean", "portrait with bokeh", "Leica 50mm lens")
3. Adjust **Max results** and **Relevance** slider directly in the search dialog (values are remembered between searches)
4. Results are filtered by a three-stage relevance algorithm:
   - **Absolute distance threshold** — removes clearly irrelevant matches
   - **Gap detection** — finds natural boundaries between relevant and noise
   - **Relative-to-best filtering** — keeps only results in the same neighbourhood as the top match
5. Matching photos are collected into a **"LrCEmbedIndex Search Results"** collection and displayed in the Library module
6. Results are added in score order (best match first). To see them ranked by relevance, set the Sort order to **"Custom Order"** in the Library toolbar. Lightroom remembers this setting per collection, so you only need to set it once.

### Describe Selected Photo

1. Select a **single** photo in the Library module
2. Go to **Library > Plug-in Extras > Describe Selected Photo**
3. The plugin sends the photo to the vision model and displays the AI-generated description
4. If the photo was previously indexed with the same vision model, the cached description is returned instantly without calling the API

### Show Index Stats

1. Go to **Library > Plug-in Extras > Show Index Stats**
2. Displays a summary of:
   - Current configuration (models, endpoints, search settings)
   - Metadata statistics (total files, per-vision-model counts, per-embed-pair counts, date range)
   - ChromaDB vector store statistics (current store count, all stores with vector counts)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | POST | Index a photo. Body: JPEG data. Headers: `X-Image-Path`, `X-Exif-Data` (percent-encoded JSON) |
| `/search` | POST | Search photos. Body: `{"query": "...", "max_results": 10, "relevance": 50}` |
| `/describe` | POST | Describe a single photo (vision only, uses cache). Body: JPEG data. Headers: `X-Image-Path`, `X-Exif-Data` |
| `/stats` | GET | Get metadata, ChromaDB, and config statistics |
| `/settings` | POST | Update config. Body: JSON with any config keys |

## Data Storage

Metadata is stored in a sharded folder structure to handle 10,000+ photos efficiently. ChromaDB is stored per embedding model so switching models doesn't corrupt the vector space:

```
<index_folder>/
├── metadata/
│   ├── 0a/
│   │   └── 0a3f...e7.json          # per-photo metadata
│   ├── 1b/
│   │   └── 1b7d...f3.json
│   └── ...                          # up to 256 shard directories
├── chromadb/
│   ├── ollama_nomic-embed-text/     # ChromaDB for Ollama embeddings
│   ├── openai_text-embedding-3-small/  # ChromaDB for OpenAI embeddings
│   └── voyage_voyage-3.5/          # ChromaDB for Voyage AI embeddings
└── lrcembedindex_config.json        # server config
```

Each metadata JSON stores results from multiple models so switching backends doesn't lose prior work:

```json
{
  "image_path": "/path/to/IMG_1234.DNG",
  "vision_results": {
    "ollama:qwen3.5": {
      "vision_description": "A motorcycle racer ...",
      "exif": { "cameraModel": "LEICA M11-P", ... },
      "full_description": "A motorcycle racer ...\n\n--- Photo Metadata ---\n...",
      "processed_at": "2026-03-15T14:22:08Z",
      "embeddings": {
        "ollama:nomic-embed-text": {
          "embedding": [0.012, -0.034, ...],
          "description_used": "A motorcycle racer ...",
          "processed_at": "2026-03-15T14:22:09Z"
        }
      }
    },
    "openai:gpt-4o": { ... }
  }
}
```

Key fields:
- `vision_results.<model>` — cached output per vision model (description, EXIF, timestamp)
- `vision_results.<model>.embeddings.<model>` — cached embedding per vision+embed pair
- Indexing skips the vision API call if the same vision model result is cached
- Indexing skips the embedding API call if the same vision+embed pair is cached
- ChromaDB is always updated to stay in sync with the current model pair

## Available Models

All model names are configurable in the plugin settings UI. Here are reference links to find available models for each provider:

### Vision Models

| Provider | Default Model | Model List |
|----------|--------------|------------|
| Ollama | `qwen3.5` | [Ollama Library](https://ollama.com/library) — filter by "vision" capability |
| OpenAI | `gpt-4o` | [OpenAI Models](https://platform.openai.com/docs/models) — look for models with "vision" or "image input" support |
| Claude | `claude-sonnet-4-6` | [Anthropic Models](https://docs.anthropic.com/en/docs/about-claude/models) — all Claude 3+ models support vision |

### Embedding Models

| Provider | Default Model | Model List |
|----------|--------------|------------|
| Ollama | `nomic-embed-text` | [Ollama Library](https://ollama.com/library) — filter by "embedding" capability |
| OpenAI | `text-embedding-3-small` | [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings#embedding-models) |
| Voyage AI | `voyage-3.5` | [Voyage AI Models](https://docs.voyageai.com/docs/embeddings) — includes domain-specific models for code, law, and finance |

## Privacy Notice

- **Ollama (default):** All processing is entirely local. No photo data leaves your machine.
- **OpenAI / Claude / Voyage AI:** When using cloud backends, your photo images (for vision) and/or description text (for embedding) are transmitted to third-party API servers. Review each provider's data handling policies:
  - [OpenAI Usage Policies](https://openai.com/policies/usage-policies)
  - [Anthropic Usage Policy](https://www.anthropic.com/policies/usage-policy)
  - [Voyage AI Terms of Service](https://www.voyageai.com/terms-of-service)
- **Local storage only:** All metadata, embeddings, and configuration are stored locally on your machine. No telemetry or analytics are collected.
- **API keys** are stored in Lightroom plugin preferences and kept in-memory on the server. They are never written to config files on disk.

Users are responsible for complying with the terms of service of their chosen API providers.

## License

MIT

This project includes [dkjson](http://dkolf.de/dkjson-lua/) by David Heiko Kolf, licensed under MIT.
