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
        if s.data and s.data.source and not (path.parent / s.data.source).is_dir():
            raise TestbedError(f"server '{s.id}': data folder '{s.data.source}' not found next to {path.name}")
    if tb.llm.api_key_env and not os.environ.get(tb.llm.api_key_env):
        warnings.append(f"llm: environment variable {tb.llm.api_key_env} is not set")
    return Loaded(tb, path, hashlib.sha256(raw).hexdigest(), warnings)


def check_buildable(tb: Testbed) -> None:
    """Refuse features that the schema accepts but this version does not implement yet."""
    todo = []
    for d in tb.domains:
        if d.auth != "none":
            todo.append(f"domain '{d.id}': auth '{d.auth}' (milestone M3)")
    if tb.gateway.guard != "none":
        todo.append(f"gateway.guard '{tb.gateway.guard}' (milestone M4)")
    for c in tb.clients:
        if c.harness != "none":
            todo.append(f"client '{c.id}': harness '{c.harness}' (milestone M1)")
    if tb.attacks:
        todo.append("attacks (milestone M7)")
    if tb.transforms:
        todo.append("transforms (milestone M7)")
    if "ar" in tb.canaries.languages:
        todo.append("Arabic canaries (milestone M7)")
    if todo:
        raise TestbedError("not implemented yet in this version:\n" + "\n".join(f"  - {t}" for t in todo))
