#!/usr/bin/env python3
"""Migrate ChromaDB document IDs from path-based to SHA-256 content hashes.

Usage:
    python migrate_to_content_hash.py --chroma-path /path/to/chromadb/model_dir
    python migrate_to_content_hash.py --index-folder /path/to/index   # all model stores
    python migrate_to_content_hash.py --chroma-path /path/to/dir --dry-run
"""

import argparse
import hashlib
import logging
import os
import sys

import chromadb

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def compute_content_hash(file_path, chunk_size=65536):
    """Compute SHA-256 hash of file content, returned as 'sha256:<hex>'."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def migrate_collection(collection, dry_run=False):
    """Migrate all path-based IDs in a collection to content hashes."""
    total = collection.count()
    if total == 0:
        logger.info("  Collection is empty, nothing to migrate.")
        return 0, 0, 0

    migrated = 0
    skipped = 0
    errors = 0
    offset = 0

    while offset < total:
        batch = collection.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        if not batch["ids"]:
            break

        for i, doc_id in enumerate(batch["ids"]):
            # Skip already-migrated entries
            if doc_id.startswith("sha256:"):
                skipped += 1
                continue

            metadata = batch["metadatas"][i] if batch["metadatas"] else {}
            image_path = metadata.get("path", "")
            embedding = batch["embeddings"][i] if batch["embeddings"] else None
            document = batch["documents"][i] if batch["documents"] else ""

            if not image_path:
                logger.warning(f"  No path in metadata for ID '{doc_id}', skipping.")
                errors += 1
                continue

            try:
                new_id = compute_content_hash(image_path)
            except FileNotFoundError:
                logger.warning(f"  File not found: {image_path}")
                errors += 1
                continue
            except PermissionError:
                logger.warning(f"  Permission denied: {image_path}")
                errors += 1
                continue
            except OSError as e:
                logger.warning(f"  OS error reading {image_path}: {e}")
                errors += 1
                continue

            if dry_run:
                logger.info(f"  [DRY RUN] {doc_id} -> {new_id}")
                migrated += 1
                continue

            # Upsert with new ID, then delete old ID
            new_metadata = dict(metadata)
            new_metadata["content_hash"] = new_id
            collection.upsert(
                ids=[new_id],
                embeddings=[embedding],
                documents=[document],
                metadatas=[new_metadata],
            )
            collection.delete(ids=[doc_id])
            migrated += 1
            logger.info(f"  Migrated: {os.path.basename(image_path)} -> {new_id[:20]}...")

        offset += len(batch["ids"])

    return migrated, skipped, errors


def migrate_store(chroma_path, dry_run=False):
    """Migrate a single ChromaDB store directory."""
    logger.info(f"Opening ChromaDB store: {chroma_path}")
    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_or_create_collection(
        name="photo_index",
        metadata={"hnsw:space": "cosine"},
    )
    total = collection.count()
    logger.info(f"  Collection 'photo_index' has {total} entries")
    return migrate_collection(collection, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate ChromaDB IDs from path-based to SHA-256 content hashes."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chroma-path", help="Path to a single ChromaDB store directory")
    group.add_argument("--index-folder", help="Index folder (migrates all model stores)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying data")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no changes will be made ===\n")

    stores = []
    if args.chroma_path:
        stores.append(args.chroma_path)
    else:
        chroma_base = os.path.join(args.index_folder, "chromadb")
        if not os.path.isdir(chroma_base):
            logger.error(f"No chromadb directory found at {chroma_base}")
            sys.exit(1)
        for name in sorted(os.listdir(chroma_base)):
            store_path = os.path.join(chroma_base, name)
            if os.path.isdir(store_path):
                stores.append(store_path)

    if not stores:
        logger.error("No ChromaDB stores found to migrate.")
        sys.exit(1)

    total_migrated = 0
    total_skipped = 0
    total_errors = 0

    for store_path in stores:
        migrated, skipped, errors = migrate_store(store_path, dry_run=args.dry_run)
        total_migrated += migrated
        total_skipped += skipped
        total_errors += errors

    logger.info(f"\n{'=== DRY RUN ' if args.dry_run else '=== '}SUMMARY ===")
    logger.info(f"  Migrated: {total_migrated}")
    logger.info(f"  Skipped (already sha256): {total_skipped}")
    logger.info(f"  Errors: {total_errors}")

    if total_errors > 0:
        logger.warning("Some entries could not be migrated. Fix file access issues and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
