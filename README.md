# MCP CyberNet Lab

**Containerised MCP network testbeds, generated from one YAML file.**
AlfaisalX, Center of Excellence for Cognitive Robotics and Autonomous Agents, Alfaisal University.

Published MCP security testbeds run every server as a local process on one machine. They have no
network, no separate organisations and no authentication. mcp-cybernet-lab builds a realistic MCP network
instead:

- each server runs in its own Docker container;
- each organisation (trust domain) has its own Docker network;
- network delay and packet loss can be set per server;
- secret "canaries" are planted in the servers' data, so a leak is detected without an LLM judge.

The same YAML can also describe the **local** setup used in the literature. Results on the two
topologies can then be compared directly.

> Status: **v0.1, milestones M0 and the first part of M2.** Schema, generator, local and networked
> topologies, network conditions, canaries and smoke test work. Agent harness (M1), authentication
> (M3), the guard gateway (M4), attacks and transforms (M7) are planned. The schema accepts them
> already, and `build` refuses them with the milestone name.

## Quick start

Requirements: Python ≥ 3.10 and Docker with Compose v2.

```bash
pip install -e ".[dev]"
mcl validate testbeds/toy-network.yaml   # check the file (no Docker)
mcl build    testbeds/toy-network.yaml   # write build/toy-network/
mcl up --wait testbeds/toy-network.yaml  # build images, start containers
mcl smoke    testbeds/toy-network.yaml   # every client initializes every server and lists its tools
mcl reset    testbeds/toy-network.yaml   # restore planted data between tasks
mcl down     testbeds/toy-network.yaml
```

`pip install -e .` creates the `mcl` command (also available as `mcp-cybernet-lab`) from
`[project.scripts]` in `pyproject.toml`. Without installing, run the same commands with Python
from the repository folder, once `pyyaml` and `pydantic` are installed:

```bash
python -m mcp_cybernet_lab smoke testbeds/toy-network.yaml
```

`mcl smoke` should show:

```
ok   agent -> fs: secure-filesystem-server 1.0.0 — http, 14 tools, ...
ok   agent -> clock: mcp-time 2026.10.10 — http, 2 tools, ...
2/2 connections ok
```

## The YAML file

```yaml
testbed: toy-network
version: 1
seed: 0                       # all randomness (canaries, later data and noise) comes from here

defaults:
  transport: http             # stdio = local pipes (as in MCPHunt); http = own container, networked

domains:                      # trust domains: one Docker network each
  - id: corp                  # internet: false (default) -> the network has no route out
  - id: public
    internet: true

servers:
  - id: fs
    package: "@modelcontextprotocol/server-filesystem"
    runtime: node             # node | python
    version: "1.0.0"          # pin it: the build warns when a version is missing
    args: ["/data/fs"]        # server data is mounted at /data/<id> by default
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

Every field is defined in [`mcp_cybernet_lab/schema.py`](mcp_cybernet_lab/schema.py). Unknown fields are errors, not
ignored. `with_packages` pins dependencies of servers that break with current libraries (see the
sqlite server in `testbeds/mcphunt-*.yaml`).

## What `build` writes

```
build/<testbed>/
  docker-compose.yml     generated; do not edit
  dockerfiles/           one per container
  context/               runtime files copied into the images
  data/<server>/         each server's data, with canaries planted in credentials.env
  data.pristine/         copy restored by `mcl reset`
  canaries.json          ground truth: every canary, its server, kind and value
  manifest.json          source file hash, seed, mcp-cybernet-lab commit, versions requested and installed
  smoke.json             written by `mcl smoke`
```

## How a server becomes a container

Most public MCP servers speak stdio only. At image build time
[`install_server.py`](images/runtime/install_server.py) installs the package in its own folder and
exposes it as `mcp-<id>`. In a networked testbed,
[mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) (0.13.0) serves it over Streamable HTTP at
`http://<id>:8080/mcp`. In a local testbed the same `mcp-<id>` runs inside the client container
over stdio. The server code is identical in both cases; only the transport changes.

## Shipped testbeds

| File | What |
|---|---|
| `toy-local.yaml` / `toy-network.yaml` | Two servers; checks an installation |
| `mcphunt-local.yaml` / `mcphunt-network.yaml` | Six of the eight servers of MCPHunt (arXiv 2604.27819): filesystem, git, sqlite, memory, time, fetch. The shell-command and browser servers are still to be added from MCPHunt's harness. |

The two files of each pair differ only in their topology lines, and they plant the same canaries.

## Tests

```bash
pytest -q        # schema, canaries, generated compose; no Docker needed
```

## Roadmap

| Milestone | Content |
|---|---|
| M0 | Schema, validation, generator ✅ |
| M1 | Agent harness; reproduce MCPHunt's propagation rates in the local topology |
| M2 | Networked topology ✅ (smoke level); local vs networked comparison on MCPHunt's tasks |
| M3 | Authentication per trust domain (token, OAuth 2.1) |
| M4 | Gateway container hosting a guard (pass-through, MCPHunt guard, Fides-style, self-evolving) |
| M5 | Realistic backends: email, object storage, git hosting |
| M6 | Self-evolving guard experiments in rounds |
| M7 | Attacker servers, log poisoning, paraphrase and English↔Arabic transforms |

## Licence

Not yet decided; to be set before public release.
