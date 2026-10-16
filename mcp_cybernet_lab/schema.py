"""The testbed YAML schema.

One YAML file describes one MCP network: trust domains, servers, clients, the gateway,
canary secrets and logging. `load_testbed` in loader.py turns the file into a `Testbed`.

Fields that belong to later milestones (auth, guards, attacks, transforms) are accepted by the
schema so that testbed files can be written now, but `build` refuses them until implemented.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
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
    provider: Literal["openai", "deepseek", "anthropic", "vllm", "ollama", "none"] = "none"
    model: str | None = None
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    api_key_env: str | None = None  # name of a host environment variable; never the key itself


class ServerData(Strict):
    source: str | None = Field(None, alias="from")  # folder copied into the server, relative to the YAML
    mount: str | None = None  # where the folder appears inside the server; default /data/<server id>


class Server(Strict):
    id: str
    package: str  # npm or PyPI package name
    runtime: Literal["node", "python"]
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

    _id = field_validator("id")(_check_id)

    @property
    def mount(self) -> str:
        return (self.data.mount if self.data and self.data.mount else None) or f"/data/{self.id}"

    @property
    def has_volume(self) -> bool:
        return self.data is not None or self.plant_canaries


class Client(Strict):
    id: str
    harness: Literal["none", "mcphunt", "langgraph", "sdk"] = "none"
    servers: list[str]
    replicas: int = Field(1, ge=1, le=64)

    _id = field_validator("id")(_check_id)


class Gateway(Strict):
    guard: Literal["none", "passthrough", "mcphunt", "fides", "evolving"] = "none"
    policy: str | None = None
    log_all: bool = True


class Canaries(Strict):
    generator: Literal["format_authentic"] = "format_authentic"
    per_server: int = Field(5, ge=0, le=1000)
    kinds: list[Literal["stripe", "aws", "github", "iban_sa", "saudi_id", "email"]] = [
        "stripe", "aws", "github", "iban_sa", "saudi_id", "email",
    ]
    languages: list[Literal["en", "ar"]] = ["en"]
    file: str = "credentials.env"  # file written into each server's data folder


class Attack(Strict):
    type: Literal["poisoned_tool", "malicious_server", "prompt_injection", "log_poisoning"]
    target: str | None = None
    payload: str | None = None


class Transform(Strict):
    type: Literal["paraphrase", "translate"]
    to: Literal["ar", "en"] | None = None
    before: list[str] = []


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
        # Apply defaults, so the rest of the code never looks at `defaults`.
        for s in self.servers:
            if s.transport is None:
                s.transport = self.defaults.transport
            if s.network is None:
                s.network = self.defaults.network

        ids = [d.id for d in self.domains] + [s.id for s in self.servers] + [c.id for c in self.clients]
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
        return self

    def server(self, sid: str) -> Server:
        return next(s for s in self.servers if s.id == sid)
