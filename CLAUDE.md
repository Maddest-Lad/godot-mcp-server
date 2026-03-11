# godot-mcp

Offline MCP server for Godot 4.6 documentation. Provides structured lookup, full-text search, semantic search, and knowledge graph tools — no external API calls.

## Project Structure

```
godot-docs/          # git submodule: godotengine/godot-docs@4.6
src/godot_docs/
  server.py          # FastMCP server — 9 tools exposed to the MCP client
  parser.py          # RST parser for Godot class files and tutorial files
  db.py              # SQLite + FTS5: structured lookups and keyword search
  graph.py           # NetworkX knowledge graph: inheritance + type-usage edges
  rag.py             # ChromaDB + sentence-transformers: offline semantic search
scripts/
  index_docs.py      # Indexing pipeline — run this to build/update the index
data/                # Generated, gitignored — rebuild with index_docs.py
  godot_docs.db      # SQLite database (classes, methods, properties, signals, tutorials)
  chroma/            # ChromaDB vector store
  graph.json         # NetworkX graph in node_link format
```

## Common Tasks

**Build or update the index:**
```bash
uv run python scripts/index_docs.py           # skip if commit unchanged
uv run python scripts/index_docs.py --force   # force full re-index
uv run python scripts/index_docs.py --no-rag  # skip embeddings (fast, 3s)
```

**Update godot-docs to latest 4.6:**
```bash
cd godot-docs && git pull && cd ..
uv run python scripts/index_docs.py
```

**Run the MCP server directly:**
```bash
uv run -m src.godot_docs.server
```

**Install dependencies:**
```bash
uv sync
```

## MCP Tools

| Tool | Purpose |
|---|---|
| `lookup_class(name)` | Full API docs: properties, methods, signals |
| `get_method(class_name, method_name)` | Single method docs |
| `list_classes(filter="")` | Browse all classes |
| `search_docs(query, section="all")` | FTS5 keyword search |
| `semantic_search(query, n_results=5)` | Conceptual/similarity search |
| `get_class_hierarchy(class_name)` | Inheritance chain up + subclasses down |
| `related_classes(class_name)` | Classes linked by inheritance or type usage |
| `get_tutorial(rst_path)` | Full tutorial content by path |
| `index_status()` | Last indexed commit, class/tutorial counts |

## Key Implementation Notes

**Parser (`parser.py`):**
- Godot class RST files are machine-generated with consistent label format: `.. _class_Node3D_method_add_gizmo:`
- Class name must be extracted from the RST heading (PascalCase), not the filename (lowercase)
- Brief description lives in the `class_{ClassName}` section, not a separate `_description` label
- Inherits line format: `**Inherits:** :ref:`Node<class_Node>`` — requires `\*{0,2}` in regex

**Indexer (`index_docs.py`):**
- Skips re-indexing if the godot-docs submodule HEAD commit hasn't changed
- `--force` bypasses the commit check
- Tutorial dirs: `about`, `getting_started`, `tutorials`, `engine_details`, `community`
- RAG step (~75s first run) downloads `all-MiniLM-L6-v2` (~80MB) to `~/.cache/huggingface`

**Knowledge graph (`graph.py`):**
- `INHERITS` edges: class → parent (from `inherits` field)
- `USES_TYPE` edges: class → class (from method return types and property types)
- Persisted as `data/graph.json` in networkx node_link format

**Windows note:** HuggingFace cache symlinks require Developer Mode. Works without it, just uses more disk. Suppress the warning with `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.

## Dependencies

- `fastmcp>=2.0` — MCP framework
- `docutils` — RST parsing
- `chromadb` — local vector store (no server needed)
- `sentence-transformers` — offline embeddings (`all-MiniLM-L6-v2`)
- `networkx` — knowledge graph
- `sqlite3` — stdlib, FTS5 for full-text search
