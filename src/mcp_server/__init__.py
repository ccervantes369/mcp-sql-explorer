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


def main() -> None:
    # Start listening. Default transport is stdio.
    server.run()
