# sql-explorer

An MCP server that lets an AI assistant answer questions about a SQLite
database in plain language — without being able to damage it or read the
parts you have marked off limits.

Ask *"which city spends the most?"* and the model discovers the tables,
reads the schema, writes its own SQL, and answers. It never gets a chance
to write, delete, or read a blocked column.

```
You:    Which city has spent the most in total?
Claude: Lyon, with 14 orders totalling 2,840.03.

You:    Give me the email and phone of every customer.
Claude: I can't — the server refuses access to customers.email.
```

## Why it exists

Handing a language model a database connection is a genuinely risky idea.
Three things can go wrong:

| Risk | How it is handled |
|---|---|
| It issues `DELETE`, `UPDATE` or `DROP` | Only statements beginning with `SELECT` are accepted |
| It reads personal data | A **SQLite authorizer** denies configured columns inside the engine |
| It returns millions of rows | Results are capped at 500 rows and queries are aborted after 5 seconds |

The second one is the interesting one. The blocked columns are not filtered
out of the SQL text — SQLite asks permission before reading *any* column and
the server answers. That means a query which never mentions `email`, but
filters on it to leak addresses one guess at a time, is refused too:

```sql
SELECT name FROM customers WHERE email LIKE '%ana%'
-- Query refused: access to customers.email is prohibited
```

There is no phrasing that gets around it, because the check does not look at
the phrasing.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <your-repo-url>
cd mcp_server
uv sync
uv run python scripts/make_sample_db.py   # builds the practice database
uv run pytest                             # 28 tests
```

To poke at the tools by hand in a browser (needs Node.js):

```bash
uv run mcp dev src/mcp_server/__init__.py
```

## Using it with Claude Desktop

Settings → Developer → Edit config, then add:

```json
{
  "mcpServers": {
    "sql-explorer": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp_server", "mcp-server"],
      "env": {
        "SQL_EXPLORER_DB": "/absolute/path/to/your.db",
        "SQL_EXPLORER_BLOCKED_COLUMNS": "users.password_hash, users.ssn"
      }
    }
  }
}
```

Restart the app afterwards. Editing the file while it is running does not
work — the app overwrites it on exit.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SQL_EXPLORER_DB` | `sample.db` in this repo | Which SQLite file to serve |
| `SQL_EXPLORER_BLOCKED_COLUMNS` | `customers.email, customers.phone` | Columns to deny, as `table.column`, comma separated |
| `SQL_EXPLORER_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `SQL_EXPLORER_PORT` | `8000` | Port to listen on, HTTP transport only |
| `SQL_EXPLORER_TOKEN` | none | Bearer token required by the HTTP transport. No default, and no server without it |

A value that is not shaped like `table.column` makes the server refuse to
start. A typo in a security setting should be loud, not silently ignored.

## Tools

| Tool | Purpose |
|---|---|
| `list_tables()` | Names of every table |
| `describe_table(table)` | Columns of one table: name, type, whether required |
| `run_query(sql)` | Runs a `SELECT` and returns `{rows, row_count, truncated}` |
| `ping()` | Liveness check |

`run_query` reports `truncated: true` when the result hit the row cap, so a
partial answer is never mistaken for a complete one.

## Resources

| URI | Content |
|---|---|
| `schema://tables` | Every table with its columns, one line each |
| `schema://{table}` | One table in detail: column name, type, whether required |

Columns the server refuses to read are marked `[blocked]`:

```
customers(id, name, email [blocked], phone [blocked], city, signup_date)
```

That is deliberate. The protection does not depend on secrecy — the
authorizer refuses regardless of what the caller knows — so naming the
blocked columns costs nothing and saves a wasted `SELECT *` that would only
be rejected.

`schema://{table}` is a *template*: one definition serves one address per
table, whatever tables the database turns out to have.

## Prompts

| Prompt | What it does |
|---|---|
| `analyze_table(table)` | Walks one table: size, distributions, gaps, outliers |
| `data_quality_report()` | Audits for duplicates, orphans, impossible values, suspicious uniformity |

Prompts return instructions, not data. They describe how to drive this
server well — read the schema first, aggregate rather than list rows, do not
reach for blocked columns — so a user who does not know the database can
still ask a good question.

## Running it over HTTP

By default the server runs on **stdio**: a client launches it as a child
process and they talk over pipes. Nothing needs authenticating, because
the operating system already decided who may start the process.

Set `SQL_EXPLORER_TRANSPORT=streamable-http` and it becomes a web service
instead — and then anyone who can reach the port can talk to it. So a token
is mandatory:

```bash
SQL_EXPLORER_TRANSPORT=streamable-http \
SQL_EXPLORER_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
uv run mcp-server
```

Every request must carry it:

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer $SQL_EXPLORER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

Anything else gets `401` and never reaches a tool, a resource, or the
database.

**With no `SQL_EXPLORER_TOKEN` set, the server refuses to start.** It does
not fall back to running open with a warning printed somewhere. A missed
warning leaves the database published while everything looks healthy, which
is the worst kind of failure: silent, and indistinguishable from success.

The listener binds `127.0.0.1`. Read the security note below before
changing that.

### Before exposing this to a network

- **TLS is not optional.** A bearer token over plain HTTP travels in clear
  text; anyone between the client and the server can read it and reuse it.
  Put this behind a reverse proxy that terminates HTTPS.
- **A shared token is not OAuth.** The MCP specification calls for OAuth 2.1
  for remote servers, which gives per-user identity, scopes and revocation.
  One shared secret gives none of those: every caller is the same caller,
  and rotating it locks everyone out at once. That is a reasonable trade for
  a single-user or small-team service, and the wrong one for a public
  deployment.
- **Rate limiting is absent.** Nothing here slows down a caller hammering
  expensive queries.

## Design notes

**Why the schema is both a tool and a resource.** `describe_table` returns
structured rows for a model to compute with; `schema://customers` returns a
readable page a person can attach to a conversation. The same information in
two shapes, because tools and resources are consumed differently. The tool is
also the reliable path, since resource support still varies between clients.

**Why `SELECT *` is refused.** The expansion includes the blocked columns,
so the authorizer denies it. The model has to name the columns it wants.
Slightly more work for it; no accidental leaks.

**Why `describe_table` interpolates its argument.** `PRAGMA table_info`
cannot take a bound parameter, so the table name goes into the statement
directly — after being checked against the real table list. An allowlist,
not an escape.

## Limitations

- SQLite only. Postgres or MySQL would need a different authorization
  approach, since the authorizer callback is a SQLite feature.
- Blocking is per column, not per row. There is no way to say "only this
  user's rows".
- The 5 second timeout is wall clock, not CPU time.

## Running the tests

```bash
uv run pytest -v
```

Twenty-eight tests in three files.

`tests/test_guards.py` covers every safety guard: refused statements,
refused columns including the filter-only leak, truncation, unknown table
names, and the query timeout.

`tests/test_resources_and_prompts.py` covers what the resources render and
what the prompts say, including that blocked columns keep their `[blocked]`
marker and that the prompts still name the tools and URIs they rely on.

`tests/test_http_auth.py` covers the HTTP door: a correct token passes, a
missing header, a wrong token, a bare token without the `Bearer` prefix and
a truncated token are all refused, and the server refuses to start in HTTP
mode with no token set. Each refusal asserts the request never reached the
endpoint, not merely that the status was `401`.

`tests/conftest.py` builds the sample database if it is missing, so the
suite runs on a fresh clone.

The guard and resource tests call the server's functions directly rather
than through an MCP session, so they would not catch a decorator being
removed.
