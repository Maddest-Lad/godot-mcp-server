"""
Knowledge graph for Godot class relationships.
Persisted as data/graph.json (networkx node_link format).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

GRAPH_PATH = Path(__file__).parent.parent.parent / "data" / "graph.json"


def build_graph(classes: list[dict[str, Any]]) -> nx.DiGraph:
    """Build graph from a list of parsed class dicts."""
    G = nx.DiGraph()
    for cls in classes:
        G.add_node(cls["name"], inherits=cls.get("inherits", ""), category="class")

    for cls in classes:
        parent = cls.get("inherits", "")
        if parent and parent in G:
            G.add_edge(cls["name"], parent, relation="INHERITS")

        # USES_TYPE edges from method signatures and property types
        seen = set()
        for m in cls.get("methods", []):
            for token in (m.get("return_type", ""), m.get("signature", "")):
                # Extract PascalCase words that likely are class names
                import re
                for candidate in re.findall(r"\b[A-Z][A-Za-z0-9]+\b", token):
                    if candidate != cls["name"] and candidate not in seen:
                        seen.add(candidate)
        for p in cls.get("properties", []):
            ptype = p.get("type", "")
            if ptype and ptype[0].isupper() and ptype != cls["name"]:
                seen.add(ptype)

        for candidate in seen:
            if candidate in G and candidate != cls["name"]:
                G.add_edge(cls["name"], candidate, relation="USES_TYPE")

    return G


def save_graph(G: nx.DiGraph) -> None:
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    GRAPH_PATH.write_text(json.dumps(data), encoding="utf-8")


def load_graph() -> nx.DiGraph | None:
    if not GRAPH_PATH.exists():
        return None
    data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    return nx.node_link_graph(data, directed=True)


def get_hierarchy(class_name: str) -> dict[str, Any]:
    """Return ancestors (inheritance chain up) and direct subclasses."""
    G = load_graph()
    if G is None or class_name not in G:
        return {"error": "Graph not built yet or class not found. Run the indexer."}

    # Ancestors: follow INHERITS edges upward
    ancestors = []
    current = class_name
    for _ in range(50):  # safety limit
        parents = [
            n for n in G.successors(current)
            if G[current][n].get("relation") == "INHERITS"
        ]
        if not parents:
            break
        current = parents[0]
        ancestors.append(current)

    # Descendants: classes that directly inherit from class_name
    subclasses = [
        n for n in G.predecessors(class_name)
        if G[n][class_name].get("relation") == "INHERITS"
    ]

    return {
        "class": class_name,
        "inherits_chain": ancestors,  # [parent, grandparent, ...]
        "direct_subclasses": sorted(subclasses),
    }


def get_related(class_name: str) -> dict[str, Any]:
    """Return classes related by inheritance or type usage."""
    G = load_graph()
    if G is None or class_name not in G:
        return {"error": "Graph not built yet or class not found. Run the indexer."}

    uses = sorted({
        n for n in G.successors(class_name)
        if G[class_name][n].get("relation") == "USES_TYPE"
    })
    used_by = sorted({
        n for n in G.predecessors(class_name)
        if G[n][class_name].get("relation") == "USES_TYPE"
    })
    subclasses = sorted({
        n for n in G.predecessors(class_name)
        if G[n][class_name].get("relation") == "INHERITS"
    })

    return {
        "class": class_name,
        "uses_types": uses,
        "used_as_type_by": used_by,
        "subclasses": subclasses,
    }
