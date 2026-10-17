"""The testbed YAML schema.

One YAML file describes one MCP network: trust domains, servers, clients, the gateway,
canary secrets and logging. `load_testbed` in loader.py turns the file into a `Testbed`.

Fields that belong to later milestones (auth, guards, attacks, transforms) are accepted by the
schema so that testbed files can be written now, but `build` refuses them until implemented.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
SERVERS_DIR = Path(__file__).resolve().parent.parent / "servers"  # custom servers shipped with the lab
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")  # usable as a Docker service and DNS name


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in the YAML is an error, not ignored


def _check_id(value: str) -> str:
    if not ID_RE.match(value):
        raise ValueError(f"id '{value}' must match {ID_RE.pattern} (lowercase, digits, '-')")
    return value


class NetworkConditions(Strict):
    delay_ms: int = Field(0, ge=0, le=10_000)
    jitter_ms: int = Field(0, ge=0, le=10_000)
    loss: float = Field(0.0, ge=0.0, le=1.0)  # fraction of packets dropped

    @property
    def is_default(self) -> bool:
        return self.delay_ms == 0 and self.jitter_ms == 0 and self.loss == 0.0


class Defaults(Strict):
    transport: Literal["stdio", "http"] = "stdio"
    network: NetworkConditions = NetworkConditions()


class Domain(Strict):
    """A trust domain: an organisation that owns servers. One Docker network per domain."""

    id: str
    auth: Literal["none", "token", "oauth"] = "none"
    internet: bool = False  # False = the domain network has no route to the internet

    _id = field_validator("id")(_check_id)


class LLM(Strict):
    """The model behind the agents (and behind LLM-based transforms). OpenAI-compatible API."""

    provider: Literal["openai", "deepseek", "anthropic", "vllm", "ollama", "none"] = "none"
    model: str | None = None
    base_url: str | None = None  # None = the provider's public endpoint (required for vllm)
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_steps: int = Field(12, ge=1, le=100)  # tool-call rounds before the agent must answer
    api_key_env: str | None = None  # name of a host environment variable; never the key itself


class ServerData(Strict):
    source: str | None = Field(None, alias="from")  # folder copied into the server, relative to the YAML
    mount: str | None = None  # where the folder appears inside the server; default /data/<server id>


class Server(Strict):
    id: str
    runtime: Literal["node", "python", "local"]
    package: str | None = None  # npm or PyPI package name (runtime node or python)
    path: str | None = None  # folder of a custom Python server, relative to the YAML (runtime local)
    version: str | None = None  # pin for reproducibility; None = latest at build time
    with_packages: list[str] = []  # extra pins installed with the server, e.g. "mcp==1.6.0"
    args: list[str] = []
    env: dict[str, str] = {}
    domain: str | None = None
    label: Literal["private", "public", "mixed"] = "private"
    transport: Literal["stdio", "http"] | None = None  # None = defaults.transport
    network: NetworkConditions | None = None  # None = defaults.network
    data: ServerData | None = None
    plant_canaries: bool = True  # write canaries into the server's data folder
    extra_canaries: str | None = None  # JSON list of {kind, name, value} the server holds itself
                                       # (e.g. secrets in database rows), relative to the YAML

    _id = field_validator("id")(_check_id)

    @model_validator(mode="after")
    def _source(self) -> "Server":
        if self.runtime == "local":
            if not self.path or self.package or self.version:
                raise ValueError(f"server '{self.id}': runtime local takes 'path' (no package, no version)")
        elif not self.package or self.path:
            raise ValueError(f"server '{self.id}': runtime {self.runtime} takes 'package' (no path)")
        return self

    @property
    def mount(self) -> str:
        return (self.data.mount if self.data and self.data.mount else None) or f"/data/{self.id}"

    @property
    def has_volume(self) -> bool:
        return self.data is not None or self.plant_canaries


class Client(Strict):
    id: str
    harness: Literal["none", "agent", "mcphunt", "langgraph"] = "agent"  # agent = the lab's tool-calling agent
    servers: list[str]
    replicas: int = Field(1, ge=1, le=64)

    _id = field_validator("id")(_check_id)


class Gateway(Strict):
    """A container between clients and servers. Every MCP message passes through it and is logged.

    guard none = no gateway container (clients talk to servers directly).
    """

    guard: Literal["none", "passthrough", "taint", "mcphunt", "fides"] = "none"
    policy: str | None = None  # guard policy YAML, relative to the testbed file
    log_all: bool = True


class Service(Strict):
    """A backend container that is not an MCP server (database, mail server, webhook sink)."""

    id: str
    image: str | None = None  # any Docker image, e.g. axllent/mailpit
    builtin: Literal["webhook-sink"] | None = None  # a service shipped with the lab
    env: dict[str, str] = {}
    domain: str
    label: Literal["private", "public", "mixed"] = "private"

    _id = field_validator("id")(_check_id)

    @model_validator(mode="after")
    def _one_source(self) -> "Service":
        if bool(self.image) == bool(self.builtin):
            raise ValueError(f"service '{self.id}': give exactly one of 'image' or 'builtin'")
        return self


class Canaries(Strict):
    generator: Literal["format_authentic"] = "format_authentic"
    per_server: int = Field(5, ge=0, le=1000)
    kinds: list[Literal["stripe", "aws", "github", "iban_sa", "saudi_id", "email"]] = [
        "stripe", "aws", "github", "iban_sa", "saudi_id", "email",
    ]
    languages: list[Literal["en", "ar"]] = ["en"]  # ar adds Arabic personal records per server
    file: str = "credentials.env"  # file written into each server's data folder


class Attack(Strict):
    """An attacker server added to the testbed (code in servers/poisoned-tools, servers/web-mock).

    poisoned_tool   a tool whose description carries hidden instructions
    rug_pull        benign descriptions first, the poisoned ones after `after_calls` calls
    prompt_injection  web pages (fetch-like tool) carrying instructions for the agent
    log_poisoning   web pages carrying text aimed at a guard that learns from its logs
    """

    type: Literal["poisoned_tool", "rug_pull", "prompt_injection", "log_poisoning"]
    id: str | None = None  # server id; default derived from the type
    payload: str  # the injected text
    after_calls: int = Field(3, ge=0)  # rug_pull only
    domain: str | None = None  # default: the first domain with internet, else the first domain

    _id = field_validator("id")(lambda v: _check_id(v) if v is not None else v)


class Transform(Strict):
    """A rewriting tool offered to the agents (code in servers/transformer); uses the testbed LLM."""

    type: Literal["paraphrase", "translate"]
    id: str | None = None
    to: Literal["ar", "en"] = "ar"  # translate only
    domain: str | None = None

    _id = field_validator("id")(lambda v: _check_id(v) if v is not None else v)


class Logging(Strict):
    messages: bool = True
    sinks: bool = True
    format: Literal["jsonl"] = "jsonl"


class Testbed(Strict):
    testbed: str
    version: int = SCHEMA_VERSION
    seed: int = Field(0, ge=0)
    defaults: Defaults = Defaults()
    domains: list[Domain] = []
    llm: LLM = LLM()
    servers: list[Server]
    clients: list[Client]
    gateway: Gateway = Gateway()
    services: list[Service] = []
    canaries: Canaries = Canaries()
    attacks: list[Attack] = []
    transforms: list[Transform] = []
    logging: Logging = Logging()
    reset: Literal["per_task", "per_round", "never"] = "per_task"

    _name = field_validator("testbed")(_check_id)

    @field_validator("version")
    @classmethod
    def _version(cls, v: int) -> int:
        if v != SCHEMA_VERSION:
            raise ValueError(f"schema version {v} not supported (this mcp-cybernet-lab reads version {SCHEMA_VERSION})")
        return v

    @model_validator(mode="after")
    def _resolve_and_cross_check(self) -> "Testbed":
        self._expand_attacks_and_transforms()
        # Apply defaults, so the rest of the code never looks at `defaults`.
        for s in self.servers:
            if s.transport is None:
                s.transport = self.defaults.transport
            if s.network is None:
                s.network = self.defaults.network

        ids = ([d.id for d in self.domains] + [s.id for s in self.servers] + [c.id for c in self.clients]
               + [v.id for v in self.services] + (["gateway"] if self.gateway.guard != "none" else []))
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate ids: {dupes}")

        domain_ids = {d.id for d in self.domains}
        server_ids = {s.id for s in self.servers}
        for s in self.servers:
            if s.domain is not None and s.domain not in domain_ids:
                raise ValueError(f"server '{s.id}': unknown domain '{s.domain}'")
            if s.transport == "http" and s.domain is None:
                raise ValueError(f"server '{s.id}': an http server needs a domain (its network)")
            if s.transport == "stdio" and not s.network.is_default:
                raise ValueError(f"server '{s.id}': network conditions need transport http (stdio has no network)")
        for c in self.clients:
            unknown = [x for x in c.servers if x not in server_ids]
            if unknown:
                raise ValueError(f"client '{c.id}': unknown servers {unknown}")
        for v in self.services:
            if v.domain not in domain_ids:
                raise ValueError(f"service '{v.id}': unknown domain '{v.domain}'")
        if self.gateway.guard != "none":
            stdio = [s.id for s in self.servers if s.transport == "stdio"]
            if stdio:
                raise ValueError(f"a gateway needs every server on transport http; stdio: {stdio}")
        if self.llm.provider == "vllm" and not self.llm.base_url:
            raise ValueError("llm: provider vllm needs base_url")
        return self

    def _expand_attacks_and_transforms(self) -> None:
        """Turn `attacks` and `transforms` into ordinary servers, connected to every client."""
        if not (self.attacks or self.transforms):
            return
        default_domain = next((d.id for d in self.domains if d.internet), None) or \
            (self.domains[0].id if self.domains else None)
        added = []
        for i, a in enumerate(self.attacks):
            folder = "web-mock" if a.type in ("prompt_injection", "log_poisoning") else "poisoned-tools"
            sid = a.id or f"{a.type.replace('_', '-')}-{i}"
            env = {"MCL_PAYLOAD": a.payload, "MCL_ATTACK": a.type, "MCL_AFTER_CALLS": str(a.after_calls)}
            added.append(Server(id=sid, runtime="local", path=str(SERVERS_DIR / folder), env=env,
                                domain=a.domain or default_domain, label="public", plant_canaries=False))
        for i, t in enumerate(self.transforms):
            sid = t.id or f"{t.type}-{i}"
            env = {"MCL_TRANSFORM": t.type, "MCL_TO": t.to}
            added.append(Server(id=sid, runtime="local", path=str(SERVERS_DIR / "transformer"), env=env,
                                domain=t.domain or default_domain, label="mixed", plant_canaries=False))
        self.servers = self.servers + added
        for c in self.clients:
            c.servers = c.servers + [s.id for s in added if s.id not in c.servers]
        self.attacks, self.transforms = [], []  # expanded; keeps the model idempotent

    def server(self, sid: str) -> Server:
        return next(s for s in self.servers if s.id == sid)
