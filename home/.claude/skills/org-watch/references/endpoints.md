# Dimension: MCP servers & HTTP endpoints

Run `scripts/discover_endpoints.py` from the scope directory. Config-first, grep-fallback per repo — trusts `wrangler.*`/`package.json`/OpenAPI specs when present, only greps for framework signatures (`new McpServer(`, `app.get(`, `@mcp.tool(`) in repos with no config signal. Returns `{mcp_servers: [...], http_endpoints: [...]}`.

**The raw inventory is not the report** — it's an intermediate. Discovery finds *what exists*; only what's *wrong* with it gets reported. Filter hard:

- **A discovered MCP/endpoint with nothing wrong is not a finding.** Never list "found MCP server in repo X" — that's inventory. It only earns a line once it fails one of the checks below.
- **Actively-developed MCP servers get end-to-end tested, not just inventoried.** If a discovered server lives in a repo with commits in the last 7 days (the "actively developing" signal):
  - Actually start/connect to it (stdio: run the entry point, do an MCP handshake; http/sse: hit the endpoint) and list its tools. Live process/tool calls need judgment — agent step, not the script.
  - Handshake or tool-list fails → real finding. Report *what broke*, not just "couldn't connect."
  - Succeeds but the server isn't installed as a connector in the user's Claude Code config → say so and offer to set it up. This is the "useful, not noise" payoff of discovery — don't silently note and move on.
- **HTTP endpoints get a live health check** — `curl -sS -o /dev/null -w '%{http_code}' <url>` (script-level, deterministic) against any endpoint with a resolvable URL (wrangler routes, OpenAPI `servers:`, `*.workers.dev`/known deploy target). Report only non-2xx/timeouts.
- **Schema/contract drift** folds into the GitHub-dimension synthesis: two+ repos defining a same-named MCP tool or HTTP route with diverging schemas is a cross-repo finding on par with a repeated bug — two implementations of "the same thing" have silently forked.
