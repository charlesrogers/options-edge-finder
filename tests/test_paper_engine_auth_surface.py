"""The paper-engine surfaces must stay behind the auth gate.

`web/src/proxy.ts` is default-deny: anything not in PUBLIC_EXACT or matching a
PUBLIC_PREFIX requires a session. That is the correct posture, but "correct by
omission" is exactly the kind of guarantee that quietly stops being true — a
route added to the public list during debugging, a prefix broadened by one
character. Arm-level P&L at Dad's size is effectively a holdings disclosure, so
this asserts the omission rather than trusting it.

Pure text inspection: no Node, no network, runs in the normal pytest step.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY = os.path.join(ROOT, "web", "src", "proxy.ts")

PROTECTED = ["/paper-engine", "/api/paper-engine/health"]


@pytest.fixture(scope="module")
def proxy_source():
    assert os.path.exists(PROXY), "web/src/proxy.ts is the auth gate and must exist"
    with open(PROXY) as f:
        return f.read()


def _public_exact(source):
    block = re.search(r"PUBLIC_EXACT\s*=\s*new Set\(\[(.*?)\]\)", source, re.S)
    assert block, "could not find PUBLIC_EXACT — the gate's shape changed"
    return set(re.findall(r"'([^']+)'", block.group(1)))


def _public_prefixes(source):
    block = re.search(r"PUBLIC_PREFIXES\s*=\s*\[(.*?)\]", source, re.S)
    assert block, "could not find PUBLIC_PREFIXES — the gate's shape changed"
    return [m for m in re.findall(r"'([^']+)'", block.group(1))]


def test_the_parser_actually_finds_the_lists(proxy_source):
    """Vacuity guard. If the regexes matched nothing, every assertion below
    would pass against an empty set and prove nothing."""
    exact = _public_exact(proxy_source)
    prefixes = _public_prefixes(proxy_source)
    assert "/login" in exact, f"parsed PUBLIC_EXACT looks wrong: {exact}"
    assert any(p.startswith("/api/auth/") for p in prefixes), prefixes


@pytest.mark.parametrize("path", PROTECTED)
def test_paper_engine_surfaces_are_not_in_the_public_exact_list(proxy_source, path):
    assert path not in _public_exact(proxy_source), (
        f"{path} was added to PUBLIC_EXACT. Arm-level P&L at Dad's size is a "
        f"holdings disclosure — this page stays behind the gate.")


@pytest.mark.parametrize("path", PROTECTED)
def test_no_public_prefix_swallows_the_paper_engine_surfaces(proxy_source, path):
    matched = [p for p in _public_prefixes(proxy_source) if path.startswith(p)]
    assert not matched, (
        f"{path} is made public by prefix {matched}. A prefix broadened by one "
        f"character is how a default-deny gate stops being one.")


def test_the_page_and_route_exist_so_this_test_is_about_something(proxy_source):
    """Otherwise this file passes forever by guarding files that were deleted."""
    assert os.path.exists(os.path.join(ROOT, "web", "src", "app", "paper-engine", "page.tsx"))
    assert os.path.exists(
        os.path.join(ROOT, "web", "src", "app", "api", "paper-engine", "health", "route.ts"))


def test_the_health_route_does_not_alert(proxy_source):
    """It reports. One stale heartbeat behind an alerting health endpoint
    produced an alert per minute for hours (tasks/lessons.md 2026-08-19)."""
    route = os.path.join(ROOT, "web", "src", "app", "api", "paper-engine",
                         "health", "route.ts")
    with open(route) as f:
        source = f.read()
    for forbidden in ["DISCORD_WEBHOOK", "discord.com/api/webhooks",
                      "pushover", "PUSHOVER"]:
        assert forbidden not in source, (
            f"the health route references {forbidden}. Alerting lives in the "
            f"scheduled engine runs and nowhere else.")
