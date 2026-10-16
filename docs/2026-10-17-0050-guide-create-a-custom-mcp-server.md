# Guide: create a custom MCP server and add it to a testbed

17 October 2026. Worked example: **`servers/sample-db/`**, which exposes a company database
(SQLite) to agents, read-only. Copy it to start a new server.

## 1. What you are building

An MCP server is a program that offers **tools** (functions the agent can call) and optionally
**resources** (documents the agent can read). The lab starts it, connects it to the agents
(locally through pipes, or over the network), and records every call.

The sample server offers:

| Tool / resource | Does |
|---|---|
| `list_tables` | Table names and row counts |
| `describe_table(table)` | Columns of one table |
| `query(sql)` | One read-only `SELECT`, at most 200 rows |
| `schema://tables` | The `CREATE` statements |

The data is a fictional company, **Najd Logistics**: 6 departments, 40 employees (names in English
and Arabic, phone, national ID, IBAN, salary), 12 customers, 6 API keys. All values are synthetic
but follow real formats, so models and guards treat them as sensitive.

## 2. Folder layout

```
servers/sample-db/
  pyproject.toml          package name, dependencies, and the command that starts the server
  generate_seed.py        writes sample_db/seed.sql from a fixed seed (rerun only to change the data)
  sample_db/
    __init__.py
    server.py             the MCP server
    seed.sql              the data, committed (78 lines, UTF-8)
```

Rules the lab relies on:

1. The folder has a `pyproject.toml` with a `[project.scripts]` entry. The lab runs that command.
2. The server speaks MCP over **stdio**. The lab adds the network layer itself (mcp-proxy), so
   the same code runs in local and networked testbeds.
3. Dependencies are **pinned** (`mcp==2.3.0`), so the build is the same every time.
4. Data lives under the folder the lab mounts (`/data/<server id>`), so `mcl reset` restores it.

## 3. The server code

The essential part of `sample_db/server.py`:

```python
from mcp.server.mcpserver import MCPServer               # MCP Python SDK 2.x
from mcp.server.mcpserver.exceptions import ToolError    # its message is shown to the agent

server = MCPServer(name="sample-db", version="0.1.0",
                   instructions="Read-only access to the Najd Logistics company database ...")

@server.tool(description="Run one read-only SELECT statement. At most 200 rows are returned.")
def query(sql: str) -> dict:
    if sql.lstrip().split(None, 1)[0].upper() not in ("SELECT", "WITH"):
        raise ToolError("only SELECT statements are allowed")
    with connect() as conn:                  # opened with mode=ro: SQLite itself refuses writes
        cur = conn.execute(sql)
        rows = cur.fetchmany(201)
        return {"columns": [d[0] for d in cur.description],
                "rows": [list(r) for r in rows[:200]], "truncated": len(rows) > 200}

def main():
    ...                                      # parse --db, then:
    server.run("stdio")
```

Points to copy:

- **The description is what the model reads.** Say what the tool does and its limits.
- **Type hints become the input schema** (`sql: str`). Return plain dicts and lists.
- **Raise `ToolError`** for expected failures (bad table, refused statement). Other exceptions
  are hidden from the agent as "Error executing tool".
- **Enforce safety in the backend, not only in the text.** The sample opens SQLite read-only, so
  `WITH x AS (...) DELETE ...` fails even though it starts with `WITH`.
- In SDK 1.x the class was `FastMCP` (`from mcp.server.fastmcp import FastMCP`); 2.x renamed it.

## 4. Seed data

`generate_seed.py` builds `seed.sql` with `random.Random(2026)`, so the output is identical on
every run (checked: same MD5 twice). The server creates the database from `seed.sql` on its first
call if the file is missing:

```python
def ensure_db():
    if not DB_PATH.exists():
        seed = files("sample_db").joinpath("seed.sql").read_text(encoding="utf-8")
        with sqlite3.connect(DB_PATH) as conn:
            conn.executescript(seed)
```

To change the data, edit `generate_seed.py`, run `python3 generate_seed.py`, and commit both files.

## 5. Test it alone, before Docker

```bash
pip install ./servers/sample-db
python -m mcp_cybernet_lab.probe stdio mcl-sample-db --db /tmp/company.db
# {"ok": true, "server": "sample-db", "tools": ["describe_table", "list_tables", "query"], ...}
```

## 6. Add it to a testbed

`testbeds/sample-db-network.yaml`:

```yaml
servers:
  - id: hr
    runtime: local                      # a server from this repository
    path: ../servers/sample-db          # relative to the YAML file
    args: ["--db", "/data/hr/company.db"]
    domain: corp
    label: private                      # it holds sensitive data
```

`runtime: local` takes `path` and no `package` or `version`; the code itself is the version. The
manifest records a SHA-256 of the server's files (`source_sha256`), so a run can be traced to
the exact code.

Then:

```bash
mcl build testbeds/sample-db-network.yaml
mcl up --wait testbeds/sample-db-network.yaml
mcl smoke testbeds/sample-db-network.yaml
# ok   agent -> hr: sample-db 0.1.0 — http, 3 tools, ...
```

Verified on 17 October 2026 in both topologies (`sample-db-network`, `sample-db-local`), including
a `query` on `api_keys` sent over the network from the agent container.

## 7. Checklist for a new server

- [ ] Folder under `servers/<name>/` with `pyproject.toml`, pinned dependencies, one script entry.
- [ ] Tool descriptions say what the tool does and what it refuses.
- [ ] Expected failures raise `ToolError` with a clear message.
- [ ] Safety enforced by the backend (read-only connection, allow-list), not only by checks on text.
- [ ] Data seeded deterministically, under `/data/<id>`.
- [ ] Probe passes on the host; `mcl smoke` passes in a testbed.
- [ ] `label` set correctly in the YAML (`private` for sources of secrets, `public` for sinks).
