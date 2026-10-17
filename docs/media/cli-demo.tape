# VHS tape — MCP CyberNet Lab command-line demo
# Renders a real terminal recording of the mcl CLI lifecycle.
# Run:  cd /tmp/mcp-cybernet-lab-demo && PATH="$PWD/.venv/bin:$PATH" vhs cli-demo.tape

Output docs/media/cli-demo.gif
Output docs/media/cli-demo.mp4

Set Shell bash
Set FontSize 18
Set Width 1240
Set Height 760
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

# --- hidden setup: neutral prompt, venv on PATH, clean screen -----------------
Hide
Type `cd /tmp/mcp-cybernet-lab-demo` Enter
Type `export PATH="$PWD/.venv/bin:$PATH"` Enter
Type `export PS1='mcp-lab $ '` Enter
Type `clear` Enter
Sleep 1s
Show

# --- title line ---------------------------------------------------------------
Type "# MCP CyberNet Lab — command-line demo" Sleep 800ms Enter
Sleep 1500ms

# --- 1. validate (measured ~0.2s) ---------------------------------------------
Type "mcl validate testbeds/toy-network.yaml" Sleep 500ms Enter
Sleep 3s

# --- 2. build (measured ~0.2s) ------------------------------------------------
Type "mcl build testbeds/toy-network.yaml" Sleep 500ms Enter
Sleep 3s

# --- 3. up (containers pre-warmed; measured ~6.5s) ----------------------------
Type "mcl up --wait testbeds/toy-network.yaml" Sleep 500ms Enter
Sleep 10s

# --- 4. smoke test: agent connects to every server, lists tools (~5s) ---------
Type "mcl smoke testbeds/toy-network.yaml" Sleep 500ms Enter
Sleep 8s

# --- 5. tear down (~3s) -------------------------------------------------------
Type "mcl down testbeds/toy-network.yaml" Sleep 500ms Enter
Sleep 6s

Type "# one YAML file -> a live, networked MCP testbed" Sleep 800ms Enter
Sleep 3s
