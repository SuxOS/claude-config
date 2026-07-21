# Security model of this config

`home/.claude/settings.json` runs under `"defaultMode": "bypassPermissions"`. In that mode
Claude Code does **not** prompt before tool calls, so the `permissions.deny` list is the
*only* enforced control — `allow` is advisory and everything not denied runs silently.

## What the deny list is — and isn't

<!-- doc-fact: settings-deny "Bash(curl *)" -->
<!-- doc-fact: settings-deny "Bash(wget *)" -->
<!-- doc-fact: settings-deny "Bash(ssh *)" -->
<!-- doc-fact: settings-deny "Bash(scp *)" -->
<!-- doc-fact: settings-deny "Bash(tar *)" -->
<!-- doc-fact: settings-deny "Bash(gh api -X *)" -->
<!-- doc-fact: settings-deny "Bash(gh api --method *)" -->
The deny list (`Bash(curl *)`, `Bash(wget *)`, `Bash(ssh *)`, `Bash(scp *)`, `Bash(tar *)`,
`Bash(gh api -X *)`, `Bash(gh api --method *)`) is **defense-in-depth against casual or
accidental misuse — a speed bump, not a boundary.** It is deliberately *not* a real
network-egress or exfiltration boundary, and must not be mistaken for one. Two structural
reasons it cannot be, as long as the current allow-list stands:

1. **Allowed interpreters subsume every denied capability.** `Bash(python3 *)`,
   `Bash(node *)`, `Bash(npm *)`, and `npx` are general-purpose runtimes: they open
   arbitrary sockets and extract archives directly, with no denied binary involved.
   `python3 -c 'import urllib.request; ...'` and `node -e 'fetch(...)'` reproduce exactly
   the HTTP fetch / data exfil that denying `curl`/`wget` is meant to stop; an
   npx-installed tool reproduces anything else. Denying `tar` (already done) is undone the
   same way. So per-binary network/archive denies are porous by construction. (#63, #69)

2. **`gh api` is a generic escape hatch, and pattern denies are order-sensitive.**
   `gh api -X DELETE /repos/O/R` ≈ `gh repo delete`; `gh api -X PUT
   /repos/O/R/actions/secrets/X` ≈ `gh secret set`. The two `gh api` write-method denies
   above catch the common `-X …` / `--method …`-first forms, but a **prefix** deny cannot
   see a flag that comes after the URL: `gh api /repos/O/R -X DELETE` slips straight
   through. Treat them as a speed bump for the obvious form, not a seal. Read-only
   `gh api repos/...` GETs (used by the skills) are unaffected. (#68)

## The durable lesson

A real egress/exfil boundary **cannot be built from per-binary deny rules while
general-purpose interpreters (`python3` / `node` / `npx`) stay on the allow-list.** Adding
more denied binaries only lengthens the list while leaving the interpreters — and
`gh api` — as open reproductions of the same capability, which is worse than a short list
because it reads as protection that isn't there. Closing the gap for real needs a
*different mechanism*: OS-level network sandboxing (egress firewall / netns), a `PreToolUse`
hook that inspects command intent before it runs (see `home/.claude/hooks/`), or narrowing
the interpreter and `gh` grants to specific scripts/subcommands. Until then, keep the deny
list honest about being a speed bump, and prefer documenting a gap over adding a per-binary
deny that gives false assurance. This applies equally to the original `curl`/`ssh`/`scp`
egress denies, not just the later additions — none of them is a network boundary. (#71)

## The first enforced step: `block-egress.py` (#77)

A `PreToolUse` hook — `home/.claude/hooks/block-egress.py`, registered as a rail behind the single
`pretooluse-bash.py` dispatcher wired under `hooks.PreToolUse` with a `Bash` matcher (#163) — now
takes the first concrete step of the "different mechanism" above. It parses
each Bash command's argv **before it runs** and blocks the obvious egress forms the deny list
structurally cannot: interpreter/shell inline-code one-liners that open a socket
(`python3 -c 'import urllib…'`, `node -e 'fetch(…)'`, `bash -c '…curl…'`); a bare network primitive
as the command word (`… && curl …`, `sudo wget …`) or a `/dev/tcp` redirect, which the *anchored*
`Bash(curl *)` deny catches only as the first word; and `gh api` **writes** in any argv position
(`gh api /repos/O/R -X DELETE`, which the prefix deny misses because the flag follows the URL). To
keep this from becoming a brittle branch per tokenization quirk (the per-form bypass drip of
#105/#115/#119/#120/#121/#126), argv is **canonicalized once** before scanning — every leading
prefix (env-assign/`sudo`/wrappers) stripped to the real command word, then inline-code flags read
through a single walk that decomposes bundled/glued/separate forms uniformly (#129). This raises
the casual/accidental bar — but it is still a **speed bump, not a seal**, and the durable lesson
stands: base64/variable-obfuscated payloads, sockets built without a named primitive, and
interpreters fed code from a file or stdin all pass it, so a *complete* egress boundary still needs
OS-level network sandboxing. The hook makes the gh-api gap enforceable at the
argv layer, which is what let the deny be narrowed back (#76) from a blanket `Bash(gh api *)` to
just the two write-method forms above — restoring the read-only `gh api repos/…` GETs the skills
use, while the hook still catches writes that slip past the URL-then-flag ordering gap.

Tracked in the security-hardening issue stream
(#33 / #36 / #37 / #43 / #44 / #45 / #46 / #53 / #58 / #63 / #68 / #69 / #71 / #77).

## MCP tool calls are a separate surface — and were entirely unguarded until #260

Everything above is about Bash argv. `home/.claude/settings.json` also enables a dozen+ MCP-bundling
plugins (`enabledPlugins`) — the GitHub plugin's server alone exposes tools like
`merge_pull_request`, `push_files`, `delete_file`, none of which appeared anywhere in
`permissions.deny`, and no `PreToolUse` hook looked at an MCP `tool_use` call at all. An MCP call is
a structurally different action from a Bash command with the same intent (there's no argv to parse,
no wrapper/quoting bypass space — just a `tool_name` and a JSON `tool_input`), so it needed its own
rail rather than reuse of the Bash-argv one.

`block-destructive-mcp.py` (#260) closes the general-purpose slice of this: a `PreToolUse` hook
matched on `mcp__.*__.*` that pattern-matches Tier-A verbs (`merge`, `delete`, `push`, `force`,
`publish`, `deploy`) in the tool name's final segment — including at camelCase boundaries
(`mergePullRequest`, #355), not just `_`/`-` ones — and blocks unconditionally on a hit — same
"cardinal rails as code" approach (#163) as the Bash rails, generalized so it needs no
hand-maintained per-plugin enumeration. This is deliberately narrower than the Cloudflare plugin's
explicit per-tool denies (settings.json:81-89, `create`/`update`/`edit` included): those remain the
belt for non-Tier-A mutations on the one plugin someone audited live. The GitHub plugin now has the
same tactical, exact-name belt too (#348, settings.json, settings.README.md's "Verified GitHub
mapping") — tool/server names confirmed from the plugin's own `.mcp.json` and the upstream
`github/github-mcp-server` README rather than a live `/mcp` session, the same primary-source tier
the Cloudflare mapping was already confirmed at.

## The native web tools are a third surface — and were entirely unguarded until #360

`WebFetch`/`WebSearch` are allow-listed in `permissions.allow` and, until #360, matched no
`PreToolUse` hook and no `permissions.deny` rule at all — the one gap that mattered most, since
`block-egress.py`'s own block message actively steers a blocked Bash egress attempt AT these two
tools ("If you need to fetch a URL use WebFetch/WebSearch") while nothing watched the door it was
pointing at. An agent-controlled `WebFetch` URL can already target cloud-metadata endpoints
(`169.254.169.254`) or loopback/private infrastructure with zero enforcement.

`block-web-egress.py` (#360) closes this: a `PreToolUse` hook matched on `WebFetch|WebSearch` that
reads `tool_input.url` (WebFetch's fetch target — `WebSearch`'s `query` is free text sent to a
search provider, not a fetch target, so there's nothing URL-shaped to check there today) and blocks
on exactly two literal-target shapes: a non-http(s) scheme (`file://`, `ftp://`, `data:`, ...), or a
LITERAL loopback/link-local/private/reserved IP target (covers the metadata IP, since it's
link-local) or known metadata hostname. No DNS resolution is performed — a hostname that merely
*resolves* to a private/metadata address is invisible to this check, the same "speed bump, not a
seal" honesty as `block-egress.py`. No repo state can prove a fetch target safe and there's no human
to confirm in an autonomous session, so a match blocks unconditionally, mirroring
`block-destructive-mcp.py`'s Tier-A shape.

## `Write` is a fourth surface — a blind full-file overwrite with no diff-aware guard until #364

Every "discard uncommitted work" guard above (`block-destructive-git.py`'s `_reset_hard_hit`/
`_discard_hit`, `audit-git-consequences.py`'s ref-diffing) is Bash-scoped. `permissions.allow`
grants `"Write"` unconditionally, and Write fully REPLACES a file's content with no diff-aware
merge — a Write call to a git-tracked file that has uncommitted staged-or-unstaged changes silently
discards them, the same Tier-A "discard without an explicit yes" case the git rails exist to catch,
reached through a tool surface those rails don't watch.

`block-write-overwrite.py` (#364) closes this: a `PreToolUse` hook matched on `Write` that runs
`git status --porcelain` scoped to `tool_input.file_path` in the file's own directory and blocks
when that file is git-tracked AND has uncommitted changes (any porcelain line other than the
untracked `??` marker) — the same "tracked change at risk" signal `block-destructive-git.py`'s
`_working_tree_dirty()` already uses, scoped to one path instead of the whole tree. `Edit` is
deliberately out of scope: it requires an exact `old_string` match against the file's current
content, so it can't blindly clobber a change it never saw the way Write can. Unconditional on a
hit, same Tier-A shape as `block-destructive-mcp.py`; fails open on any error, a relative
`file_path`, or a target outside a readable git repo.
