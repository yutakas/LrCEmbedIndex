import logging
import os
import re

import chromadb

from config import config, get_embed_model_label

logger = logging.getLogger(__name__)

CHROMA_BASE_DIR = "chromadb"

chroma_client = None
chroma_collection = None
_current_embed_label = None


def _sanitize_dir_name(label):
    """Convert a model label like 'ollama:nomic-embed-text' to a safe directory name."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", label)


def get_chroma_path():
    if config["index_folder"]:
        embed_dir = _sanitize_dir_name(get_embed_model_label())
        return os.path.join(config["index_folder"], CHROMA_BASE_DIR, embed_dir)
    return None


def init_chromadb():
    global chroma_client, chroma_collection, _current_embed_label
    chroma_path = get_chroma_path()
    if not chroma_path:
        logger.warning("No index folder set, cannot initialize ChromaDB")
        return
    os.makedirs(chroma_path, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=chroma_path)
    chroma_collection = chroma_client.get_or_create_collection(
        name="photo_index",
        metadata={"hnsw:space": "cosine"},
    )
    _current_embed_label = get_embed_model_label()
    logger.info(f"ChromaDB initialized at {chroma_path}, "
                f"model={_current_embed_label}, "
                f"collection count: {chroma_collection.count()}")


def _ensure_correct_store():
    """Reinitialize if the embed model has changed since last init."""
    global _current_embed_label
    if _current_embed_label != get_embed_model_label():
        init_chromadb()


def get_chromadb_stats():
    """Return stats about all ChromaDB stores in the index folder."""
    stats = {
        "current_model": get_embed_model_label(),
        "current_count": chroma_collection.count() if chroma_collection else 0,
        "current_path": get_chroma_path(),
        "all_stores": [],
    }

    # List all per-model ChromaDB directories
    if config["index_folder"]:
        chroma_base = os.path.join(config["index_folder"], CHROMA_BASE_DIR)
        if os.path.isdir(chroma_base):
            for name in sorted(os.listdir(chroma_base)):
                store_path = os.path.join(chroma_base, name)
                if not os.path.isdir(store_path):
                    continue
                try:
                    client = chromadb.PersistentClient(path=store_path)
                    col = client.get_or_create_collection(
                        name="photo_index",
                        metadata={"hnsw:space": "cosine"},
                    )
                    count = col.count()
                except Exception:
                    count = -1
                stats["all_stores"].append({
                    "model_dir": name,
                    "count": count,
                })

    return stats


def upsert_photo(doc_id, embedding, description, image_path):
    _ensure_correct_store()
    if chroma_collection is None:
        init_chromadb()
    chroma_collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[description],
        metadatas=[{"path": image_path}],
    )


def _relevance_to_params(relevance):
    """Convert the 0-100 relevance slider to filter parameters.

    relevance=0   → max_distance=1.5, gap_ratio=5.0, best_ratio=5.0  (very lenient)
    relevance=50  → max_distance=0.85, gap_ratio=1.8, best_ratio=2.5 (balanced)
    relevance=100 → max_distance=0.2, gap_ratio=1.2, best_ratio=1.5  (very strict)

    Linear interpolation between the endpoints.
    """
    t = relevance / 100.0
    max_distance = 1.5 - t * 1.3       # 1.5 → 0.2
    gap_ratio = 5.0 - t * 3.8          # 5.0 → 1.2
    best_ratio = 5.0 - t * 3.5         # 5.0 → 1.5
    return max_distance, gap_ratio, best_ratio


def _filter_relevant(matches, relevance=None):
    """Filter search results to only include relevant photos.

    Uses the relevance value (0-100 slider) to derive:
      1. Absolute threshold  – drop anything with cosine distance > max_distance
      2. Gap detection       – if distance[i] / distance[i-1] > gap_ratio,
                               there is a natural boundary; cut off there
      3. Relative to best    – drop results whose distance > best * best_ratio
                               (keeps results in the same "neighbourhood" as the
                               top match)

    At least one result is always returned if it passes the absolute threshold.
    """
    if not matches:
        return matches

    if relevance is None:
        relevance = config.get("search_relevance", 50)
    max_distance, gap_ratio, best_ratio = _relevance_to_params(relevance)
    logger.info(f"Relevance slider={relevance} → max_dist={max_distance:.2f}, "
                f"gap_ratio={gap_ratio:.2f}, best_ratio={best_ratio:.2f}")

    # 1. absolute threshold
    filtered = [m for m in matches if m["distance"] <= max_distance]
    if not filtered:
        return []

    # 3. relative to best
    best_dist = filtered[0]["distance"]
    if best_dist > 0:
        cutoff = best_dist * best_ratio
        filtered = [m for m in filtered if m["distance"] <= cutoff]

    # 2. gap detection (distances are sorted ascending from ChromaDB)
    if len(filtered) > 1:
        keep = 1
        for i in range(1, len(filtered)):
            prev = filtered[i - 1]["distance"]
            curr = filtered[i]["distance"]
            if prev > 0 and curr / prev > gap_ratio:
                break
            keep = i + 1
        filtered = filtered[:keep]

    logger.info(f"Relevance filter: {len(matches)} candidates -> {len(filtered)} relevant "
                f"(best={matches[0]['distance']:.3f}, "
                f"worst_kept={filtered[-1]['distance']:.3f})")
    return filtered


def search_photos(embedding, n_results=10, relevance=None):
    _ensure_correct_store()
    if chroma_collection is None or chroma_collection.count() == 0:
        return []
    n_results = min(n_results, chroma_collection.count())
    results = chroma_collection.query(
        query_embeddings=[embedding],
        n_results=n_results,
    )
    matches = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            path = results["metadatas"][0][i].get("path", "") if results["metadatas"] else ""
            description = results["documents"][0][i] if results["documents"] else ""
            distance = results["distances"][0][i] if results["distances"] else 0
            matches.append({
                "path": path,
                "description": description,
                "distance": distance,
            })
    return _filter_relevant(matches, relevance=relevance)
