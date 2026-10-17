"""Read a testbed YAML file into a validated `Testbed`."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import Testbed


class TestbedError(Exception):
    """A testbed file that cannot be used, with a message meant for the person who wrote it."""

    __test__ = False  # the name starts with "Test"; tell pytest it is not a test class


@dataclass
class Loaded:
    testbed: Testbed
    path: Path  # the YAML file
    sha256: str  # hash of the file bytes, recorded in the manifest
    warnings: list[str]


def load_testbed(path: str | Path) -> Loaded:
    path = Path(path).resolve()
    if not path.is_file():
        raise TestbedError(f"{path}: file not found")
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise TestbedError(f"{path}: not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise TestbedError(f"{path}: the top level must be a mapping")
    try:
        tb = Testbed.model_validate(data)
    except ValidationError as e:
        lines = [f"{path}: {e.error_count()} problem(s)"]
        for err in e.errors():
            where = ".".join(str(p) for p in err["loc"]) or "(top level)"
            lines.append(f"  - {where}: {err['msg']}")
        raise TestbedError("\n".join(lines)) from None

    warnings = []
    for s in tb.servers:
        if s.runtime == "local":
            src = path.parent / s.path
            if not (src / "pyproject.toml").is_file():
                raise TestbedError(f"server '{s.id}': '{s.path}' must be a folder with a pyproject.toml")
        elif s.version is None:
            warnings.append(f"server '{s.id}': no version pinned; the build is not reproducible")
        if s.extra_canaries and not (path.parent / s.extra_canaries).is_file():
            raise TestbedError(f"server '{s.id}': extra_canaries '{s.extra_canaries}' not found")
        if s.data and s.data.source and not (path.parent / s.data.source).is_dir():
            raise TestbedError(f"server '{s.id}': data folder '{s.data.source}' not found next to {path.name}")
    if tb.llm.api_key_env and not os.environ.get(tb.llm.api_key_env):
        warnings.append(f"llm: environment variable {tb.llm.api_key_env} is not set")
    return Loaded(tb, path, hashlib.sha256(raw).hexdigest(), warnings)


def check_buildable(tb: Testbed) -> None:
    """Refuse values that the schema names but this version does not implement."""
    todo = []
    for d in tb.domains:
        if d.auth == "oauth":
            todo.append(f"domain '{d.id}': auth 'oauth' (use 'token'; OAuth 2.1 is not implemented)")
    if tb.gateway.guard in ("mcphunt", "fides"):
        todo.append(f"gateway.guard '{tb.gateway.guard}' (external guard; integrate its code as a guard plug-in)")
    for c in tb.clients:
        if c.harness in ("mcphunt", "langgraph"):
            todo.append(f"client '{c.id}': harness '{c.harness}' (only 'agent' and 'none' are built in)")
    if todo:
        raise TestbedError("not implemented in this version:\n" + "\n".join(f"  - {t}" for t in todo))
