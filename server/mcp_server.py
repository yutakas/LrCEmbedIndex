"""MCP server for searching indexed photos from Claude Chat/Code/Desktop.

Exposes three tools:
  - search_photos: semantic search with optional thumbnail previews
  - get_photo_info: metadata + thumbnail for a specific photo
  - get_stats: index statistics

Requires Python 3.10+ and the `mcp` package (pip install mcp).

Usage (stdio transport):
    python mcp_server.py

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "photo-search": {
          "command": "python3",
          "args": ["/path/to/LrCEmbedIndex/server/mcp_server.py"]
        }
      }
    }
"""

import asyncio
import base64
import json
import logging
import os
import sys

# Ensure server/ modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from config import config, load_config, VERSION
from vectorstore import init_chromadb, search_photos as vs_search, get_chromadb_stats
from embedding import get_embedding
from metadata import (
    load_photo_metadata, load_thumbnail,
    count_metadata_files, collect_metadata_stats,
)

# Log to stderr — stdout is the MCP stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

mcp = FastMCP("LrCEmbedIndex", version=VERSION)

_initialized = False


def _ensure_init():
    """Load config and initialize ChromaDB on first use."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    if load_config():
        if config["index_folder"]:
            init_chromadb()
            logger.info(f"MCP: {count_metadata_files()} metadata files found")
    else:
        logger.warning("MCP: No config found — index not loaded")


def _strip_embeddings(meta: dict) -> dict:
    """Return a copy of metadata with embedding vectors removed."""
    import copy
    clean = copy.deepcopy(meta)
    for v_data in clean.get("vision_results", {}).values():
        for e_data in v_data.get("embeddings", {}).values():
            e_data.pop("embedding", None)
    return clean


def _thumbnail_content(image_path: str) -> ImageContent | None:
    """Load thumbnail and return as ImageContent, or None."""
    thumb_bytes = load_thumbnail(image_path)
    if not thumb_bytes:
        return None
    return ImageContent(
        type="image",
        data=base64.b64encode(thumb_bytes).decode("ascii"),
        mimeType="image/jpeg",
    )


@mcp.tool()
async def search_photos(
    query: str,
    max_results: int = 0,
    relevance: int = -1,
    include_thumbnails: bool = True,
) -> list[TextContent | ImageContent]:
    """Search indexed photos by natural language query.

    Args:
        query: Natural language search query (e.g. "sunset over mountains")
        max_results: Maximum number of results (0 = use server default)
        relevance: Relevance filter 0-100 (-1 = use server default).
                   0 = show all, 100 = only very close matches.
        include_thumbnails: Include thumbnail images in results (default true)
    """
    _ensure_init()

    if max_results <= 0:
        max_results = config.get("search_max_results", 10)
    if relevance < 0:
        relevance = config.get("search_relevance", 50)

    emb = await asyncio.to_thread(get_embedding, query)
    if not emb:
        return [TextContent(type="text", text="Failed to generate query embedding. Is the embedding model running?")]

    matches = await asyncio.to_thread(vs_search, emb, n_results=max_results, relevance=relevance)

    if not matches:
        return [TextContent(type="text", text="No matching photos found.")]

    content: list[TextContent | ImageContent] = []
    for i, m in enumerate(matches):
        content.append(TextContent(
            type="text",
            text=json.dumps({
                "result": i + 1,
                "path": m["path"],
                "filename": os.path.basename(m["path"]),
                "description": m["description"],
                "distance": round(m["distance"], 4),
            }, indent=2),
        ))
        if include_thumbnails:
            img = await asyncio.to_thread(_thumbnail_content, m["path"])
            if img:
                content.append(img)

    return content


@mcp.tool()
async def get_photo_info(
    path: str,
    include_thumbnail: bool = True,
) -> list[TextContent | ImageContent]:
    """Get metadata for a specific photo by file path.

    Args:
        path: Full file path of the photo
        include_thumbnail: Include the thumbnail image (default true)
    """
    _ensure_init()

    meta = await asyncio.to_thread(load_photo_metadata, path)
    if not meta:
        return [TextContent(type="text", text=f"No metadata found for: {path}")]

    clean = _strip_embeddings(meta)
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(clean, indent=2)),
    ]

    if include_thumbnail:
        img = await asyncio.to_thread(_thumbnail_content, path)
        if img:
            content.append(img)

    return content


@mcp.tool()
async def get_stats() -> str:
    """Return index statistics: metadata counts, model info, ChromaDB stats."""
    _ensure_init()

    meta_stats = await asyncio.to_thread(collect_metadata_stats)
    chroma_stats = await asyncio.to_thread(get_chromadb_stats)

    safe_config = {k: v for k, v in config.items() if "api_key" not in k}

    stats = {
        "metadata": {
            "file_count": await asyncio.to_thread(count_metadata_files),
            "vision_models": meta_stats.get("vision_models", {}),
            "embed_models": meta_stats.get("embed_models", {}),
            "thumbnail_count": meta_stats.get("thumbnail_count", 0),
            "oldest_entry": meta_stats.get("oldest_entry"),
            "newest_entry": meta_stats.get("newest_entry"),
        },
        "chromadb": chroma_stats,
        "config": safe_config,
        "version": VERSION,
    }
    return json.dumps(stats, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
