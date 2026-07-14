---
name: paste
description: Formats output so it can be copied and pasted directly into its destination with zero cleanup — the right register (plain text, markdown, or raw code) for where it's going, never a generic default. Use whenever a response is going to be copied somewhere else — into an email, a Slack/iMessage/text thread, a GitHub PR/issue/README, an Obsidian/Notion note, a terminal, or a script file. Trigger on explicit asks ("/paste", "give me something pasteable", "make this copy-pasteable", "no markdown for this", "format this for email/slack/github") AND implicitly, automatically, any time you are about to output a code block, shell command, config file, or commit/PR-style text that the user will copy elsewhere — don't wait to be asked. Also applies retroactively: "reformat that for X" or "strip the markdown from that" should reformat the most recent relevant content.
---

# Paste

Content that's about to be copied somewhere else should arrive in the register that destination expects — nothing to strip, nothing to add, nothing that breaks when it lands. A markdown-formatted paragraph pasted into Gmail shows up as literal asterisks and pound signs. A shell script with explanatory comments pasted into a terminal echoes noise line by line. A GitHub PR description with no markdown at all reads as an undifferentiated wall of text where headers and lists would have organized it. Each destination has one register that actually works; this skill is about picking it correctly instead of defaulting to whatever Claude would naturally write.

## Step 1 — identify the destination

Look at what the user said and what the content is. Most of the time this is obvious from context — don't ask if you can reasonably infer it.

| Signal in the request | Destination | Register |
|---|---|---|
| "copy into an email", "send this to...", "text him", "paste into Slack/iMessage" | Email / chat / message | **Plain text** |
| "for the PR description", "put this in the README", "for my notes", "for GitHub/Obsidian/Notion" | Markdown doc | **Markdown** |
| "run this", "shell script", "paste into my terminal", "add to my .zshrc/config file" | Shell / code / config | **Runnable code, no comments** |
| A code block, command, or config is the natural output of the task (no destination stated) | Same file/terminal it's meant to run in | **Runnable code, no comments** — apply automatically |
| Prose is the natural output and no destination is stated | Unknown | **Plain text** (see Step 3) |

If two signals conflict (e.g., "give me a script for the PR description"), the noun after "for" wins — that's the actual destination, and here the script is display content inside a markdown doc, so it keeps its code-block fence but still drops comments meant only for a human reading it live.

## Step 2 — apply the register

**Plain text (email, chat, text messages):**
No `#` headers, no `**bold**`/`_italic_`, no `` ` `` backticks, no `[]()` links, no markdown tables. If you need structure, use line breaks, blank lines between ideas, and plain dashes or numbers (`1.`, `-`) — these read fine as literal characters, unlike `#` or `**`, which don't. Write it the way you'd actually type it into a Gmail compose box, because that's exactly where it's going.

**Markdown (GitHub, README, notes, wikis):**
Full markdown is correct here — headers, bold, code fences, tables, links. This is the one case where markdown syntax is the deliverable, not an artifact to strip. Match the target's conventions: PR descriptions are typically terse with a summary + test plan; README sections use whatever heading level fits the existing doc; Obsidian/Notion notes can use `[[wikilinks]]` if the user's vault does.

**Runnable code / shell / config:**
This is the CLAUDE.md rule generalized: strip every comment whose only job is explaining what the code does to a human reading it *right now* in this conversation — that explanation belongs in your surrounding chat message, not in the pasted artifact, because it'll sit there stale forever once pasted. Keep a comment only if it documents something that will still be true and non-obvious after paste (a genuine warning, a required env var, a non-obvious flag). No markdown fencing inside the actual file content — the ` ```bash ` fence is for display in this chat, not something that goes into the file. Make sure the snippet is complete and runs as-is: no `# ... rest of your code` placeholders, no partial diffs presented as whole files, no unresolved variables the user has to fill in unless you say so explicitly.

## Step 3 — when the destination is genuinely ambiguous

If the content is prose (not code) and nothing in the request signals where it's going, default to **plain text, no markdown**. Reasoning: plain text works everywhere a paste target could be — email, Slack, a text file, a Word doc — while markdown only works in the subset of places that render it. Markdown pasted somewhere that doesn't render it is broken; plain text pasted somewhere that does render markdown just looks like plain text, which is never wrong. If you're still unsure and the cost of guessing wrong is high (long-form content, high-stakes destination), ask once — but for a quick "give me a paste-ready version of this," infer and proceed rather than pausing to interrogate a two-line request.

## Examples

**Input:** "can you write that explanation up so I can paste it into an email to my landlord"
**Output:** Plain paragraphs, no headers or bold, a plain `-` list if needed, sign-off as literal text — nothing that would show up as `**` or `#` in a Gmail compose window.

**Input:** "add a bash function to my .zshrc that greps running docker containers by name"
**Output:** Just the function — no `# this function greps containers` comment above it, no fence-only markdown wrapper implying it's for display rather than the file, ready to drop straight into `.zshrc` and `source` it.

**Input:** "write the PR description"
**Output:** Markdown — `## Summary`, `## Test plan` with a checklist, matching how this repo's other PRs are typically formatted.

**Input:** "give me a paste of this migration plan" (no destination stated, content is prose)
**Output:** Plain text by default (Step 3) — unless the surrounding conversation makes clear it's headed to a GitHub issue or doc, in which case use markdown instead.
