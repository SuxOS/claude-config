"""Source adapters: discover raw records and (in execute mode) act on them.

Real adapters: ``local_git`` (local clones) and ``github`` (issues/PRs/CI via ``gh``).
Mock adapter: ``mock`` (JSON fixtures) — drives deterministic tests and stands in for any
unavailable integration. New sources are added by dropping in another Adapter subclass;
nothing else in the engine changes.
"""

from __future__ import annotations

from .base import Adapter, ActionResult, AdapterUnavailable
from .github import GitHubAdapter
from .local_git import LocalGitAdapter
from .mock import MockAdapter

__all__ = [
    "Adapter",
    "ActionResult",
    "AdapterUnavailable",
    "GitHubAdapter",
    "LocalGitAdapter",
    "MockAdapter",
    "build_adapter",
]

_REGISTRY = {
    "mock": MockAdapter,
    "local": LocalGitAdapter,
    "local_git": LocalGitAdapter,
    "github": GitHubAdapter,
}


def build_adapter(name: str, **kwargs) -> Adapter:
    """Construct an adapter by short name. Raises KeyError for an unknown adapter."""
    return _REGISTRY[name](**kwargs)
