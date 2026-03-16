# LrCEmbedIndex

A Lightroom Classic plugin and Python server for AI-powered photo indexing and semantic search. Supports both **Ollama** (local) and **OpenAI API** backends for vision and embedding models.

## Overview

- **Lightroom Classic Plugin** generates JPEG thumbnails and extracts EXIF metadata from your photo library, sending them to a local Python server.
- **Python Server** describes each photo using a vision model, generates vector embeddings, and stores everything in ChromaDB for fast semantic search.
- **Dual backend support** — toggle between Ollama and OpenAI independently for vision and embedding.

## Architecture

```
Lightroom Classic
  ├── Generate Index  ──►  POST /index   (JPEG + EXIF + image path)
  ├── Search Photo    ──►  POST /search  (query text)
  └── Settings UI     ──►  POST /settings (all configuration)
                               │
                          Python Server (Flask, port 8600)
                               │
                     ┌─────────┼─────────┐
                     ▼         ▼         ▼
              Ollama/OpenAI  ChromaDB   Metadata
              (vision +      (per-model  (sharded
               embed)        vector DB)  JSON files)
```

## Project Structure

```
LrCEmbedIndex/
├── lrcembedindex.lrplugin/
│   ├── Info.lua                 # Plugin manifest
│   ├── GenerateIndex.lua        # Menu: index all photos in selected folder
│   ├── SearchPhoto.lua          # Menu: semantic search dialog
│   ├── PluginInfoProvider.lua   # Settings UI
│   └── dkjson.lua               # JSON library
├── server/
│   ├── server.py                # Flask app entry point
│   ├── routes.py                # API route handlers
│   ├── config.py                # Configuration management
│   ├── vision.py                # Vision model integration (Ollama/OpenAI)
│   ├── embedding.py             # Embedding model integration (Ollama/OpenAI)
│   ├── vectorstore.py           # ChromaDB vector store with relevance filtering
│   ├── metadata.py              # Sharded JSON metadata storage
│   ├── helpers.py               # EXIF-to-text conversion, utilities
│   └── requirements.txt         # Python dependencies
├── README.md
└── LICENSE
```

## Prerequisites

- Python 3.11+
- Adobe Lightroom Classic
- **For Ollama mode:** [Ollama](https://ollama.ai/) running with models pulled:
  - `qwen3.5` (vision) and `nomic-embed-text` (embedding), or your preferred models
- **For OpenAI mode:** An OpenAI API key ([get one here](https://platform.openai.com/api-keys))

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
   - Toggle between **Ollama** and **OpenAI API**
   - Ollama: endpoint URL + model name (default: `qwen3.5`)
   - OpenAI: API key (uses `gpt-4o`)

   **Embedding Model:**
   - Toggle between **Ollama** and **OpenAI API**
   - Ollama: endpoint URL + model name (default: `nomic-embed-text`)
   - OpenAI: API key (uses `text-embedding-3-small`)

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
3. Results are filtered by a three-stage relevance algorithm:
   - **Absolute distance threshold** — removes clearly irrelevant matches
   - **Gap detection** — finds natural boundaries between relevant and noise
   - **Relative-to-best filtering** — keeps only results in the same neighbourhood as the top match
4. Adjust the **Relevance Threshold** slider in settings to tune strictness

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | POST | Index a photo. Body: JPEG data. Headers: `X-Image-Path`, `X-Exif-Data` (percent-encoded JSON) |
| `/search` | POST | Search photos. Body: `{"query": "..."}` |
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
│   └── openai_text-embedding-3-small/  # ChromaDB for OpenAI embeddings
└── lrcembedindex_config.json        # server config
```

Each metadata JSON contains:
- `image_path` — original file path
- `vision_description` — raw vision model output
- `description` — combined vision + EXIF text (used for embedding)
- `exif` — full EXIF data from Lightroom
- `embedding` — vector embedding
- `vision_model` / `embed_model` — model labels (e.g., `ollama:qwen3.5`, `openai:gpt-4o`)
- `processed_at` — UTC timestamp

## License

MIT
