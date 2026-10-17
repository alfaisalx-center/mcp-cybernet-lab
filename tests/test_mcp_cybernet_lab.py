"""Unit tests: schema, canaries and the generated compose file. No Docker needed."""

from pathlib import Path

import pytest
import yaml

from mcp_cybernet_lab.compose import build
from mcp_cybernet_lab.loader import TestbedError, check_buildable, load_testbed
from mcp_cybernet_lab.seeding import make_canaries

ROOT = Path(__file__).resolve().parent.parent
TESTBEDS = sorted((ROOT / "testbeds").glob("*.yaml"))

TOY = {
    "testbed": "t",
    "domains": [{"id": "corp"}, {"id": "public", "internet": True}],
    "servers": [
        {"id": "a", "package": "pkg-a", "runtime": "python", "version": "1", "domain": "corp", "transport": "http"},
        {"id": "b", "package": "pkg-b", "runtime": "node", "version": "1", "domain": "public",
         "transport": "http", "network": {"delay_ms": 50, "loss": 0.02}},
        {"id": "c", "package": "pkg-c", "runtime": "python", "version": "1"},
    ],
    "clients": [{"id": "agent", "servers": ["a", "b", "c"]}],
}


def write(tmp_path, data, name="tb.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data))
    return p


@pytest.mark.parametrize("path", TESTBEDS, ids=lambda p: p.stem)
def test_shipped_testbeds_validate_and_build(path, tmp_path):
    loaded = load_testbed(path)
    check_buildable(loaded.testbed)
    out = build(loaded, tmp_path / loaded.testbed.testbed)
    assert (out / "docker-compose.yml").exists()


def test_local_and_network_files_differ_only_in_topology():
    for name in ("toy", "mcphunt"):
        net = load_testbed(ROOT / f"testbeds/{name}-network.yaml").testbed
        loc = load_testbed(ROOT / f"testbeds/{name}-local.yaml").testbed
        assert [s.package for s in net.servers] == [s.package for s in loc.servers]
        assert [s.version for s in net.servers] == [s.version for s in loc.servers]
        assert {s.transport for s in net.servers} == {"http"}
        assert {s.transport for s in loc.servers} == {"stdio"}
        assert make_canaries(net) == make_canaries(loc)  # same secrets in both


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(colour="blue"), "Extra inputs"),
    (lambda d: d["servers"][0].update(id="Bad_Id"), "must match"),
    (lambda d: d["servers"][0].update(domain="nowhere"), "unknown domain"),
    (lambda d: d["clients"][0].update(servers=["zzz"]), "unknown servers"),
    (lambda d: d["servers"].append(dict(d["servers"][0])), "duplicate ids"),
    (lambda d: d["servers"][2].update(network={"delay_ms": 10}), "need transport http"),
    (lambda d: d["servers"][0].pop("domain"), "needs a domain"),
    (lambda d: d.update(version=9), "not supported"),
])
def test_invalid_files_give_clear_errors(tmp_path, change, message):
    data = yaml.safe_load(yaml.safe_dump(TOY))
    change(data)
    with pytest.raises(TestbedError, match=message):
        load_testbed(write(tmp_path, data))


def test_defaults_are_applied(tmp_path):
    data = yaml.safe_load(yaml.safe_dump(TOY))
    data["defaults"] = {"transport": "http", "network": {"delay_ms": 7}}
    data["servers"][2]["domain"] = "corp"
    tb = load_testbed(write(tmp_path, data)).testbed
    c = tb.server("c")
    assert c.transport == "http" and c.network.delay_ms == 7
    assert tb.server("b").network.delay_ms == 50  # explicit value wins


def test_canaries_depend_only_on_seed_and_server(tmp_path):
    data = yaml.safe_load(yaml.safe_dump(TOY))
    first = make_canaries(load_testbed(write(tmp_path, data)).testbed)
    assert first == make_canaries(load_testbed(write(tmp_path, data, "again.yaml")).testbed)
    data["servers"].append({"id": "d", "package": "p", "runtime": "python", "version": "1"})
    grown = make_canaries(load_testbed(write(tmp_path, data, "grown.yaml")).testbed)
    assert [r for r in grown if r["server"] != "d"] == first  # adding a server changes nothing else
    data["seed"] = 1
    other = make_canaries(load_testbed(write(tmp_path, data, "seed1.yaml")).testbed)
    assert {r["value"] for r in other}.isdisjoint({r["value"] for r in first})


def test_compose_topology(tmp_path):
    out = build(load_testbed(write(tmp_path, TOY)), tmp_path / "out")
    c = yaml.safe_load((out / "docker-compose.yml").read_text())
    s = c["services"]
    assert set(s) == {"a", "b", "agent"}  # stdio server c runs inside the client
    assert s["a"]["networks"] == ["net-corp"] and s["b"]["networks"] == ["net-public"]
    assert sorted(s["agent"]["networks"]) == ["net-corp", "net-public"]
    assert c["networks"]["net-corp"]["internal"] is True
    assert c["networks"]["net-public"]["internal"] is False
    assert s["b"]["cap_add"] == ["NET_ADMIN"] and "cap_add" not in s["a"]
    assert s["b"]["environment"]["MCL_LOSS_PCT"] == "2"
    assert "./data/c:/data/c" in s["agent"]["volumes"]
    assert "install_server.py python pkg-c 1 c" in (out / "dockerfiles/agent.Dockerfile").read_text()
    assert (out / "data/a/credentials.env").read_text().count("=") == 5


def test_unimplemented_features_are_refused(tmp_path):
    data = yaml.safe_load(yaml.safe_dump(TOY))
    data["servers"][2]["transport"] = "http"
    data["servers"][2]["domain"] = "corp"
    data["gateway"] = {"guard": "fides"}
    data["domains"][0]["auth"] = "oauth"
    loaded = load_testbed(write(tmp_path, data))
    with pytest.raises(TestbedError, match="fides") as e:
        build(loaded, tmp_path / "out")
    assert "oauth" in str(e.value)


def test_local_server_is_copied_and_installed(tmp_path):
    out = build(load_testbed(ROOT / "testbeds/sample-db-network.yaml"), tmp_path / "out")
    assert (out / "context/servers/hr/pyproject.toml").exists()
    assert not list((out / "context/servers/hr").rglob("__pycache__"))
    df = (out / "dockerfiles/hr.Dockerfile").read_text()
    assert "COPY servers/hr /opt/mcp-src/hr" in df and "install_server.py local /opt/mcp-src/hr" in df
    import json
    hr = next(s for s in json.loads((out / "manifest.json").read_text())["servers"] if s["id"] == "hr")
    assert len(hr["source_sha256"]) == 64


@pytest.mark.parametrize("server, message", [
    ({"id": "x", "runtime": "local"}, "takes 'path'"),
    ({"id": "x", "runtime": "local", "path": "p", "package": "q"}, "takes 'path'"),
    ({"id": "x", "runtime": "python"}, "takes 'package'"),
    ({"id": "x", "runtime": "python", "package": "q", "path": "p"}, "takes 'package'"),
])
def test_server_source_rules(tmp_path, server, message):
    data = {"testbed": "t", "servers": [server], "clients": [{"id": "a", "servers": ["x"]}]}
    with pytest.raises(TestbedError, match=message):
        load_testbed(write(tmp_path, data))


def test_local_server_needs_pyproject(tmp_path):
    (tmp_path / "srv").mkdir()
    data = {"testbed": "t", "servers": [{"id": "x", "runtime": "local", "path": "srv"}],
            "clients": [{"id": "a", "servers": ["x"]}]}
    with pytest.raises(TestbedError, match="pyproject"):
        load_testbed(write(tmp_path, data))
