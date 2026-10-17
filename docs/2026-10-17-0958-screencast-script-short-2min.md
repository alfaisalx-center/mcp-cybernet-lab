# Short screencast — 2-minute quick start (narration + shots)

**MCP CyberNet Lab · 2026-10-17**

A ready-to-record 2-minute version for social media (LinkedIn, X, YouTube Shorts). Quick start only,
no repo tour. For the full version see
[`2026-10-17-0956-screencast-script-getting-started.md`](2026-10-17-0956-screencast-script-getting-started.md).

Same "hide your personal data" rules apply — **record from a fresh clone in a neutral folder**
(`~/demo/mcp-cybernet-lab`), use an incognito browser, never run `git remote -v` and never open the
`private/` folder on camera. Do the dry run first so Docker images are cached and the recording is fast.

---

## Scene 1 — Hook (0:00–0:15)

**On screen:** title card — "MCP CyberNet Lab — Test MCP security in one command."

**Narration:**
> How do you test whether an AI agent connected to MCP servers can leak private data? MCP CyberNet
> Lab, an open framework from AlfaisalX, stands up a realistic MCP network on your machine from a
> single YAML file. Here's the 2-minute start.

---

## Scene 2 — Install and run, command line (0:15–1:05)

**On screen:** clean terminal. Type each command; edit out the waits.

**Narration:**
> You need Python and Docker. Install once.

**Type:**
```bash
pip install -e ".[dev]"
```

**Narration:**
> Then take any testbed and bring it up — this builds a Docker network of MCP servers and an agent.

**Type:**
```bash
mcl up --wait testbeds/toy-network.yaml
```

**Narration:**
> And smoke-test it: every server initialises and lists its tools.

**Type:**
```bash
mcl smoke testbeds/toy-network.yaml
```

**Narration:**
> That's a live MCP network, from one file.

---

## Scene 3 — The web interface (1:05–1:45)

**On screen:** terminal → `mcl web`, then switch to incognito browser at `http://127.0.0.1:8000`.

**Narration:**
> Prefer a browser? Run `mcl web`. Pick a testbed, see it validated at a glance, edit the YAML with
> live validation, and run the whole lifecycle — build, up, smoke, down — from these buttons, with
> the output right there.

**On screen:** click a testbed, then click **Up** then **Smoke**, let the console stream briefly.

---

## Scene 4 — Close (1:45–2:00)

**On screen:** title card with the URL `github.com/alfaisalx-center/mcp-cybernet-lab`.

**Narration:**
> It also ships a guided ethical-hacking lab — real MCP attacks on synthetic data, each paired with
> the defence that stops it. For teaching and for research. It's open. Link below. Try it today.

---

## One-take command list (for the recording)

```bash
pip install -e ".[dev]"
mcl up --wait testbeds/toy-network.yaml
mcl smoke    testbeds/toy-network.yaml
mcl web      # Ctrl-C to stop
# off-camera when done: mcl down testbeds/toy-network.yaml
```

## Suggested caption (for the post)

> MCP CyberNet Lab — an open framework from AlfaisalX, Alfaisal University, to test the security of
> Model Context Protocol systems. Stand up a realistic MCP network from one YAML file, run attacks on
> synthetic data in containers, and measure what leaks — from the command line or the browser. For
> teaching and research. #MCP #AIsecurity #LLM #AgentSecurity
