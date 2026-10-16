# MCP server catalogue: public servers we can add, and custom servers to build

17 October 2026. Which MCP servers MCP CyberNet Lab can host, in three groups:

- **A.** public servers that already work in the lab;
- **B.** public servers that can be added;
- **C.** custom servers to write in this repository, for scenarios no public server covers.

Every package name and version below was checked on npm or PyPI on 16–17 October 2026.

## Rules for choosing a server

1. **No real external accounts.** A server that needs a real Slack, GitHub or cloud account makes
   runs non-reproducible, costs money, and risks leaking real data. Prefer servers that talk to a
   **local backend container** (Postgres, Redis, Mailpit, MinIO, Gitea).
2. **Pin the version.** Write `version:` in the YAML; the manifest records what was installed.
3. **Deprecated packages are allowed but frozen.** Several reference servers were archived in 2025
   (marked below). They still install, but some need old dependencies (`with_packages`), as the
   sqlite server does.
4. **Label every server** `private`, `public` or `mixed`: a leak is a canary moving from a
   `private` server to a `public` one.

## How a server is added today

| Kind | Supported now? | YAML |
|---|---|---|
| npm package | Yes | `runtime: node`, `package: "<name>"` |
| PyPI package | Yes | `runtime: python`, `package: <name>` |
| Docker image (Go servers, e.g. Gitea, GitHub) | **Not yet** | planned: `runtime: image`, `image: <ref>` |
| Custom server in this repo (`servers/<name>/`) | Yes (17 Oct) | `runtime: local`, `path: ../servers/<name>`; see the guide `2026-10-17-0050-guide-create-a-custom-mcp-server.md` |

The "not yet" row is a small change to `schema.py` and `compose.py`. They are needed before
any server of group C or any Go server is added.

---

## A. Public servers already working (smoke-tested 16 October 2026)

| id in our YAML | Package | Runtime | Version | Role in experiments |
|---|---|---|---|---|
| fs | `@modelcontextprotocol/server-filesystem` | node | 1.0.0 | Private files: main canary source |
| git | `mcp-server-git` | python | 2026.10.10 | Repositories, commit history |
| sqlite | `mcp-server-sqlite` (archived) | python | 2025.4.25, with `mcp==1.6.0`, `pydantic==2.10.6` | Database rows |
| memory | `@modelcontextprotocol/server-memory` | node | 1.0.0 | Knowledge graph, persists across a task |
| clock | `mcp-server-time` | python | 2026.10.10 | Neutral utility (no data) |
| fetch | `mcp-server-fetch` | python | 2026.10.10 | Reaches the web: the main **sink** |

These are six of MCPHunt's eight servers.

## B. Public servers that can be added

### B1. Reference servers (Model Context Protocol project)

| Package | Runtime | Version | Status | Use |
|---|---|---|---|---|
| `@modelcontextprotocol/server-everything` | node | 1.0.0 | current | Test server exercising every MCP feature (tools, resources, prompts, sampling); protocol checks |
| `@modelcontextprotocol/server-sequential-thinking` | node | 1.0.0 | current | Reasoning helper; neutral |
| `@modelcontextprotocol/server-postgres` | node | 0.6.2 | **deprecated** | Read-only SQL on a local Postgres container |
| `@modelcontextprotocol/server-redis` | node | 2025.4.25 | **deprecated** | Key–value store on a local Redis container |
| `@modelcontextprotocol/server-puppeteer` | node | 2025.5.12 | **deprecated** | Browser automation; prefer Playwright below |
| `@modelcontextprotocol/server-github` | node | 2025.4.8 | **deprecated** | Needs a real GitHub account; avoid (rule 1) |
| `@modelcontextprotocol/server-gitlab` | node | 2025.4.25 | **deprecated** | Can target a **local GitLab** container |
| `@modelcontextprotocol/server-slack` | node | 2025.4.25 | **deprecated** | Needs a real Slack; replace with custom `team-chat` (C) |
| `@modelcontextprotocol/server-gdrive`, `-google-maps`, `-brave-search` | node | — | **deprecated** | Need Google or Brave accounts; avoid |
| `mcp-server-sentry` | python | 2025.1.14 | archived | Needs a Sentry account; avoid |

### B2. Third-party servers that fit the lab

| Package | Runtime | Version | Backend container | Use |
|---|---|---|---|---|
| `@playwright/mcp` | node | 0.0.83 | (browser inside the container) | Browser automation; likely MCPHunt's browser server, still to confirm from its harness |
| `shell-command-mcp` | node | 0.0.1 | — | Shell commands with an allow-list; name matches MCPHunt's, still to confirm |
| `mcp-email-server` | python | 1.13.1 | **Mailpit** (SMTP + IMAP) | Email: read inbox (source), send mail (sink) |
| `postgres-mcp` | python | 0.3.0 | **Postgres** | Maintained alternative to the deprecated Postgres server |
| `mcp-server-redis` | python | 0.1.1 | **Redis** | Maintained alternative to the deprecated Redis server |
| `@benborla29/mcp-server-mysql` | node | 2.0.9 | **MySQL** | Business database |
| `mcp-mongo-server` | node | 3.0.1 | **MongoDB** | Document database |
| `mcp-server-qdrant` | python | 0.8.1 | **Qdrant** | Vector store: RAG memory, semantic leaks |
| `mcp-server-docker` | python | 0.3.0 | Docker socket | DevOps agent; **dangerous**, host access; isolate or avoid |
| `kubernetes-mcp-server` / `mcp-server-kubernetes` | python | 0.0.67 / 0.1.6 | **kind** cluster | Cloud-operations scenarios (later) |
| `mcp-atlassian` | python | 0.23.1 | Jira/Confluence | Needs Atlassian; only with a local instance |
| `awslabs.aws-api-mcp-server` | python | 1.5.6 | **LocalStack** | Cloud scenarios against a local AWS emulator |
| `@notionhq/notion-mcp-server` | node | 2.5.2 | Notion | Needs a Notion account; avoid |
| `@upstash/context7-mcp` | node | 4.4.2 | Internet | Documentation lookup; neutral, needs internet |

Go servers distributed as Docker images (need `runtime: image`): **Gitea MCP** (git hosting and
CI on a local Gitea, the best replacement for GitHub) and **GitHub's official MCP server** (real
account; avoid).

### Suggested first additions

1. `@playwright/mcp` and `shell-command-mcp`: complete MCPHunt's eight servers (confirm from its harness).
2. `mcp-email-server` + Mailpit: email is the most realistic exfiltration channel and is missing from MCPHunt.
3. `postgres-mcp` + Postgres: a real database with canaries inside rows, not only in a file.
4. Gitea MCP + Gitea: git hosting and CI, also missing from MCPHunt.

---

## C. Custom servers to build in this repository

Written in Python with the official SDK (`mcp`, FastMCP style), one folder each under
`servers/<name>/`, with seeded data so that runs are reproducible. They give scenarios that no
public server offers.

### C1. Private data sources (where canaries live)

| Server | Holds | Why custom |
|---|---|---|
| `hr-payroll` | Employees, salaries, Saudi IBANs, national IDs | Realistic regulated PII, seeded from the lab seed |
| `crm` | Customers, contracts, phone numbers; names in **Arabic and English** | Cross-lingual leaks need Arabic records |
| `secrets-vault` | API keys, tokens, passwords | A clear, labelled credential store |
| `arabic-docs` | Arabic internal documents (policies, memos) with embedded PII | No public Arabic data server exists |

### C2. Sinks and channels (where leaks land)

| Server | Does | Why custom |
|---|---|---|
| `team-chat` | Slack-like channels: post and read messages; some channels are external | Replaces the real-Slack server (rule 1); every post is logged |
| `public-paste` | Pastebin or public web form; records everything submitted | A clean, fully observable public sink: ground truth for leaks |
| `webhook-sink` | Accepts any HTTP POST and records it | The exfiltration target used in attack papers, kept inside the lab |
| `ticketing` | Helpdesk tickets written by "customers" | Mixed trust: user text is an injection vector, replies are a sink |

### C3. Transformations (for the semantic and cross-lingual research questions)

| Server | Does | Why custom |
|---|---|---|
| `translator` | English↔Arabic translation tool (local model or fixed dictionary) | Translated canaries defeat exact matching |
| `summarizer` | Paraphrase and summarise tool | Paraphrased canaries defeat exact matching |

### C4. Adversarial servers (attacks, milestone M7)

| Server | Attack | Notes |
|---|---|---|
| `poisoned-tools` | Tool descriptions with hidden instructions (tool poisoning) | Payloads read from the YAML, so attacks are configurable |
| `rug-pull` | Benign descriptions first, malicious after N calls or after approval | Tests guards that check tools only once |
| `shadowing` | Registers tool names that collide with another server's tools | Cross-server confusion |
| `web-mock` | Offline "internet": pages with injected instructions | Indirect prompt injection without real websites; replaces `fetch` in closed runs |
| `log-poisoner` | Writes text meant to mislead a guard that learns from its own logs | The central attack of the self-evolving guard thesis |

### C5. Lab infrastructure

| Server | Does |
|---|---|
| `audit-log` | Exposes the gateway's message log over MCP, for the self-evolving guard to read |
| `canary-oracle` | Answers "is this string a planted canary?"; used only by the evaluator, never by agents |

### Suggested build order

1. ~~`runtime: local` support, plus one custom server as the template~~ done: `servers/sample-db`.
2. `public-paste` and `webhook-sink`: observable sinks are needed for every leak measurement.
3. `hr-payroll` and `crm` (with Arabic records): realistic private sources.
4. `team-chat`, `ticketing`: realistic multi-party channels.
5. `translator`, `summarizer`: semantic and cross-lingual experiments.
6. Adversarial servers, with milestone M7.
