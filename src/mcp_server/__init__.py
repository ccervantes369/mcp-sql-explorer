import sqlite3
from pathlib import Path

from mcp.server import MCPServer

# Where the database lives: three folders up from this file, then sample.db
DB_PATH = Path(__file__).parent.parent.parent / "sample.db"

# The server object. The name is how clients identify us.
server = MCPServer(name="sql-explorer")


@server.tool()
def ping() -> str:
    """Check that the server is alive."""
    return "pong"


@server.tool()
def list_tables() -> list[str]:
    """List the names of every table in the database."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


@server.tool()
def describe_table(table: str) -> list[dict[str, object]]:
    """Describe the columns of one table: name, type, and whether it is required."""
    conn = sqlite3.connect(DB_PATH)
    try:
        # A table name cannot be passed as a "?" parameter, so we check it
        # against the real table list before letting it near the SQL.
        known = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if table not in known:
            raise ValueError(f"Unknown table: {table!r}")

        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()

    return [
        {"name": row[1], "type": row[2], "required": bool(row[3])}
        for row in rows
    ]


@server.tool()
def run_query(sql: str) -> list[dict[str, object]]:
    """Run a read-only SELECT query against the database and return the rows."""
    # Tidy the input so a trailing semicolon or stray spacing does not
    # confuse the check below.
    statement = sql.strip().rstrip(";").strip()

    # Guard: nothing but SELECT gets through.
    if not statement.lower().startswith("select"):
        raise ValueError("Only SELECT statements are allowed.")

    conn = sqlite3.connect(DB_PATH)
    # row_factory makes each row behave like a dict instead of a bare tuple,
    # so the column names travel with the values.
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(statement).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def main() -> None:
    # Start listening. Default transport is stdio.
    server.run()
