"""
Parse Godot 4 RST documentation files into structured dicts.

Godot class files (classes/class_*.rst) are machine-generated with a very
consistent format. Tutorial files are hand-written and we just extract text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_rst_inline(text: str) -> str:
    """Remove common RST inline markup: :ref:`...`, ``code``, **bold**, |type|."""
    text = re.sub(r":[a-z_]+:`([^`<]+)(?:<[^>]+>)?`", r"\1", text)
    text = re.sub(r"\|[A-Za-z0-9_]+\|", "", text)
    text = re.sub(r"``([^`]+)``", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def _clean_block(lines: list[str]) -> str:
    """Join and strip a block of RST lines into plain text."""
    joined = " ".join(l.strip() for l in lines if l.strip() and not l.strip().startswith(".."))
    return _strip_rst_inline(joined)


_SECTION_RE = re.compile(r"^[-=~^`]+$")
_LABEL_RE = re.compile(r"^\.\.\s+_([^:]+):$")
# Matches: **Inherits:** :ref:`Node<class_Node>` or Inherits: :ref:`Node<class_Node>`
_INHERITS_RE = re.compile(r"\*{0,2}Inherits:\*{0,2}\s*:ref:`([^`<]+)", re.IGNORECASE)
_REF_RE = re.compile(r":ref:`([^`<]+)(?:<[^>]+>)?`")


def parse_class_file(path: Path) -> dict[str, Any] | None:
    """
    Parse a Godot class RST file.
    Returns a dict with keys:
      name, inherits, brief_description, description, rst_path,
      methods, properties, signals, constants, enums, tutorials
    Returns None if the file doesn't look like a class file.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if not lines:
        return None

    result: dict[str, Any] = {
        "name": "",
        "inherits": "",
        "brief_description": "",
        "description": "",
        "rst_path": str(path),
        "methods": [],
        "properties": [],
        "signals": [],
        "constants": [],
        "enums": [],
        "tutorials": [],
    }

    # --- Extract class name from the RST heading (PascalCase) ---
    # The heading is the first non-empty, non-directive line followed by ====
    for i, line in enumerate(lines[:-1]):
        next_line = lines[i + 1]
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("..")
            and not stripped.startswith(":")
            and _SECTION_RE.match(next_line.strip())
            and "=" in next_line
        ):
            result["name"] = stripped
            break

    # Fallback: derive from filename
    if not result["name"]:
        stem = path.stem
        result["name"] = stem[6:] if stem.startswith("class_") else stem

    class_name = result["name"]

    # --- Extract inherits (within first 30 lines) ---
    for line in lines[:30]:
        m = _INHERITS_RE.search(line)
        if m:
            result["inherits"] = m.group(1).strip()
            break

    # --- Split into labelled sections ---
    sections: dict[str, list[str]] = {}
    current_label = "_top"
    current_lines: list[str] = []

    for line in lines:
        m = _LABEL_RE.match(line)
        if m:
            sections[current_label] = current_lines
            current_label = m.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    sections[current_label] = current_lines

    # --- Brief description ---
    # In Godot 4 RST, the brief (one-liner) sits in the class's own label section
    # (class_Node3D), as the first prose line after the heading and Inherits lines.
    # There is no separate class_Node3D_description label for the brief.
    class_section_lines = sections.get(f"class_{class_name}", [])
    if not class_section_lines:
        # Try case-insensitive
        for k, v in sections.items():
            if k.lower() == f"class_{class_name}".lower():
                class_section_lines = v
                break

    skip_prefixes = ("**Inherits", "**Inherited", "Inherits", "Inherited")
    for l in class_section_lines:
        stripped = l.strip()
        if not stripped:
            continue
        if stripped.startswith("..") or stripped.startswith(":"):
            continue
        if _SECTION_RE.match(stripped):
            continue
        # Skip the class name heading itself
        if stripped == class_name:
            continue
        # Skip inheritance lines
        if any(stripped.startswith(p) for p in skip_prefixes):
            continue
        # This is the brief description
        result["brief_description"] = _strip_rst_inline(stripped)
        break

    # --- Tutorials ---
    tut_label = f"class_{class_name}_tutorials"
    for label, lblines in sections.items():
        if label.lower() == tut_label.lower():
            for l in lblines:
                refs = _REF_RE.findall(l)
                result["tutorials"].extend(refs)
            break

    # --- Methods, Properties, Signals, Constants ---
    # Labels use the original PascalCase class name, e.g.:
    #   class_Node3D_method_add_gizmo
    #   class_Node3D_property_position
    #   class_Node3D_signal_visibility_changed
    #   class_Node3D_constant_NOTIFICATION_TRANSFORM_CHANGED
    method_prefix = f"class_{class_name}_method_"
    prop_prefix = f"class_{class_name}_property_"
    signal_prefix = f"class_{class_name}_signal_"
    const_prefix = f"class_{class_name}_constant_"
    enum_prefix = f"class_{class_name}_enum_"

    for label, lblines in sections.items():
        if label.startswith(method_prefix):
            method_name = label[len(method_prefix):]
            desc = _clean_block(lblines)
            sig = _extract_signature(lblines, method_name)
            result["methods"].append({
                "name": method_name,
                "signature": sig,
                "return_type": _extract_return_type(sig),
                "description": desc,
            })
        elif label.startswith(prop_prefix):
            prop_name = label[len(prop_prefix):]
            desc = _clean_block(lblines)
            ptype, default = _extract_property_meta(lblines)
            result["properties"].append({
                "name": prop_name,
                "type": ptype,
                "default_value": default,
                "description": desc,
            })
        elif label.startswith(signal_prefix):
            sig_name = label[len(signal_prefix):]
            desc = _clean_block(lblines)
            result["signals"].append({"name": sig_name, "description": desc})
        elif label.startswith(const_prefix):
            const_name = label[len(const_prefix):]
            desc = _clean_block(lblines)
            result["constants"].append({"name": const_name, "description": desc})
        elif label.startswith(enum_prefix):
            enum_name = label[len(enum_prefix):]
            desc = _clean_block(lblines)
            result["enums"].append({"name": enum_name, "description": desc})

    return result


def _extract_signature(lines: list[str], method_name: str) -> str:
    """Try to find a method signature line (contains method name and parentheses)."""
    for line in lines:
        stripped = line.strip()
        if method_name in stripped and "(" in stripped and not stripped.startswith(".."):
            return _strip_rst_inline(stripped)
    return f"{method_name}()"


def _extract_return_type(sig: str) -> str:
    """Guess return type from a signature like 'void method_name(...)'."""
    parts = sig.strip().split()
    if len(parts) >= 2 and "(" in parts[1]:
        return parts[0]
    return ""


def _extract_property_meta(lines: list[str]) -> tuple[str, str]:
    """Extract property type and default value from section lines."""
    for line in lines:
        stripped = line.strip()
        # ``TypeName`` **prop_name** = ``default``
        m = re.search(r"``([A-Za-z0-9_\[\]]+)``\s+\*\*[^*]+\*\*(?:\s*=\s*``([^`]*)``)?", stripped)
        if m:
            return m.group(1), m.group(2) or ""
        # |TypeName| **prop_name** = ``default``
        m2 = re.search(r"\|([A-Za-z0-9_]+)\|\s+\*\*[^*]+\*\*(?:\s*=\s*``([^`]*)``)?", stripped)
        if m2:
            return m2.group(1), m2.group(2) or ""
    return "", ""


# ---------------------------------------------------------------------------
# Tutorial file parser
# ---------------------------------------------------------------------------

def parse_tutorial_file(path: Path, docs_root: Path) -> dict[str, Any] | None:
    """
    Parse a tutorial/manual RST file.
    Returns: {title, section, rst_path, content}
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = text.splitlines()
    if len(lines) < 3:
        return None

    # Section = top-level directory relative to docs root
    try:
        rel = path.relative_to(docs_root)
        section = rel.parts[0] if len(rel.parts) > 1 else "root"
    except ValueError:
        section = "unknown"

    # Title: first heading (line N+1 is === or --- underlining line N)
    title = path.stem.replace("_", " ").title()
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        next_line = lines[i + 1].strip()
        if line and next_line and _SECTION_RE.match(next_line) and not line.startswith("..") and not line.startswith(":"):
            title = line
            break

    # Extract plain text
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            content_lines.append("")
            continue
        if stripped.startswith("..") or stripped.startswith(":"):
            continue
        if _SECTION_RE.match(stripped):
            continue
        content_lines.append(_strip_rst_inline(stripped))

    content = "\n".join(content_lines)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()

    if len(content) < 50:
        return None

    return {
        "title": title,
        "section": section,
        "rst_path": str(path.relative_to(docs_root)).replace("\\", "/"),
        "content": content[:50000],
    }
