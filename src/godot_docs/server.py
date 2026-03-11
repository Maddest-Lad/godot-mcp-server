"""
Godot documentation MCP server.
Provides offline lookup, full-text search, semantic search, and knowledge graph tools.

Run:
    uv run -m src.godot_docs.server

Build index first:
    uv run python scripts/index_docs.py
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from . import db, graph, rag

mcp = FastMCP("godot-docs")


@mcp.tool
async def lookup_class(name: str) -> dict[str, Any]:
    """
    Get full API documentation for a Godot class.
    Returns properties, methods, signals, and description.
    Example: lookup_class("Node3D")
    """
    result = db.lookup_class(name)
    if result is None:
        return {"error": f"Class '{name}' not found. Try list_classes() to browse available classes."}
    return result


@mcp.tool
async def get_method(class_name: str, method_name: str) -> dict[str, Any]:
    """
    Get documentation for a specific method on a Godot class.
    Example: get_method("Node", "add_child")
    """
    result = db.get_method(class_name, method_name)
    if result is None:
        return {"error": f"Method '{method_name}' not found on class '{class_name}'."}
    return result


@mcp.tool
async def list_classes(filter: str = "") -> list[str]:
    """
    List all indexed Godot classes. Optionally filter by substring.
    Example: list_classes("Node") returns all classes with 'Node' in the name.
    """
    return db.list_classes(filter)


@mcp.tool
async def search_docs(query: str, section: str = "all") -> list[dict[str, Any]]:
    """
    Full-text search across Godot classes and tutorials.
    Use section='classes' or section='tutorials' to narrow results (default: 'all').
    Returns up to 20 results with snippets.
    Example: search_docs("raycast physics layer")
    """
    try:
        return db.search_docs(query, section)
    except Exception as e:
        return [{"error": str(e), "hint": "Ensure the index has been built: uv run python scripts/index_docs.py"}]


@mcp.tool
async def semantic_search(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """
    Semantic similarity search using local embeddings (all-MiniLM-L6-v2).
    Better than keyword search for conceptual questions.
    Example: semantic_search("how do I handle input events"), semantic_search("tween animation")
    """
    return rag.semantic_search(query, n_results)


@mcp.tool
async def get_class_hierarchy(class_name: str) -> dict[str, Any]:
    """
    Get the full inheritance chain for a Godot class: ancestors and direct subclasses.
    Example: get_class_hierarchy("CharacterBody3D")
    """
    return graph.get_hierarchy(class_name)


@mcp.tool
async def related_classes(class_name: str) -> dict[str, Any]:
    """
    Find classes related to the given class: subclasses, and classes that use it as a type.
    Useful for exploring the class ecosystem around a concept.
    Example: related_classes("Node")
    """
    return graph.get_related(class_name)


@mcp.tool
async def get_tutorial(rst_path: str) -> dict[str, Any]:
    """
    Get the full content of a tutorial by its RST path (as returned by search_docs or semantic_search).
    Example: get_tutorial("getting_started/introduction/index.rst")
    """
    result = db.get_tutorial(rst_path)
    if result is None:
        return {"error": f"Tutorial '{rst_path}' not found."}
    return result


@mcp.tool
async def index_status() -> dict[str, Any]:
    """
    Check the index status: last indexed commit, class count, and tutorial count.
    If counts are 0, run: uv run python scripts/index_docs.py
    """
    return db.index_status()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
