# MCP CyberNet Lab

**A containerised testbed and benchmark for Model Context Protocol (MCP) security — built from one YAML file.**
AlfaisalX, Center of Excellence for Cognitive Robotics and Autonomous Agents, Alfaisal University.

MCP CyberNet Lab lets you stand up a realistic network of MCP servers and an LLM agent on your own
machine, run attacks against them in a contained environment, and measure what leaks. It is meant
as a **teaching tool** and as a **baseline framework and benchmark** that other researchers can build
their own MCP-security experiments on.

Published MCP security testbeds run every server as a local process on one machine, with no network,
no separate organisations and no authentication. MCP CyberNet Lab builds a realistic MCP network
instead:

- each server runs in its own Docker container;
- each organisation (trust domain) has its own Docker network, and a private network has no route to the internet;
- per-domain authentication (bearer token) can be required;
- network delay and packet loss can be set per server;
- an optional gateway logs every tool call and can block it with a guard;
- secret **canaries** are planted in the servers' data, so a leak is detected deterministically, without an LLM judge.

The same YAML can also describe the **local** setup used in the literature, so results on the two
topologies can be compared directly.

## Educational and authorised use only

This project includes a small **ethical-hacking lab** that demonstrates attacks on MCP servers and
agents. It exists for teaching and defensive research. Everything runs locally against **synthetic
data** (every secret is format-authentic but fake) in containers with no route to the internet; the
"exfiltration" endpoints are local recorders. Use it only on infrastructure you own or are
authorised to test. It is not a tool for attacking real systems, and the demonstrations are paired
with the defence that stops them. See [`docs/2026-10-17-0210-ethical-hacking-lab.md`](docs/2026-10-17-0210-ethical-hacking-lab.md).

## Quick start

Requirements: Python ≥ 3.10 and Docker with Compose v2. For the web UI, Node ≥ 18.

```bash
pip install -e ".[dev]"

# Option A — the web interface (configure and run testbeds in the browser)
mcl web                                   # http://127.0.0.1:8000

# Option B — the command line
mcl validate testbeds/toy-network.yaml    # check the file (no Docker)
mcl build    testbeds/toy-network.yaml    # write build/toy-network/
mcl up --wait testbeds/toy-network.yaml   # build images, start containers
mcl smoke    testbeds/toy-network.yaml    # every client initialises every server and lists its tools
mcl down     testbeds/toy-network.yaml
```

`pip install -e .` creates the `mcl` command (also `mcp-cybernet-lab`). Without installing, run the
same commands as `python -m mcp_cybernet_lab <command> …` once `pyyaml` and `pydantic` are present.

## The web interface

`mcl web` serves a local page (bound to `127.0.0.1`) to:

- browse the testbeds in `testbeds/` and see each one validated at a glance;
- edit or write a testbed YAML, with live validation and a summary of its servers, domains and gateway;
- run **build / up / smoke / reset / down** and watch the output;
- read the server catalogue.

The front-end is a React app in [`web/`](web/), pre-built into the package so `mcl web` works out of
the box. To change it: `cd web && npm install && npm run build` (writes `mcp_cybernet_lab/webdist/`),
or `npm run dev` for hot reload against a running `mcl web`.

## The YAML file

```yaml
testbed: toy-network
version: 1
seed: 0                       # all randomness (canaries, data, noise) comes from here

defaults:
  transport: http             # stdio = local pipes (as in the literature); http = own container, networked

domains:                      # trust domains: one Docker network each
  - id: corp                  # no `internet: true` -> the network has no route out
  - id: public
    internet: true

servers:
  - id: fs
    package: "@modelcontextprotocol/server-filesystem"
    runtime: node             # node | python | local (a server from this repo's servers/)
    version: "1.0.0"
    args: ["/data/fs"]        # server data is mounted at /data/<id>
    domain: corp
    label: private            # private | public | mixed
    data: { from: data/toy-fs }
  - id: clock
    package: mcp-server-time
    runtime: python
    version: "2026.10.10"
    domain: public
    label: public
    network: { delay_ms: 80, jitter_ms: 10, loss: 0.01 }   # applied with tc netem

clients:
  - id: agent
    servers: [fs, clock]

canaries:
  per_server: 6               # format-authentic secrets: sk_live_*, AKIA*, ghp_*, SA IBAN, ...
```

Every field is defined in [`mcp_cybernet_lab/schema.py`](mcp_cybernet_lab/schema.py). Unknown fields
are errors, not ignored.

## Setting up MCP servers

- **Existing public servers** — [`docs/2026-10-17-0032-mcp-server-catalogue.md`](docs/2026-10-17-0032-mcp-server-catalogue.md)
  lists the servers that work today and others you can add. Most speak stdio only; at image-build
  time [`install_server.py`](images/runtime/install_server.py) installs the package and, in a
  networked testbed, [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) serves it over Streamable
  HTTP at `http://<id>:8080/mcp`. The server code is identical locally and networked; only the
  transport changes.
- **Your own server** — [`docs/2026-10-17-0050-guide-create-a-custom-mcp-server.md`](docs/2026-10-17-0050-guide-create-a-custom-mcp-server.md)
  walks through [`servers/sample-db/`](servers/sample-db), a read-only company database (synthetic
  English and Arabic records) exposed over MCP with `runtime: local`.

## The ethical-hacking lab

[`docs/2026-10-17-0210-ethical-hacking-lab.md`](docs/2026-10-17-0210-ethical-hacking-lab.md) is a
guided walkthrough of the standard MCP attack patterns against the synthetic *Najd Logistics*
enterprise, each shown first succeeding and then **blocked by the taint-tracking guard**:

| Demo | Pattern | Lesson |
|---|---|---|
| Poisoned tool | A tool's description tells the agent to read a secret and pass it on | Treat tool descriptions as untrusted input |
| Rug pull | A tool behaves, then changes its instructions after a few calls | Pin and re-check tool definitions |
| Prompt injection | A fetched web page carries instructions to the agent | Data from a tool is data, not commands |
| Cross-lingual leak | A secret is translated before being published | Detect secrets by value, across languages |

Run a demo with `mcl build/up` on `testbeds/enterprise-attacks.yaml`, then `mcl run … --tasks
tasks/attacks.yaml` (needs an LLM API key); compare the guarded and unguarded runs with
`mcl compare`.

## Measuring

```bash
mcl run     testbeds/enterprise-network.yaml --tasks tasks/enterprise.yaml   # run the agent, detect leaks
mcl report  runs/enterprise-network/<id>                                     # rates with 95% Wilson intervals
mcl compare runs/A runs/B                                                    # paired comparison, exact McNemar
```

`mcl run` needs an OpenAI-compatible endpoint; set the key named by the testbed's `llm.api_key_env`.

## What `build` writes

```
build/<testbed>/
  docker-compose.yml     generated; do not edit        data/<server>/     each server's data (canaries planted)
  dockerfiles/           one per container              data.pristine/     copy restored by `mcl reset`
  context/               runtime files for the images   canaries.json      ground truth: every canary
  policy/current.json    the guard policy (if any)      manifest.json      source hash, seed, commit, versions
```

## Shipped testbeds

| File | What |
|---|---|
| `toy-{local,network}` | Two servers; checks an installation |
| `mcphunt-{local,network}` | Six servers of MCPHunt (filesystem, git, sqlite, memory, time, fetch) for reproduction |
| `sample-db-{local,network}` | The custom company-database server next to a public fetch server |
| `enterprise-{local,network}` | The *Najd Logistics* enterprise: private data servers and public sinks |
| `enterprise-guarded` | The enterprise with the taint-tracking gateway enabled |
| `enterprise-attacks` | The guarded enterprise with the attacker servers of the ethical-hacking lab |

Each `local`/`network` pair differs only in its topology lines and plants the same canaries.

## Tests

```bash
pytest -q        # schema, canaries, generated compose, guard and detector; no Docker needed
```

## Extending the framework

MCP CyberNet Lab is a baseline others can build on:

- **New servers** — drop a package under `servers/` and reference it with `runtime: local`.
- **New guards** — subclass `Guard` in [`mcp_cybernet_lab/guards.py`](mcp_cybernet_lab/guards.py) and register it.
- **New commands** — a separate package can add `mcl` subcommands through the `mcp_cybernet_lab.commands`
  entry point, without modifying this repository.

## Roadmap

| Milestone | Content | |
|---|---|---|
| M0 | Schema, validation, generator | ✅ |
| M1 | LLM agent harness; reproduce MCPHunt propagation rates (local topology) | ✅ |
| M2 | Networked topology; local-vs-networked comparison | ✅ |
| M3 | Per-domain authentication (bearer token) | ✅ |
| M4 | Gateway hosting a guard (pass-through, taint-tracking) | ✅ |
| M5 | Realistic backends: webhook sink, paste site, mock web | ✅ |
| M6 | Web interface for configuration and setup | ✅ |
| M7 | Ethical-hacking lab: attacker servers, English↔Arabic transforms, cross-lingual detection | ✅ |

## Licence

Released for **educational and research use**. A formal open-source licence will be attached before
the first tagged release; until then, please contact the AlfaisalX center for other uses.
