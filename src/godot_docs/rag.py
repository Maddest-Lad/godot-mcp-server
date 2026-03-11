"""
RAG (semantic search) using ChromaDB + sentence-transformers.
All embeddings are computed locally — no external API calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CHROMA_PATH = Path(__file__).parent.parent.parent / "data" / "chroma"
EMBED_MODEL = "all-MiniLM-L6-v2"

_client = None
_ef = None


def _get_client():
    global _client
    if _client is None:
        import chromadb
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def _get_ef():
    global _ef
    if _ef is None:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        _ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    return _ef


def _classes_collection():
    return _get_client().get_or_create_collection("classes", embedding_function=_get_ef())


def _tutorials_collection():
    return _get_client().get_or_create_collection("tutorials", embedding_function=_get_ef())


# ---------------------------------------------------------------------------
# Index helpers (called by indexer)
# ---------------------------------------------------------------------------

def index_classes(classes: list[dict[str, Any]], batch_size: int = 64) -> None:
    col = _classes_collection()
    ids, docs, metas = [], [], []
    for cls in classes:
        method_names = " ".join(m["name"] for m in cls.get("methods", []))
        prop_names = " ".join(p["name"] for p in cls.get("properties", []))
        text = f"{cls['name']} {cls.get('brief_description', '')} Methods: {method_names} Properties: {prop_names}"
        ids.append(cls["name"])
        docs.append(text)
        metas.append({
            "name": cls["name"],
            "inherits": cls.get("inherits", ""),
            "brief": cls.get("brief_description", "")[:500],
        })
    # Upsert in batches
    for i in range(0, len(ids), batch_size):
        col.upsert(
            ids=ids[i:i+batch_size],
            documents=docs[i:i+batch_size],
            metadatas=metas[i:i+batch_size],
        )


def index_tutorials(tutorials: list[dict[str, Any]], batch_size: int = 32) -> None:
    col = _tutorials_collection()
    ids, docs, metas = [], [], []
    for tut in tutorials:
        # Chunk into ~512-word windows for better retrieval
        chunks = _chunk_text(tut["content"], max_words=512)
        for j, chunk in enumerate(chunks):
            chunk_id = f"{tut['rst_path']}::chunk{j}"
            ids.append(chunk_id)
            docs.append(f"{tut['title']} {chunk}")
            metas.append({
                "title": tut["title"],
                "section": tut["section"],
                "rst_path": tut["rst_path"],
                "chunk": j,
            })
    for i in range(0, len(ids), batch_size):
        col.upsert(
            ids=ids[i:i+batch_size],
            documents=docs[i:i+batch_size],
            metadatas=metas[i:i+batch_size],
        )


def _chunk_text(text: str, max_words: int = 512) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i+max_words]))
    return chunks or [text]


# ---------------------------------------------------------------------------
# Query helpers (called by MCP server)
# ---------------------------------------------------------------------------

def semantic_search(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    results = []
    try:
        # Search classes
        cls_col = _classes_collection()
        cls_res = cls_col.query(query_texts=[query], n_results=min(n_results, cls_col.count() or 1))
        for i, doc_id in enumerate(cls_res["ids"][0]):
            meta = cls_res["metadatas"][0][i]
            distance = cls_res["distances"][0][i] if cls_res.get("distances") else None
            results.append({
                "type": "class",
                "id": doc_id,
                "name": meta.get("name", doc_id),
                "brief": meta.get("brief", ""),
                "score": round(1 - distance, 3) if distance is not None else None,
            })
    except Exception:
        pass

    try:
        # Search tutorials
        tut_col = _tutorials_collection()
        tut_res = tut_col.query(query_texts=[query], n_results=min(n_results, tut_col.count() or 1))
        for i, doc_id in enumerate(tut_res["ids"][0]):
            meta = tut_res["metadatas"][0][i]
            distance = tut_res["distances"][0][i] if tut_res.get("distances") else None
            results.append({
                "type": "tutorial",
                "id": doc_id,
                "title": meta.get("title", ""),
                "section": meta.get("section", ""),
                "rst_path": meta.get("rst_path", ""),
                "score": round(1 - distance, 3) if distance is not None else None,
            })
    except Exception:
        pass

    # Sort by score descending and return top n
    results.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return results[:n_results]
