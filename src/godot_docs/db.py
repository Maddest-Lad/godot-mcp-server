"""
SQLite database helpers for structured Godot doc lookups and full-text search.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent.parent / "data" / "godot_docs.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS classes (
        name              TEXT PRIMARY KEY,
        inherits          TEXT,
        brief_description TEXT,
        description       TEXT,
        rst_path          TEXT
    );

    CREATE TABLE IF NOT EXISTS methods (
        id          INTEGER PRIMARY KEY,
        class_name  TEXT REFERENCES classes(name) ON DELETE CASCADE,
        name        TEXT,
        return_type TEXT,
        signature   TEXT,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS properties (
        id            INTEGER PRIMARY KEY,
        class_name    TEXT REFERENCES classes(name) ON DELETE CASCADE,
        name          TEXT,
        type          TEXT,
        default_value TEXT,
        description   TEXT
    );

    CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY,
        class_name  TEXT REFERENCES classes(name) ON DELETE CASCADE,
        name        TEXT,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS tutorials (
        id       INTEGER PRIMARY KEY,
        title    TEXT,
        section  TEXT,
        rst_path TEXT UNIQUE,
        content  TEXT
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS classes_fts USING fts5(
        name, brief_description, description,
        content='classes', content_rowid='rowid'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS tutorials_fts USING fts5(
        title, content,
        content='tutorials', content_rowid='id'
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Write helpers (used by indexer)
# ---------------------------------------------------------------------------

def upsert_class(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute("""
        INSERT INTO classes(name, inherits, brief_description, description, rst_path)
        VALUES(:name, :inherits, :brief_description, :description, :rst_path)
        ON CONFLICT(name) DO UPDATE SET
            inherits=excluded.inherits,
            brief_description=excluded.brief_description,
            description=excluded.description,
            rst_path=excluded.rst_path
    """, data)
    conn.execute("DELETE FROM methods WHERE class_name=?", (data["name"],))
    conn.execute("DELETE FROM properties WHERE class_name=?", (data["name"],))
    conn.execute("DELETE FROM signals WHERE class_name=?", (data["name"],))
    for m in data.get("methods", []):
        conn.execute(
            "INSERT INTO methods(class_name,name,return_type,signature,description) VALUES(?,?,?,?,?)",
            (data["name"], m["name"], m["return_type"], m["signature"], m["description"]),
        )
    for p in data.get("properties", []):
        conn.execute(
            "INSERT INTO properties(class_name,name,type,default_value,description) VALUES(?,?,?,?,?)",
            (data["name"], p["name"], p["type"], p["default_value"], p["description"]),
        )
    for s in data.get("signals", []):
        conn.execute(
            "INSERT INTO signals(class_name,name,description) VALUES(?,?,?)",
            (data["name"], s["name"], s["description"]),
        )


def upsert_tutorial(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute("""
        INSERT INTO tutorials(title, section, rst_path, content)
        VALUES(:title, :section, :rst_path, :content)
        ON CONFLICT(rst_path) DO UPDATE SET
            title=excluded.title,
            section=excluded.section,
            content=excluded.content
    """, data)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO classes_fts(classes_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO tutorials_fts(tutorials_fts) VALUES('rebuild')")
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------------------
# Read helpers (used by MCP server)
# ---------------------------------------------------------------------------

def lookup_class(name: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM classes WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["methods"] = [dict(r) for r in conn.execute(
            "SELECT name,return_type,signature,description FROM methods WHERE class_name=?", (name,)
        )]
        data["properties"] = [dict(r) for r in conn.execute(
            "SELECT name,type,default_value,description FROM properties WHERE class_name=?", (name,)
        )]
        data["signals"] = [dict(r) for r in conn.execute(
            "SELECT name,description FROM signals WHERE class_name=?", (name,)
        )]
        return data


def get_method(class_name: str, method_name: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM methods WHERE class_name=? COLLATE NOCASE AND name=? COLLATE NOCASE",
            (class_name, method_name),
        ).fetchone()
        return dict(row) if row else None


def list_classes(filter_str: str = "") -> list[str]:
    with get_conn() as conn:
        if filter_str:
            rows = conn.execute(
                "SELECT name FROM classes WHERE name LIKE ? ORDER BY name",
                (f"%{filter_str}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT name FROM classes ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def search_docs(query: str, section: str = "all") -> list[dict[str, Any]]:
    results = []
    with get_conn() as conn:
        if section in ("all", "classes"):
            rows = conn.execute(
                """
                SELECT c.name, c.brief_description, c.rst_path,
                       snippet(classes_fts, 2, '[', ']', '...', 16) as snippet
                FROM classes_fts
                JOIN classes c ON classes_fts.rowid = c.rowid
                WHERE classes_fts MATCH ?
                ORDER BY rank
                LIMIT 20
                """,
                (query,),
            ).fetchall()
            for r in rows:
                results.append({"type": "class", **dict(r)})

        if section in ("all", "tutorials"):
            rows = conn.execute(
                """
                SELECT t.id, t.title, t.section, t.rst_path,
                       snippet(tutorials_fts, 1, '[', ']', '...', 24) as snippet
                FROM tutorials_fts
                JOIN tutorials t ON tutorials_fts.rowid = t.id
                WHERE tutorials_fts MATCH ?
                ORDER BY rank
                LIMIT 20
                """,
                (query,),
            ).fetchall()
            for r in rows:
                results.append({"type": "tutorial", **dict(r)})

    return results


def get_tutorial(rst_path: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tutorials WHERE rst_path=?", (rst_path,)
        ).fetchone()
        return dict(row) if row else None


def index_status() -> dict[str, Any]:
    with get_conn() as conn:
        class_count = conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        tutorial_count = conn.execute("SELECT COUNT(*) FROM tutorials").fetchone()[0]
        last_commit = get_meta(conn, "last_indexed_commit") or "never"
        last_run = get_meta(conn, "last_indexed_at") or "never"
    return {
        "last_indexed_commit": last_commit,
        "last_indexed_at": last_run,
        "class_count": class_count,
        "tutorial_count": tutorial_count,
    }
