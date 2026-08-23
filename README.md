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
uv run pytest                             # 13 tests, all guards covered
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

## Design notes

**Why the schema is a tool, not a resource.** MCP also offers *resources*
for readable content. A schema would fit there, but tools are supported by
every client today, and the model needs the schema on demand rather than
attached up front.

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

Thirteen tests, covering every guard: refused statements, refused columns
(including the filter-only leak), truncation, unknown table names, and the
query timeout. `tests/conftest.py` builds the sample database if it is
missing, so the suite runs on a fresh clone.
