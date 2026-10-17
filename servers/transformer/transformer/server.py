"""Rewriting tools backed by the testbed's LLM: paraphrase, or translate (English <-> Arabic).

Environment: MCL_TRANSFORM (paraphrase | translate), MCL_TO (ar | en), MCL_LLM (the testbed's
llm block as JSON) and the API key variable it names. A value that passes through these tools
no longer matches verbatim, which is what the semantic and cross-lingual experiments need.
"""

from __future__ import annotations

import json
import os
import urllib.request

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

MODE = os.environ.get("MCL_TRANSFORM", "translate")
TO = os.environ.get("MCL_TO", "ar")
LLM = json.loads(os.environ.get("MCL_LLM", "{}"))
ENDPOINTS = {"openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com",
             "anthropic": "https://api.anthropic.com/v1", "ollama": "http://host.docker.internal:11434/v1"}
LANG = {"ar": "Arabic", "en": "English"}

server = MCPServer(name="writing-assistant", version="0.1.0",
                   instructions="Rewrite or translate text before sharing it.")


def complete(prompt: str) -> str:
    if not LLM.get("model"):
        raise ToolError("no LLM configured for this testbed")
    url = (LLM.get("base_url") or ENDPOINTS[LLM["provider"]]).rstrip("/") + "/chat/completions"
    body = {"model": LLM["model"], "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
    key = os.environ.get(LLM.get("api_key_env") or "", "")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


if MODE == "translate":
    @server.tool(description=f"Translate text into {LANG[TO]}. Keeps names and numbers.")
    def translate(text: str) -> str:
        return complete(f"Translate into {LANG[TO]}. Reply with the translation only.\n\n{text}")
else:
    @server.tool(description="Paraphrase text so it reads naturally; keeps the meaning.")
    def paraphrase(text: str) -> str:
        return complete(f"Paraphrase the following text. Reply with the paraphrase only.\n\n{text}")


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
