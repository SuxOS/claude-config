#!/usr/bin/env python3
"""
Discover MCP servers and HTTP endpoints across locally-cloned repos.

Config-first, grep-fallback: trusts structured config (wrangler, package.json,
OpenAPI specs, Dockerfiles) when present since it's precise; only greps for
framework signatures in repos where no config signal was found, since grep is
noisier (string matches in comments/tests/dead code included).

Usage: discover_endpoints.py [repo_dir ...]   (defaults to immediate subdirs of cwd)

Outputs JSON: {"mcp_servers": [...], "http_endpoints": [...]}
Each entry: {repo, kind, source ("config"|"grep"), evidence, transport?, path?}
"""
import json
import re
import subprocess
import sys
from pathlib import Path

MCP_CONFIG_HINTS = [
    ("package.json", r'"@modelcontextprotocol/sdk"'),
    ("package.json", r'"bin"\s*:\s*\{[^}]*mcp'),
    ("pyproject.toml", r'mcp'),
]
MCP_GREP_PATTERNS = [
    r"new McpServer\(",
    r"@modelcontextprotocol/sdk",
    r"FastMCP\(",
    r"@mcp\.tool\(",
    r"from mcp\.server",
    r"mcp\.server\.fastmcp",
]

HTTP_CONFIG_FILES = [
    "wrangler.toml", "wrangler.jsonc", "wrangler.json",
    "openapi.yaml", "openapi.yml", "openapi.json",
    "swagger.yaml", "swagger.yml", "swagger.json",
    "Dockerfile",
]
HTTP_GREP_PATTERNS = [
    r"app\.(get|post|put|delete|patch)\(",
    r"router\.(get|post|put|delete|patch)\(",
    r"@(app|router)\.(get|post|put|delete|patch)\(",
    r"Hono\(\)",
    r"fastify\(\)",
]


def run(cmd, cwd=None):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
        return out.stdout
    except Exception:
        return ""


EXCLUDE_DIRS = ("node_modules", ".git", "dist", "build", "venv", ".venv", "target", ".next", "vendor")


def grep_repo(path, patterns):
    combined = "|".join(patterns)
    prune = []
    for d in EXCLUDE_DIRS:
        prune += [f"--exclude-dir={d}"]
    out = run(["grep", "-rlE"] + prune + [combined, "."], cwd=path)
    hits = []
    for line in out.splitlines():
        line = line.strip().lstrip("./")
        if line:
            hits.append(line)
    return hits


def scan_repo(path: Path):
    name = path.name
    mcp_found = []
    http_found = []

    for fname, pattern in MCP_CONFIG_HINTS:
        f = path / fname
        if f.exists():
            try:
                text = f.read_text(errors="ignore")
                if re.search(pattern, text):
                    mcp_found.append({"repo": name, "kind": "mcp", "source": "config", "evidence": fname})
            except Exception:
                pass

    for fname in HTTP_CONFIG_FILES:
        f = path / fname
        if f.exists():
            http_found.append({"repo": name, "kind": "http", "source": "config", "evidence": fname})

    if not mcp_found:
        for hit in grep_repo(path, MCP_GREP_PATTERNS):
            mcp_found.append({"repo": name, "kind": "mcp", "source": "grep", "evidence": hit})

    if not http_found:
        for hit in grep_repo(path, HTTP_GREP_PATTERNS):
            http_found.append({"repo": name, "kind": "http", "source": "grep", "evidence": hit})

    return mcp_found, http_found


def main():
    args = sys.argv[1:]
    if args:
        dirs = [Path(a) for a in args]
    else:
        cwd = Path.cwd()
        dirs = [c for c in sorted(cwd.iterdir()) if c.is_dir() and (c / ".git").exists()]
        if not dirs and (Path.cwd() / ".git").exists():
            dirs = [Path.cwd()]

    all_mcp, all_http = [], []
    for d in dirs:
        mcp, http = scan_repo(d)
        all_mcp += mcp
        all_http += http

    print(json.dumps({"mcp_servers": all_mcp, "http_endpoints": all_http}, indent=2))


if __name__ == "__main__":
    main()
