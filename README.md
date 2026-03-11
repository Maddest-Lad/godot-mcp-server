# godot-mcp

Offline MCP server for Godot 4 documentation. Provides structured lookup, full-text search, semantic search, and knowledge graph tools — no external API calls.

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Check out godot-docs submodule (if cloning fresh)
git submodule update --init --recursive

# 3. Build index (first time, ~2-3 min with embeddings)
uv run python scripts/index_docs.py

# Skip embeddings for a quick 3-second index:
uv run python scripts/index_docs.py --no-rag
```

## MCP Config

Add to your Claude Code / MCP client config:

```json
{
  "mcpServers": {
    "godot-docs": {
      "command": "uv",
      "args": ["run", "-m", "src.godot_docs.server"],
      "cwd": "C:/Users/sam/Desktop/Projects/godot-mcp"
    }
  }
}
```

## Available Tools

| Tool | Description |
|---|---|
| `lookup_class(name)` | Full API docs for a class: properties, methods, signals |
| `get_method(class_name, method_name)` | Docs for a specific method |
| `list_classes(filter="")` | List all classes, optionally filtered |
| `search_docs(query, section="all")` | Full-text search (classes + tutorials) |
| `semantic_search(query, n_results=5)` | Semantic/conceptual search via local embeddings |
| `get_class_hierarchy(class_name)` | Inheritance chain (ancestors + subclasses) |
| `related_classes(class_name)` | Classes related by inheritance or type usage |
| `get_tutorial(rst_path)` | Full content of a tutorial |
| `index_status()` | Check if index is up to date |

## Updating Docs

```bash
cd godot-docs && git pull && cd ..
uv run python scripts/index_docs.py
```

## Adding to game project as submodule

```bash
cd /path/to/your-game
git submodule add https://github.com/you/godot-mcp.git tools/godot-mcp
git submodule update --init --recursive
```
