"""Configuration: the declared fabric (sources) + an optional drain policy file.

Fabric truth is ``~/.claude/fabric.json`` (workspace root, orgs, repos, pipeline). Drain
policy is an optional ``drain.config.json`` (stdlib JSON — tomllib is 3.11+, unavailable on
the 3.9 target). Everything has a safe default so ``drain`` runs with zero config.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .adapters import build_adapter
from .adapters.base import Adapter

DEFAULT_FABRIC = "~/.claude/fabric.json"

DEFAULTS: Dict[str, Any] = {
    "org": "SuxOS",
    "adapters": ["local", "github"],  # mock is opt-in (tests / demos)
    "max_rounds": 3,
    "limit": None,
    "retries": 2,
    "backoff_base": 0.2,
    "breaker_threshold": 3,
    "concurrency": 4,
    "github_limit": 200,
    "mock_fixture": None,
}


def load_fabric(path: Optional[str] = None) -> Dict[str, Any]:
    p = os.path.expanduser(path or DEFAULT_FABRIC)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if path and os.path.exists(os.path.expanduser(path)):
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def _org_repos(fabric: Dict[str, Any], org: str) -> List[str]:
    return list(((fabric.get("orgs", {}).get(org, {}) or {}).get("repos", [])) or [])


def build_adapters(
    config: Dict[str, Any],
    fabric: Dict[str, Any],
    only: Optional[List[str]] = None,
) -> List[Adapter]:
    """Instantiate the enabled adapters, wiring in fabric-derived sources.

    ``only`` (from ``--source``) filters to a subset of adapter names.
    """
    org = config.get("org", "SuxOS")
    workspace_root = fabric.get("workspace_root")
    repos = _org_repos(fabric, org)
    slugs = [f"{org}/{r}" for r in repos]

    wanted = [a for a in config.get("adapters", []) if (only is None or a in only)]
    adapters: List[Adapter] = []
    for name in wanted:
        if name in ("local", "local_git"):
            adapters.append(build_adapter("local", workspace_root=workspace_root))
        elif name == "github":
            adapters.append(build_adapter("github", repos=slugs, limit=config.get("github_limit", 200)))
        elif name == "mock":
            adapters.append(build_adapter("mock", fixture_path=config.get("mock_fixture")))
    return adapters
