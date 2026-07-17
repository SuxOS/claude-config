# Security model of this config

`home/.claude/settings.json` runs under `"defaultMode": "bypassPermissions"`. In that mode
Claude Code does **not** prompt before tool calls, so the `permissions.deny` list is the
*only* enforced control — `allow` is advisory and everything not denied runs silently.

## What the deny list is — and isn't

The deny list (`Bash(curl *)`, `Bash(wget *)`, `Bash(ssh *)`, `Bash(scp *)`,
`Bash(gh api -X *)`, `Bash(gh api --method *)`) is **defense-in-depth against casual or
accidental misuse — a speed bump, not a boundary.** It is deliberately *not* a real
network-egress or exfiltration boundary, and must not be mistaken for one. Two structural
reasons it cannot be, as long as the current allow-list stands:

1. **Allowed interpreters subsume every denied capability.** `Bash(python3 *)`,
   `Bash(node *)`, `Bash(npm *)`, and `npx` are general-purpose runtimes: they open
   arbitrary sockets and extract archives directly, with no denied binary involved.
   `python3 -c 'import urllib.request; ...'` and `node -e 'fetch(...)'` reproduce exactly
   the HTTP fetch / data exfil that denying `curl`/`wget` is meant to stop; an
   npx-installed tool reproduces anything else. Denying `tar` would be undone the same
   way. So per-binary network/archive denies are porous by construction. (#63, #69)

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
*different mechanism*: OS-level network sandboxing (egress firewall / netns), or narrowing
the interpreter and `gh` grants to specific scripts/subcommands. Until then, keep the deny
list honest about being a speed bump, and prefer documenting a gap over adding a per-binary
deny that gives false assurance.

Tracked in the security-hardening issue stream
(#33 / #36 / #37 / #43 / #44 / #45 / #46 / #53 / #58 / #63 / #68 / #69 / #71).
