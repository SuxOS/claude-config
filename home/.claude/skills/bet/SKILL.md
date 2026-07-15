---
name: bet
description: The "prove it's real" directive — adversarially verify a result, claim, or finished piece of work instead of trusting it. Inquiry family; append "?" and the count (1–5) scales rigor (/bet? one check → /bet????? adversarial panel). Read-mostly. Use for "/bet", "/bet???", "prove it", "you sure?", "verify this", "is that actually true".
---

**`bet` means: don't trust it — try to break it.** The object is whatever's being claimed true: your own just-finished work, a passing test, a "this fixes it," a stated fact, a plan's assumption. Default stance is **skeptic** — assume it's wrong until it survives a real attempt to falsify it.

Every verb already runs a cheap version of this automatically — the *no completion claim without fresh evidence* rail (CLAUDE.md). `bet?` is when you deliberately turn that dial up: the explicit, adversarial, multi-lens verification for when a plain smoke-check isn't enough.

## `?` scales rigor

Count the trailing `?` (1–5): how hard you try to break it.

- **`/bet?`** — One honest check. Re-derive the claim from ground truth, run the actual thing, look for the obvious hole. Confirm or refute.
- **`/bet???`** — Multiple independent angles: reproduce it, check the edge cases, read what the claim *depends* on, look for the counterexample.
- **`/bet?????`** — Adversarial panel: several independent skeptics, each prompted to *refute*, each from a different lens (correctness, edge cases, security, does-it-actually-reproduce). Majority-refute kills it. Default to "refuted" under uncertainty. Fan them out in parallel.

More `?` buys more independent verification effort — not a softer bar. The goal is to *fail* the claim if it can be failed; a `bet` that only looks for confirmation is worthless.

## How to run it

1. **State the claim precisely** — what exactly is asserted true? Vague claims can't be tested.
2. **Go to ground truth** — run it, reproduce it, read the source, check the data. Never verify one artifact against another artifact; verify against reality.
3. **Attack, don't admire** — construct the input that breaks it, the case it forgot, the assumption that doesn't hold.
4. **Rule at the chosen rigor** — CONFIRMED (survived the attack), REFUTED (here's the failing case), or UNCERTAIN (here's what I couldn't test and why).

## Output

Verdict first, evidence second:
`[CONFIRMED|REFUTED|UNCERTAIN] <claim> — <the failing case, the repro, or the gap>`

A REFUTED verdict hands off to `go` (fix it) or `fml` (if it's already broken in the wild). Never soften a refutation to be agreeable — a false CONFIRMED is the one outcome that defeats the whole point.

## Read-mostly

`bet` may *run* things to test them (tests, repros, queries) but never changes the work it's judging — verifying and editing are different jobs. Fixing is `go`'s.

## Delegate for the common case

If the claim is "this code change works," prefer the built-in `verify` skill — it already drives the actual feature end-to-end. Reach for `bet?`'s adversarial-panel machinery when the claim is broader than one code change (a fact, a plan assumption, someone else's finding) or when `?` count ≥3 calls for multi-lens refutation `verify` doesn't do.
