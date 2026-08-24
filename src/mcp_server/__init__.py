import os
import secrets
import sqlite3
import time
from pathlib import Path

from mcp.server import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

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


@server.resource("schema://tables", mime_type="text/plain")
def schema_overview() -> str:
    """Every table in the database, with its columns, as one readable page."""
    lines = []
    for table in list_tables():
        names = [_describe_column(table, col) for col in describe_table(table)]
        lines.append(f"{table}({', '.join(names)})")
    return "\n".join(lines)


@server.resource("schema://{table}", mime_type="text/plain")
def table_schema(table: str) -> str:
    """The columns of one table.

    The {table} in the URI makes this a template: one function serves
    schema://customers, schema://orders, and any table another database
    happens to have.
    """
    lines = [f"Table: {table}", ""]
    for col in describe_table(table):
        needed = "required" if col["required"] else "optional"
        label = _describe_column(table, col)
        lines.append(f"  {label:<24} {col['type']:<8} {needed}")
    return "\n".join(lines)


def _describe_column(table: str, col: dict) -> str:
    """Column name, marked if the server would refuse to read it."""
    name = str(col["name"])
    if (table.lower(), name.lower()) in BLOCKED_COLUMNS:
        return f"{name} [blocked]"
    return name



@server.prompt()
def analyze_table(table: str) -> str:
    """Explore one table properly: size, distributions, gaps and outliers."""
    return f"""Investigate the "{table}" table in this database and report what you find.

Work through it in this order, using run_query for each step:

1. Size. How many rows are there?
2. Shape. Read schema://{table} to see the columns. Columns marked
   [blocked] cannot be read, so do not try.
3. Distributions. For each text column with few distinct values, show the
   counts per value. For each numeric column, report min, max and average.
4. Gaps. Which columns contain empty strings or nulls, and how often?
5. Outliers. Show the handful of rows with the most extreme numeric values.

Keep every query small. Aggregate rather than listing rows, and never
select more than you need: results are capped at 500 rows.

Finish with a short plain-language summary of what the data appears to be
and anything that looks worth a second look."""


@server.prompt()
def data_quality_report() -> str:
    """Hunt for broken or suspicious data across the whole database."""
    return """Audit this database for data quality problems.

Start by reading schema://tables to see what exists, then look for:

- Duplicates. Rows that appear to be the same real thing recorded twice.
- Orphans. Rows referencing an id that does not exist in the parent table.
- Impossible values. Negative amounts, dates in the future, dates before
  the thing they belong to, empty required fields.
- Suspicious uniformity. A column where nearly every row holds the same
  value is often a bug rather than a fact.

Use aggregate queries and counts rather than dumping rows. For each problem
you find, report the query that found it, how many rows are affected, and
one example.

If you find nothing wrong, say so plainly rather than inventing concerns."""



class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject any HTTP request that does not carry the expected token.

    This sits in front of the MCP app, so an unauthenticated request never
    reaches a tool, a resource, or the database.
    """

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._expected = f"Bearer {token}"

    async def dispatch(self, request, call_next):
        presented = request.headers.get("authorization", "")
        # compare_digest takes the same time whether the first character
        # is wrong or only the last one, so it does not leak the token
        # to someone measuring how long the rejection took.
        if not secrets.compare_digest(presented, self._expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def main() -> None:
    """Start the server on the transport named by SQL_EXPLORER_TRANSPORT.

    Defaults to stdio, which is how a desktop client launches this as a
    child process. Set "streamable-http" to run it as a web service.
    """
    transport = os.environ.get("SQL_EXPLORER_TRANSPORT", "stdio")

    if transport == "stdio":
        # Nothing to authenticate: whoever launched this process is already
        # trusted by the operating system.
        server.run()
        return

    if transport != "streamable-http":
        raise ValueError(
            f"Unknown transport {transport!r}. Use 'stdio' or 'streamable-http'."
        )

    token = os.environ.get("SQL_EXPLORER_TOKEN")
    if not token:
        raise ValueError(
            "SQL_EXPLORER_TOKEN must be set to serve over HTTP. Refusing to "
            "start an unauthenticated server."
        )

    import uvicorn

    app = server.streamable_http_app()
    app.add_middleware(TokenAuthMiddleware, token=token)

    # Bound to localhost deliberately. Exposing this beyond the machine
    # needs TLS as well as a token: without it the header travels in clear.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("SQL_EXPLORER_PORT", "8000")),
    )
