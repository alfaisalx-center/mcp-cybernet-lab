# Getting-started screencast — narration + shot script

**MCP CyberNet Lab · 2026-10-17**

A ready-to-record script for a public "how to get started" video, in English. It covers three
parts: (1) a tour of the GitHub repo, (2) a command-line demo, (3) the web-interface demo. Target
length **8–10 minutes**. Read the narration as written, or paraphrase in your own voice.

Two people are the audience: a researcher who finds the repo and wants to try it, and Ayman, who
will build his thesis on top of it.

---

## Before you record — hide your personal data

Nothing in the committed repo contains personal data, but your live screen does. Do this first:

1. **Terminal prompt.** Your prompt shows `/Users/akoubaa/…`. Either:
   - set a neutral prompt for the recording: `export PS1='\[\e[32m\]mcp-lab\[\e[0m\]:\W$ '`, and
   - work from a neutral path: copy or clone the repo to `~/demo/mcp-cybernet-lab` and record there.
2. **Git remotes.** `git remote -v` shows your private mirror (`aniskoubaa/…`). **Do not run
   `git remote -v` on camera**, and if you show the GitHub page, show only the public
   `alfaisalx-center/mcp-cybernet-lab` page — never the `aniskoubaa` one.
3. **The `private/` folder.** It is git-ignored and must never appear. Before recording, run
   `ls -a` once off-camera to confirm what is there, and **do not `cd private/` or `ls private/`**
   on camera. If you record from a fresh `git clone`, `private/` will not exist at all — this is the
   safest option.
4. **Browser.** If you show the browser for the web UI or GitHub, use a clean window — no bookmarks
   bar, no other tabs, no autofill showing your email. Use a private/incognito window.
5. **Shell history and env.** Clear scrollback before you start. Make sure no `*_API_KEY` value is
   printed on screen (the demo never needs to print one).
6. **Recommended recording setup:** `git clone https://github.com/alfaisalx-center/mcp-cybernet-lab
   ~/demo/mcp-cybernet-lab` into a clean folder, open a fresh terminal there, and record only that
   folder and the browser. This guarantees no private path, no private remote, and no `private/`.

---

## Part 0 — Title (0:00–0:20)

**On screen:** title card — "MCP CyberNet Lab — Getting Started" with the AlfaisalX line.

**Narration:**
> Welcome. This is MCP CyberNet Lab, an open framework from AlfaisalX at Alfaisal University for
> testing the security of Model Context Protocol systems. In the next few minutes I'll show you the
> repository, then run a testbed two ways — from the command line and from the web interface — so you
> can get started on your own machine right away.

---

## Part 1 — Tour of the GitHub repo (0:20–2:30)

**On screen:** the public GitHub page `github.com/alfaisalx-center/mcp-cybernet-lab`, README rendered.
Scroll slowly through the sections named below.

**Narration:**
> Here is the public repository. The README is the map. At the top it says what the project is: a
> containerised testbed and benchmark for MCP security, built from a single YAML file.
>
> Most published MCP security testbeds run every server as a local process on one machine — no
> network, no separate organisations, no authentication. This project builds a realistic network
> instead: each server runs in its own Docker container, each organisation is its own trust domain
> on its own Docker network, and a private network has no route to the internet.

**On screen:** scroll to "Educational and authorised use only".

**Narration:**
> This section matters. The project includes an ethical-hacking lab that demonstrates real attacks
> on MCP agents. Everything runs locally against synthetic data — every secret is fake — in
> containers with no route to the internet. Use it only on systems you own or are authorised to
> test. Every attack in the lab is paired with the defence that stops it.

**On screen:** scroll to the repo file tree. Point at these folders in turn.

**Narration:**
> A quick tour of the layout. `testbeds/` holds the YAML files that describe each network. `servers/`
> holds the MCP servers, including a synthetic company database. `mcp_cybernet_lab/` is the Python
> package and the `mcl` command line. `web/` is the React web interface. And `docs/` has the guides,
> including a full walkthrough of the ethical-hacking lab. That's the whole project — one YAML file
> in, a running Docker network out.

---

## Part 2 — Command-line demo (2:30–6:00)

**On screen:** clean terminal in `~/demo/mcp-cybernet-lab`.

**Narration:**
> Let's run it. You need Python 3.10 or newer and Docker. Install the package once.

**Type:**
```bash
pip install -e ".[dev]"
```

**Narration:**
> That gives you the `mcl` command. Everything starts from a testbed file. Let's look at the simplest
> one.

**Type:**
```bash
cat testbeds/toy-network.yaml
```

**Narration:**
> This describes two servers, each in its own container, and one agent that connects to them. First,
> validate the file — this checks it without touching Docker.

**Type:**
```bash
mcl validate testbeds/toy-network.yaml
```

**Narration:**
> It's valid. Now build it. `build` turns the YAML into a Docker Compose project — Dockerfiles, the
> compose file, and the servers' data with secret canaries planted in it.

**Type:**
```bash
mcl build testbeds/toy-network.yaml
```

**Narration:**
> Now bring it up. This builds the images and starts the containers. The `--wait` flag waits until
> they're healthy.

**Type:**
```bash
mcl up --wait testbeds/toy-network.yaml
```

**Narration:**
> And let's prove it works end to end with a smoke test. This has the agent connect to every server
> and list the tools each one offers.

**Type:**
```bash
mcl smoke testbeds/toy-network.yaml
```

**Narration:**
> Every server initialised and returned its tools. That's a live MCP network running on your machine,
> from one YAML file. When you're done, tear it down.

**Type:**
```bash
mcl down testbeds/toy-network.yaml
```

**Narration:**
> That's the whole command-line loop: validate, build, up, smoke, down. The security experiments —
> running the agent against the attack testbeds and measuring what leaks — use the same commands on a
> bigger testbed; the ethical-hacking lab guide in `docs/` walks through that step by step.

> **Optional recording note:** keep this section to the toy testbed, which starts in seconds. Do not
> run `mcl run` on camera — it needs an LLM API key and would print traffic; point viewers to the
> docs for it instead.

---

## Part 3 — Web-interface demo (6:00–9:00)

**On screen:** terminal.

**Narration:**
> If you'd rather not use the command line, there's a web interface. Start it with one command.

**Type:**
```bash
mcl web
```

**Narration:**
> It serves a local page on your own machine, at 127-0-0-1 port 8000, and opens your browser.

**On screen:** switch to the clean browser window showing `http://127.0.0.1:8000`.

**Narration:**
> On the left is every testbed in the project. Click one and you see it validated at a glance, with a
> summary of its servers, its trust domains, and whether a security gateway is enabled.

**On screen:** click `toy-network`, let the summary render. Point at the servers / domains / gateway
summary and the label badges.

**Narration:**
> You can edit the YAML right here, with live validation as you type — if you make a mistake it tells
> you immediately. And you can run the whole lifecycle from these buttons: build, up, smoke, reset,
> down. The output streams into the console below, so you never have to leave the page.

**On screen:** click **Build**, then **Up**, let the console stream. Then **Smoke**. Then **Down**.
Keep each step short in editing.

**Narration:**
> Same result as the command line — a running network — but driven entirely from the browser. This is
> the fastest way for a new user, or a classroom, to get started without memorising any commands.

**On screen:** back to terminal, press Ctrl-C to stop `mcl web`.

**Narration:**
> Stop the server with Control-C when you're finished.

---

## Part 4 — Closing and a note for Ayman (9:00–end)

**On screen:** back to the GitHub README, scrolled to "Extending the framework".

**Narration:**
> That's how to get started. To recap: clone the repo, `pip install`, and you can stand up a realistic
> MCP network from one YAML file — from the command line or the browser — and study how attacks on MCP
> agents work and how to defend against them.
>
> The framework is a baseline to build on: you can add your own MCP servers, write your own defensive
> guards, and even add your own `mcl` commands from a separate package without changing this
> repository.
>
> Ayman — this is your starting point. Clone it, run the toy testbed exactly as I did here to confirm
> your setup, then read the ethical-hacking lab guide in `docs/` and bring up the enterprise testbed.
> That gives you the full attack-and-defence environment your thesis builds on. Start there and we'll
> take the next step from the running lab.
>
> The repository is at github.com/alfaisalx-center/mcp-cybernet-lab. Thanks for watching.

---

## Appendix — exact command list (for a dry run before recording)

Run this once off-camera to make sure every command succeeds and images are cached (so the recording
is fast):

```bash
pip install -e ".[dev]"
mcl validate testbeds/toy-network.yaml
mcl build    testbeds/toy-network.yaml
mcl up --wait testbeds/toy-network.yaml
mcl smoke    testbeds/toy-network.yaml
mcl down     testbeds/toy-network.yaml
mcl web        # Ctrl-C to stop
```

Because the images are cached after the dry run, `mcl up` on camera will be much quicker.

## Appendix — suggested tools

- **Screen recording + voiceover:** QuickTime (built in on macOS) or OBS Studio (free).
- **Zoom the terminal font** to ~18pt so it's readable in the video.
- **Edit** the pauses out (image builds, container starts) to keep it under 10 minutes.
