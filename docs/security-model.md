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
*different mechanism*: OS-level network sandboxing (egress firewall / netns), a `PreToolUse`
hook that inspects command intent before it runs (see `home/.claude/hooks/`), or narrowing
the interpreter and `gh` grants to specific scripts/subcommands. Until then, keep the deny
list honest about being a speed bump, and prefer documenting a gap over adding a per-binary
deny that gives false assurance. This applies equally to the original `curl`/`ssh`/`scp`
egress denies, not just the later additions — none of them is a network boundary. (#71)

## The first enforced step: `block-egress.py` (#77)

A `PreToolUse` hook — `home/.claude/hooks/block-egress.py`, wired under `hooks.PreToolUse` with a
`Bash` matcher — now takes the first concrete step of the "different mechanism" above. It parses
each Bash command's argv **before it runs** and blocks the two obvious egress forms the deny list
structurally cannot: interpreter/shell inline-code one-liners that open a socket
(`python3 -c 'import urllib…'`, `node -e 'fetch(…)'`, `bash -c '…curl…'`), and `gh api` **writes**
in any argv position (`gh api /repos/O/R -X DELETE`, which the prefix deny misses because the flag
follows the URL). This raises the casual/accidental bar — but it is still a **speed bump, not a
seal**, and the durable lesson stands: base64/variable-obfuscated payloads, sockets built without a
named primitive, and interpreters fed code from a file or stdin all pass it, so a *complete* egress
boundary still needs OS-level network sandboxing. The hook makes the gh-api gap enforceable at the
argv layer, which is what let the deny be narrowed back (#76) from a blanket `Bash(gh api *)` to
just the two write-method forms above — restoring the read-only `gh api repos/…` GETs the skills
use, while the hook still catches writes that slip past the URL-then-flag ordering gap.

Tracked in the security-hardening issue stream
(#33 / #36 / #37 / #43 / #44 / #45 / #46 / #53 / #58 / #63 / #68 / #69 / #71 / #77).
