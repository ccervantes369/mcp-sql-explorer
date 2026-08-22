from mcp.server import MCPServer

# The server object. The name is how clients identify us.
server = MCPServer(name="sql-explorer")


@server.tool()
def ping() -> str:
    """Check that the server is alive."""
    return "pong"


def main() -> None:
    # Start listening. Default transport is stdio.
    server.run()
