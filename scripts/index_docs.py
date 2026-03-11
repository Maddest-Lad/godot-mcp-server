"""
Godot docs indexer.
Parses godot-docs/ submodule and populates SQLite, ChromaDB, and the knowledge graph.

Usage:
    uv run python scripts/index_docs.py            # skip if already indexed at same commit
    uv run python scripts/index_docs.py --force    # force full re-index
    uv run python scripts/index_docs.py --no-rag   # skip slow embedding step

To update docs:
    cd godot-docs && git pull && cd ..
    uv run python scripts/index_docs.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when run directly
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.godot_docs import db, graph, rag
from src.godot_docs.parser import parse_class_file, parse_tutorial_file

DOCS_ROOT = ROOT / "godot-docs"
TUTORIAL_DIRS = ["about", "getting_started", "tutorials", "engine_details", "community"]


def get_current_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=DOCS_ROOT,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Index Godot documentation")
    parser.add_argument("--force", action="store_true", help="Re-index even if commit unchanged")
    parser.add_argument("--no-rag", action="store_true", help="Skip embedding/vector index step")
    args = parser.parse_args()

    if not DOCS_ROOT.exists() or not (DOCS_ROOT / "classes").exists():
        print(f"ERROR: godot-docs submodule not found at {DOCS_ROOT}")
        print("Run: git submodule update --init --recursive")
        sys.exit(1)

    conn = db.get_conn()
    db.init_schema(conn)

    current_commit = get_current_commit()
    stored_commit = db.get_meta(conn, "last_indexed_commit")

    if not args.force and current_commit != "unknown" and current_commit == stored_commit:
        print(f"Already indexed at commit {current_commit[:8]}. Use --force to re-index.")
        status = db.index_status()
        print(f"  Classes: {status['class_count']}, Tutorials: {status['tutorial_count']}")
        return

    print(f"Indexing godot-docs @ {current_commit[:8] if current_commit != 'unknown' else '?'}")
    t0 = time.time()

    # --- 1. Parse and index class files ---
    class_dir = DOCS_ROOT / "classes"
    class_files = sorted(class_dir.glob("class_*.rst"))
    print(f"  Parsing {len(class_files)} class files...")

    all_classes = []
    for i, path in enumerate(class_files):
        parsed = parse_class_file(path)
        if parsed:
            all_classes.append(parsed)
            upsert_data = {
                "name": parsed["name"],
                "inherits": parsed["inherits"],
                "brief_description": parsed["brief_description"],
                "description": parsed.get("description", ""),
                "rst_path": str(Path(parsed["rst_path"]).relative_to(DOCS_ROOT)),
            }
            db.upsert_class(conn, {**upsert_data, **parsed})
        if (i + 1) % 200 == 0:
            conn.commit()
            print(f"    {i+1}/{len(class_files)} classes...")

    conn.commit()
    print(f"  Indexed {len(all_classes)} classes.")

    # --- 2. Parse and index tutorial files ---
    print("  Parsing tutorial files...")
    all_tutorials = []
    for section in TUTORIAL_DIRS:
        section_path = DOCS_ROOT / section
        if not section_path.exists():
            continue
        for rst_path in section_path.rglob("*.rst"):
            parsed = parse_tutorial_file(rst_path, DOCS_ROOT)
            if parsed and len(parsed.get("content", "")) > 100:
                all_tutorials.append(parsed)
                db.upsert_tutorial(conn, parsed)

    conn.commit()
    print(f"  Indexed {len(all_tutorials)} tutorial files.")

    # --- 3. Rebuild FTS ---
    print("  Rebuilding full-text search index...")
    db.rebuild_fts(conn)

    # --- 4. Build knowledge graph ---
    print("  Building knowledge graph...")
    G = graph.build_graph(all_classes)
    graph.save_graph(G)
    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    # --- 5. Build vector index ---
    if not args.no_rag:
        print(f"  Building vector index (this may take a few minutes on first run)...")
        print("  (Downloads ~80MB embedding model on first run)")
        rag.index_classes(all_classes)
        print(f"  Indexed {len(all_classes)} class embeddings.")
        rag.index_tutorials(all_tutorials)
        print(f"  Indexed tutorial embeddings.")
    else:
        print("  Skipping RAG index (--no-rag).")

    # --- 6. Store commit hash ---
    from datetime import datetime, timezone
    db.set_meta(conn, "last_indexed_commit", current_commit)
    db.set_meta(conn, "last_indexed_at", datetime.now(timezone.utc).isoformat())

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s.")
    print(f"  Classes: {len(all_classes)}, Tutorials: {len(all_tutorials)}")


if __name__ == "__main__":
    main()
