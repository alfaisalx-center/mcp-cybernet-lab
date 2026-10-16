"""Sample MCP server: exposes a company SQLite database, read-only.

    mcl-sample-db --db /data/hr/company.db

If the database file does not exist, it is created from seed.sql (shipped with the package).
`mcl reset` deletes it with the rest of the server's data, so the next call starts from the
seed again.

Tools:  list_tables, describe_table, query (one read-only SELECT)
Resource:  schema://tables  (the CREATE statements)
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError  # message is shown to the agent

MAX_ROWS = 200

server = MCPServer(
    name="sample-db",
    version="0.1.0",
    instructions="Read-only access to the Najd Logistics company database "
                 "(departments, employees, customers, api_keys). Use list_tables and "
                 "describe_table first, then query with a single SELECT statement.",
)
DB_PATH = Path("company.db")  # replaced by --db in main()


def ensure_db() -> None:
    """Create the database from the seed if it is missing."""
    if DB_PATH.exists():
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    seed = files("sample_db").joinpath("seed.sql").read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(seed)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A read-only connection: writes fail in SQLite itself, whatever the SQL says."""
    ensure_db()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@server.tool(description="List the tables of the database with their number of rows.")
def list_tables() -> dict[str, int]:
    with connect() as conn:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


@server.tool(description="Columns of one table: name, type, and whether it may be empty.")
def describe_table(table: str) -> list[dict]:
    with connect() as conn:
        if table not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            raise ToolError(f"unknown table '{table}'; call list_tables")
        return [{"name": r["name"], "type": r["type"], "nullable": not r["notnull"]}
                for r in conn.execute(f'PRAGMA table_info("{table}")')]


@server.tool(description=f"Run one read-only SELECT statement. At most {MAX_ROWS} rows are returned.")
def query(sql: str) -> dict:
    head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    if head not in ("SELECT", "WITH"):
        raise ToolError("only SELECT statements are allowed")
    with connect() as conn:
        try:
            cur = conn.execute(sql)  # sqlite3 refuses more than one statement per call
        except (sqlite3.Error, sqlite3.Warning) as e:
            raise ToolError(f"SQL error: {e}") from e
        rows = cur.fetchmany(MAX_ROWS + 1)
        return {
            "columns": [d[0] for d in cur.description],
            "rows": [list(r) for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS,
        }


@server.resource("schema://tables", description="CREATE statements of every table.",
                 mime_type="text/plain")
def schema() -> str:
    with connect() as conn:
        return "\n".join(r[0] + ";" for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' ORDER BY name"))


def main() -> None:
    global DB_PATH
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default="company.db", help="SQLite file; created from the seed if missing")
    DB_PATH = Path(p.parse_args().db)
    server.run("stdio")


if __name__ == "__main__":
    main()
