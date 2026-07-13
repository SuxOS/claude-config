---
name: man
description: The "show me my skills" reference verb — the native `.` (inform) verb. Bare "/man" (= /man.) just lists the custom verbs with one-liners — plain and fast. "/man <thing>" filters to a slice (verbs/mcp/skills/repo); more dots scale completeness — "/man....." renders the full toolbelt (built-ins + connected MCP world + repo) as a visual. Distinct from wtf (which reads a situation) — man maps *capabilities*. Use for "/man", "show me the tools/skills", "what can I do here", "what's available".
---

**`man` means: show what's on the workbench.** Not the state of the work (`wtf?`) — the *tools* available to do it. Output is a scannable interface, freshly gathered from ground truth, not recited from memory.

## Gather (fast, parallel)

- **Custom verbs** — `ls ~/.claude/skills/` + each `SKILL.md` frontmatter `description`. Group by mark: `?` inquire · `!` act · dispatch subset (`cron`/`queue`/`fork`). Show the one-line each.
- **Built-in skills** — from the session's available-skills list; surface the ones relevant to the current repo/task (e.g. `code-review`, `verify`, `run`, `loop`, `schedule`, `deep-research`, `claude-api`, `dataviz`, plus any plugin skills like `cloudflare:*`, `sux:*`).
- **Connected world** — MCP servers wired this session (sux, cloudflare, grafana, browser, computer-use, macOS…) and what each is for. Note any still connecting.
- **This repo** — name, branch, and one line on what it is (from git + a glance at the tree).

## Scope — `.` count scales completeness; bare is small on purpose

`man` is the native `.` (inform) verb — it shows, never investigates or changes. More dots = more complete.

- **`/man`** = **`/man.`** — **just list my skills.** The custom verbs, each with its one-line, grouped by mark. A plain scannable list (markdown), not a production. The common case; keep it light and fast.
- **`/man <thing>`** — one slice: `/man verbs`, `/man mcp`, `/man cloudflare`, `/man skills`, `/man repo`. Filter, don't dump.
- **`/man.....` (or `/man all`)** — the full toolbelt as a **visual** (`show_widget`): the `.`/`?`/`!` grammar up top, verb chips with one-liners (clickable → `sendPrompt` an explanation), built-in skills, connected MCP world, repo footer. Dense-but-clean is fine here — a man page *is* a dense reference. Fall back to markdown if no visual surface.

## Read-only

`man` only *shows*. Acting on what it reveals is the other verbs' job — it's the index they hang off.
