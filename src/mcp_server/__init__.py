import os
import sqlite3
import time
from pathlib import Path

from mcp.server import MCPServer

# Used when nobody says otherwise: the practice database in this repo.
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "sample.db"

# Which database to serve. Set SQL_EXPLORER_DB to point at your own file.
DB_PATH = Path(os.environ.get("SQL_EXPLORER_DB") or DEFAULT_DB_PATH)

# Never return more rows than this in one call, and never let a query run
# longer than this many seconds.
MAX_ROWS = 500
QUERY_TIMEOUT_SECONDS = 5.0

DEFAULT_BLOCKED_COLUMNS = "customers.email, customers.phone"


def _parse_blocked_columns(raw: str) -> set[tuple[str, str]]:
    """Turn "customers.email, customers.phone" into {("customers", "email"), ...}.

    Anything not written as table.column is a mistake worth failing loudly
    for: a typo here silently leaves a column unprotected.
    """
    blocked = set()
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item.count(".") != 1:
            raise ValueError(
                f"Blocked columns must be written as table.column, got {item!r}"
            )
        table, column = item.split(".")
        blocked.add((table, column))
    return blocked


# Columns the model is never allowed to read. Override with
# SQL_EXPLORER_BLOCKED_COLUMNS, e.g. "users.password_hash, users.ssn".
BLOCKED_COLUMNS = _parse_blocked_columns(
    os.environ.get("SQL_EXPLORER_BLOCKED_COLUMNS") or DEFAULT_BLOCKED_COLUMNS
)


def _authorizer(action, arg1, arg2, db_name, trigger_name):
    """Called by SQLite before it touches anything.

    For a read, arg1 is the table and arg2 is the column. Returning
    SQLITE_DENY makes the whole query fail inside the engine.
    """
    if action == sqlite3.SQLITE_READ:
        pair = ((arg1 or "").lower(), (arg2 or "").lower())
        if pair in BLOCKED_COLUMNS:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _make_progress_handler(deadline: float):
    """Build a callback SQLite runs periodically while a query executes.

    Returning a non-zero value tells SQLite to abandon the query, which is
    how a runaway scan gets stopped part-way through.
    """

    def handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    return handler


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
def run_query(sql: str) -> dict[str, object]:
    """Run a read-only SELECT query and return the rows.

    At most 500 rows come back; if the query matched more, "truncated" is
    true and you should add a LIMIT or aggregate instead. Queries running
    longer than 5 seconds are aborted.
    """
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
    conn.set_authorizer(_authorizer)
    conn.set_progress_handler(
        _make_progress_handler(time.monotonic() + QUERY_TIMEOUT_SECONDS), 1000
    )
    try:
        # Ask for one row more than the cap: if it arrives, we know there
        # was more data without having to fetch all of it.
        rows = conn.execute(statement).fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as exc:
        if "interrupted" in str(exc).lower():
            raise ValueError(
                f"Query aborted: took longer than {QUERY_TIMEOUT_SECONDS} seconds."
            ) from None
        raise ValueError(f"Query refused: {exc}") from None
    finally:
        conn.close()

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return {
        "rows": [dict(row) for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def main() -> None:
    # Start listening. Default transport is stdio.
    server.run()
