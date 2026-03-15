# LrCEmbedIndex

A Lightroom Classic plugin and Python server for AI-powered photo indexing and semantic search using Ollama vision and embedding models.

## Overview

- **Lightroom Classic Plugin** generates JPEG thumbnails and extracts EXIF metadata from your photo library, sending them to a local Python server.
- **Python Server** uses Ollama to describe each photo (via `qwen3.5` vision model), generates vector embeddings (via `nomic-embed-text`), and stores everything in ChromaDB for fast semantic search.

## Architecture

```
Lightroom Classic
  ├── Generate Index  ──►  POST /index   (JPEG + EXIF + image path)
  ├── Search Photo    ──►  POST /search  (query text)
  └── Settings UI     ──►  POST /settings (index folder, ollama URL)
                               │
                          Python Server (Flask, port 8600)
                               │
                     ┌─────────┼─────────┐
                     ▼         ▼         ▼
                  Ollama    ChromaDB   Metadata
                (vision +  (vector    (sharded
                 embed)     store)     JSON files)
```

## Project Structure

```
LrCEmbedIndex/
├── lrcembedindex.lrplugin/
│   ├── Info.lua                 # Plugin manifest
│   ├── GenerateIndex.lua        # Menu: index all photos in selected folder
│   ├── SearchPhoto.lua          # Menu: semantic search dialog
│   ├── PluginInfoProvider.lua   # Settings UI (index folder, ollama URL)
│   └── dkjson.lua               # JSON library
├── server/
│   ├── server.py                # Python Flask REST server
│   └── requirements.txt         # Python dependencies
└── README.md
```

## Prerequisites

- [Ollama](https://ollama.ai/) running with the following models pulled:
  - `qwen3.5` (vision model for image description)
  - `nomic-embed-text` (embedding model for vector search)
- Python 3.11+
- Adobe Lightroom Classic

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
4. In the plugin settings panel, configure:
   - **Python Server URL** (default: `http://localhost:8600`)
   - **Ollama Endpoint** (default: `http://localhost:11434`)
   - **Index & Metadata Folder** — where metadata and ChromaDB data are stored
5. Click **Save & Apply Settings**

## Usage

### Generate Index

1. Select a folder in Lightroom's Library module
2. Go to **Library > Plug-in Extras > Generate Index**
3. All photos in the selected folder will be processed:
   - JPEG thumbnail generated and sent to the server
   - EXIF metadata (camera, lens, settings, GPS, keywords, etc.) extracted and sent
   - Ollama vision model describes the image
   - EXIF text is appended to the description
   - Combined text is embedded and stored in ChromaDB

Photos already indexed with the same models are automatically skipped.

### Search Photo

1. Go to **Library > Plug-in Extras > Search Photo**
2. Enter a natural language description (e.g., "sunset over the ocean", "portrait with bokeh", "Canon 70-200mm")
3. The top 10 matching photos are returned with file paths and descriptions

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | POST | Index a photo. Body: JPEG data. Headers: `X-Image-Path`, `X-Exif-Data` |
| `/search` | POST | Search photos. Body: `{"query": "..."}` |
| `/settings` | POST | Update config. Body: `{"index_folder": "...", "ollama_url": "..."}` |

## Data Storage

Metadata is stored in a sharded folder structure to handle 10,000+ photos efficiently:

```
<index_folder>/
├── metadata/
│   ├── 0a/
│   │   └── 0a3f...e7.json     # per-photo metadata
│   ├── 1b/
│   │   └── 1b7d...f3.json
│   └── ...                     # up to 256 shard directories
├── chromadb/                   # ChromaDB vector store
└── lrcembedindex_config.json   # server config
```

Each metadata JSON contains:
- `image_path` — original file path
- `vision_description` — raw Ollama vision output
- `description` — combined vision + EXIF text (used for embedding)
- `exif` — full EXIF data from Lightroom
- `embedding` — vector embedding
- `vision_model` / `embed_model` — model names used
- `processed_at` — UTC timestamp

## License

MIT
