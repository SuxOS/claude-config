#!/usr/bin/env python3
"""PreToolUse hook (matcher: `WebFetch|WebSearch`) — the egress rail the native web tools lack.

`home/.claude/settings.json` allow-lists `WebFetch`/`WebSearch` (permissions.allow) and
`hooks.PreToolUse` has exactly three matchers — `Agent|Task`, `Bash`, `mcp__.*__.*` — none of
which cover either tool (#360). Every other network-egress-shaped surface in this repo has at
least a rail: Bash-invoked network commands get block-egress.py, MCP tool calls get
block-destructive-mcp.py. docs/security-model.md documents Bash-argv and MCP as separate
surfaces each with their own enforcement, but never mentions WebFetch/WebSearch — and
block-egress.py's own block message actively steers bypassed Bash traffic at these two tools
("If you need to fetch a URL use WebFetch/WebSearch"), so the one channel it points at had zero
rail of its own.

Unlike Bash argv, a WebFetch/WebSearch call is structured `tool_input` JSON with a `url` (WebFetch)
or `query` (WebSearch) field — no wrapper/quoting/substitution bypass space to fight, so this rail
is a straight field read, not an argv canonicalizer. `query` is free-text sent to a search provider,
not a fetch target, so there is no URL-shaped value to validate there today; the matcher still
covers `WebSearch` (as the issue's suggested direction names it) so a future `url`-shaped field on
that tool inherits the same check with no wiring change, and `check()` is a no-op for `tool_input`
with no `url` key. For `WebFetch`, `tool_input.url` is validated against exactly the two shapes the
issue calls out as mechanically checkable without a network call:

  1. a non-http(s) scheme (`file://`, `ftp://`, `gopher://`, `data:`, ...) — WebFetch's whole
     contract is fetching a web URL; anything else is already off-contract.
  2. a LITERAL loopback/link-local/private/reserved IP target (127.0.0.1, 169.254.169.254 — the
     cloud-metadata address on AWS/GCP/Azure alike, since it's link-local — 10/8, 172.16/12,
     192.168/16, ::1, fc00::/7, fe80::/10, ...), or a known metadata hostname
     (`metadata.google.internal`/`metadata.goog`).

Deliberately scoped to LITERAL targets, not resolved ones: this hook makes no DNS query (no
network access from a PreToolUse hook, and a resolution can change between check-time and
fetch-time anyway), so a hostname that merely RESOLVES to a private/metadata address today is
invisible here — the same "speed bump, not a seal" honesty block-egress.py's own docstring gives
docs/security-model.md's durable lesson. Mirrors block-destructive-mcp.py's Tier-A shape: no repo
state can prove a fetch/search target safe, and there is no human to confirm in an autonomous
session, so a match blocks unconditionally rather than being gated on some "would this actually
hurt" heuristic (there's no repo state to check that against here).

Fail-open on any error, and on anything this can't confidently parse (a malformed URL, a missing
`url` field, a non-dict `tool_input`) — a hook bug, or a shape this doesn't recognize, must never
wedge the session (repo convention). Exit 2 = block; exit 0 = allow.
"""
import ipaddress
import sys
from urllib.parse import urlparse

from _hookutil import hook_tool_input, load_hook_input

ALLOWED_SCHEMES = {"http", "https"}

# Cloud-metadata hostnames that aren't IP literals, so ipaddress.ip_address() can't catch them.
# 169.254.169.254 itself (AWS/GCP/Azure/DigitalOcean's shared metadata IP) is already covered by
# the link-local check below (169.254.0.0/16) — these are the DNS-name form some SDKs use instead.
METADATA_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}


def _disallowed_host_reason(host):
    """Return a human reason `host` is a disallowed literal target, or None (including for an
    ordinary DNS name — this hook does no resolution, see module docstring)."""
    if not host:
        return None
    host = host.strip().lower()
    if host in METADATA_HOSTNAMES:
        return f"a known cloud-metadata hostname (`{host}`)"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None  # not an IP literal — an ordinary DNS name, nothing more to check offline
    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_unspecified:
        return f"a loopback/link-local/private/reserved IP literal (`{host}`)"
    return None


def _offending_url(url):
    """Return a human reason `url` is a disallowed WebFetch target, or None."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if not scheme:
        return None  # no scheme at all — not a URL shape this hook can confidently parse
    if scheme not in ALLOWED_SCHEMES:
        return f"a non-http(s) scheme (`{scheme}:`)"
    return _disallowed_host_reason(parsed.hostname)


def check(tool_name, tool_input):
    """Dispatcher-facing predicate: (tool_name, tool_input) -> full block message, or None."""
    if not isinstance(tool_input, dict):
        return None
    reason = _offending_url(tool_input.get("url"))
    if not reason:
        return None
    return (
        f"Web egress guard (PreToolUse): `{tool_name}` was blocked because its target URL is "
        f"{reason}. No repo state can prove a fetch target safe, and there is no human to confirm "
        "in an autonomous session (mirrors block-destructive-mcp.py's unconditional Tier-A block). "
        "If this is a legitimate internal target, ask the user to fetch it manually outside the "
        "agent loop."
    )


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    tool_name = data.get("tool_name")
    if tool_name not in ("WebFetch", "WebSearch"):
        sys.exit(0)

    try:
        message = check(tool_name, hook_tool_input(data))
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
