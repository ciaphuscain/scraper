"""SQLite FTS5 virtual tables kept in sync with triggers (external content)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# (fts table, content table, columns)
FTS_TABLES: list[tuple[str, str, list[str]]] = [
    ("videos_fts", "videos", ["title", "description"]),
    ("channels_fts", "channels", ["name", "description"]),
    ("segments_fts", "transcript_segments", ["text"]),
    ("ideas_fts", "ideas", ["title", "explanation", "keywords_text", "topic"]),
]


def _rowid(table: str) -> str:
    # videos/channels use string PKs, so use SQLite's implicit rowid.
    return "rowid"


def fts_statements() -> list[str]:
    stmts: list[str] = []
    for fts, content, cols in FTS_TABLES:
        col_list = ", ".join(cols)
        new_vals = ", ".join(f"new.{c}" for c in cols)
        old_vals = ", ".join(f"old.{c}" for c in cols)
        rid = _rowid(content)
        stmts += [
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5({col_list}, content='{content}', "
            f"content_rowid='{rid}', tokenize='porter unicode61 remove_diacritics 2')",
            f"CREATE TRIGGER IF NOT EXISTS {fts}_ai AFTER INSERT ON {content} BEGIN "
            f"INSERT INTO {fts}(rowid, {col_list}) VALUES (new.{rid}, {new_vals}); END",
            f"CREATE TRIGGER IF NOT EXISTS {fts}_ad AFTER DELETE ON {content} BEGIN "
            f"INSERT INTO {fts}({fts}, rowid, {col_list}) VALUES ('delete', old.{rid}, {old_vals}); END",
            f"CREATE TRIGGER IF NOT EXISTS {fts}_au AFTER UPDATE OF {col_list} ON {content} BEGIN "
            f"INSERT INTO {fts}({fts}, rowid, {col_list}) VALUES ('delete', old.{rid}, {old_vals}); "
            f"INSERT INTO {fts}(rowid, {col_list}) VALUES (new.{rid}, {new_vals}); END",
        ]
    return stmts


def drop_statements() -> list[str]:
    out: list[str] = []
    for fts, _content, _cols in FTS_TABLES:
        for suffix in ("ai", "ad", "au"):
            out.append(f"DROP TRIGGER IF EXISTS {fts}_{suffix}")
        out.append(f"DROP TABLE IF EXISTS {fts}")
    return out


def create_fts(conn: Connection) -> None:
    for stmt in fts_statements():
        conn.execute(text(stmt))


def rebuild_fts(conn: Connection) -> None:
    for fts, _c, _cols in FTS_TABLES:
        conn.execute(text(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')"))
