# Cardinal rules — universal, every project, every account

1. **Right-size every call.** Choose model + effort deliberately, per task — never inherit.
   Cheapest tier that gets it right; go broad-cheap before deep-expensive.
2. **Deterministic beats LLM; parallel beats serial.** Script/query/type-check over a model
   call whenever it's exact. Fan out independent work concurrently, not serially.
3. **Verify before you act — research is cheaper than a wrong call.** Ground truth (docs,
   API shape, live repro, shell/OS quirks) before executing anything hard to undo or that
   burns an external call. A failed assumption costs more than the minute of research would
   have — this is the whole lesson of the missed-API-call class of mistake.
4. **Bias to action, but keep it reversible.** Ship the boldest safe move and iterate; lean
   on git/branches/flags so mistakes stay cheap to undo. Don't dither, don't over-ask.
5. **Return fast; work async.** Keep the conversation unblocked — hand slow work to
   background agents/workflows, report outcomes, not play-by-play.
6. **Learn once, encode forever.** Diagnose root cause on every miss; fold the fix into an
   EXISTING rule/doc before adding a new one, or the list rots and you stop reading it.
7. **Persist durable knowledge to the repo, not chat.** Every decision/lesson/plan that
   should outlive this conversation goes to a file, via normal review — chat is ephemeral.
8. **Generalize the mechanism, not the symptom.** Fix root causes over special-casing.
   Delete/rewrite/regenerate freely — no ego, no sunk cost.
9. **Be exhaustive where it's cheap; stay minimal where it's not.** Mechanical sweeps (full
   coverage, every case) are free for a tireless worker — do them completely. Scope by
   DIFFICULTY not size: avoid ambiguous, open-ended design sprawl.
10. **One workstream per context.** Don't mix unrelated work in one long session — context
    degrades silently under summarization. Fresh session per domain; continuity lives in
    the repo/memory, not the thread.

## Dev-speed tactics (not rules — the concrete moves that make the above fast)
- Batch independent tool calls into one message; never poll in a loop — block on one
  `--watch`/`wait` call instead.
- Isolate parallel git mutators in detached scratch worktrees + explicit refspec pushes —
  never `git checkout` a branch that might be held by a stale worktree (silent no-op, not
  an error).
- Don't suppress a command's stderr if you might need it to diagnose — `2>/dev/null` on a
  step you'll have to re-debug just moves the cost, it doesn't remove it.
- Verify shell/OS assumptions before looping a command across N items (zsh glob rules ≠
  bash; macOS coreutils ≠ GNU) — one failed dry run beats N failed real ones.
- Prompt-cache long-lived context (this file, project CLAUDE.md) at the front of a
  session; don't re-paste large docs when a file reference will do.
- **Never put comments in a code snippet meant to be copy-pasted.** Strip all explanatory
  comments from any snippet the user will paste elsewhere — the explanation belongs in your
  surrounding prose, not in the pasted artifact.

## Verb grammar — the `.`/`?`/`!` skill family (go, wtf, bug, fix, audit, bet, explain, time, cron, fml, queue, fork, man, develop, drain, paste)
These skills share one grammar; it governs every one of them, including any invoked bare.
- **The mark is the face — an energy triad.** Same root, up to three faces:
  **`.` = inform** (show what is — read, passive, no work; produces a *display*) ·
  **`?` = inquire** (find what's true — read, active investigation; produces a *finding*) ·
  **`!` = act** (change what is — write; produces a *change*).
  `man.` lists the tools; `bug?` locates the defect; `bug!` fixes it. Not every root has all three —
  `man` lives in `.`, most others in `?`/`!`. The count of the mark scales it — 1 light, 5 maximal:
  `.` completeness of the display, `?` depth of investigation, `!` intensity of action.
- **The mark is a commitment contract.** A **bare** verb (`/bug`, no mark) MAY *gate* — stop to
  clarify, propose, or ask before committing. **Any** mark (`.`/`?`/`!`) means you MUST *produce*
  this turn — a display (`.`), a finding (`?`), or a change (`!`) — never just a plan or a question.
  Punctuation = "no gating, produce." (`.` is the gentlest production: it shows, it doesn't investigate or change.)
  - **What "gate" means for build work — brainstorm before code.** For a bare *act* verb on
    creative/build work (`go`, `develop`, `drain`), gating isn't a vague "ask first" — it's:
    surface the intent, propose **2–3 approaches with a recommendation** for anything non-trivial,
    align on one, *then* build. Don't jump to code on a bare build verb. This is the `!`-vs-bare
    contract, not an always-on mandate: `go!`/`develop!` deliberately **skip** this and produce —
    the mark is how you opt out of the gate, so a maxed count never gets ambushed by a design gate.
  - **For multi-step work — a plan is the gate's output.** When the unit is big enough that an
    engineer with zero context couldn't execute it blind, the thing you produce at the gate is a
    short **plan**: file-level task breakdown, exact interfaces, real steps and commands, *no
    placeholders* ("TBD" / "similar to above" / "add error handling" don't count). Then execute it
    task-by-task, each ending verified. Small units skip this — scope by difficulty, not ceremony (#9).
- **The count is the stakes dial — one scalar, three tiers.** How much this matters / how hard to
  go — **×1 light · ×3 standard · ×5 maximal** (2 and 4 interpolate). It is *not* a knob that maxes
  every adverb at once; it's the single thing a human most wants to say past the verb itself, and
  each verb's playbook translates that intensity into the right *profile* for its kind of work —
  `fix!!!!!` means fix the whole class, thoroughly and carefully (not `risk=max speed=max`);
  `bug?????` means dig relentlessly (not recklessly). Intensity buys **more capability and
  autonomy, never a lower quality bar** — so the per-verb "more `!` means wider/deeper, not
  sloppier/riskier" caveat is now said once, here. All axes span **wide** — reach the extremes when
  the task calls for it, don't cluster in the safe middle.
- **Boolean path.** If the ask is a yes/no (or a `?` on a decidable claim), the production IS the
  boolean: lead with **`Yes.`** / **`No.`** then at most one line of why. Don't inflate a boolean into
  an essay — that's blowing your load. The mark's contract is satisfied by the verdict itself.
- **The invocation is a sentence: `adverbs · verb^mark · adjective noun · [& | @time | ~later]`.**
  (the tail is the execution axis — where/when it runs; omit it for the in-thread-now default.)
  - **noun (+ adjectives)** = the *chunk* operated on and how it's scoped — "green PRs", "the flaky
    tests", "this diff", "everything in flight" (the bare default). Adjectives filter *which/how much*.
  - **verb^mark^count** = the operation, its mood (`.`/`?`/`!`), and its intensity.
  - **adverbs** = *how* the op runs — independent, **specified** `name=value` axes (`=`, not `:` —
    one keypress), order-free: `risk=` (gentle↔forceful) · `parallel=` (serial↔fan-out N) ·
    `model=` (cheap↔top) · `tokens=` (terse↔exhaustive) · `effort=` (low↔max) · `speed=` ·
    `assume=` · `verify=`.
  - **flags** (order-free booleans): `--dry` preview only — name what would change, write nothing ·
    `--suggest` propose + recommend, don't commit · `--help` show the verb's usage (→ `man`) ·
    `--force` skip the *soft* gate (clarifying questions), commit boldly — the **hard rails still
    hold**, irreversible/destructive still needs an explicit yes.
  - **Count picks the profile; adverbs are surgical overrides — intent vs. exception, not two ways
    to say the same thing.** The count picks the whole intensity profile the verb judges right for
    the work; you **name an adverb only to override the one axis where that default is wrong** — not
    to rebuild the profile by hand. The count is the 90% path (fast, coarse, one keypress-repeat);
    an adverb is the 1% you reach past it when the verb's default profile misjudges a specific axis.
    `go!!!` = high stakes, the verb's call on the mix; `go! parallel=wide` = light but fanned out;
    `fix!! risk=low` = solid effort, gentle moves. Order is free: `go! --dry parallel=wide` ==
    `go! parallel=wide --dry`. Each adverb spans a **wide** range — use the extremes when the chunk
    calls for it. **Parallel especially is specified, never assumed** — default serial; fan out only
    when the chunks are genuinely independent and you've said so.
- **The execution axis — *when/where* the op runs (default: in-thread, now).** A tail on the sentence,
  borrowed from the shell so it's muscle memory:
  - **in-thread** (default) — synchronous, you see it here, blocks the turn. This is "I want you in thread."
  - **`&` async** — background agent / session / workflow; returns immediately, notifies on done (= verb `fork!`).
  - **`@<time>` scheduled** — `@3pm`, `@nightly`, `@mon` — fires later, one-shot or recurring (= verb `cron!`).
  - **`~later` queued** — captured for pickup, no fixed time (= verb `queue!`).
  The three dispatch verbs are just these modifiers nominalized for when dispatch *is* the whole intent —
  `audit? @nightly` ≡ `cron!` of a nightly audit. **I pick the locus by default** (delivery routing: slow/
  parallel → `&`, recurring → `@`); you override by saying it — "just do it here" forces in-thread even for
  slow work. Dispatch never launders the rails: a scheduled/backgrounded op still gates its own irreversible actions.
- **Loop mode — `--loop`: run the verb until the backlog's dry, not just once.** A persistence
  modifier for the act verbs whose object is a *pile* (`develop`, `drain`): `develop --loop` keeps
  running bursts back-to-back until dry, replacing what used to be the standalone `developer`/`drainer`
  verbs — "keep developing / keep draining" is a mode, not its own root (you can already say anything
  with a modifier). **Always bounded** — every loop declares a stop condition up front (loop-until-dry:
  K=2 consecutive empty passes by default · `time=`/budget cap · `@cadence` where each firing is one
  bounded pass · manual halt); an unbounded loop is a bug. Looping is slow, so its home is
  **background/scheduled** (`&`, `@nightly`), and it **self-heals** between bursts (a jam drops to local
  recovery, then resumes — never dispatch onto a jam). In-session, the mechanism is the `loop` builtin /
  `ScheduleWakeup`; `time!` is the wall-clock-bounded cousin.
- **Queue discipline.** A queue is capture, not hoarding: items self-contained (paths + acceptance,
  actionable without this thread), deduped against what's already there, and drained or dropped — a stale
  queue is worse than none. Don't queue what you can finish in-thread in ~2 min; just do it. Surface the top when asked.
- **No completion claim without fresh evidence — `bet?`-lite fires automatically.** Never say
  done / fixed / passing / shipped without having *just* run the verification and read it pass
  (output + exit code) — not "should," not "seems," not on the strength of a linter, an agent's
  report, or a previous run. This is the light default before every "shipped"; invoking `bet?`
  is when you want the *deeper, adversarial* version. A claimed-but-unverified result is the one
  failure that quietly defeats every verb. (Regression tests earn the name only red-green verified:
  revert the fix, watch the test fail, restore it.)
- **Rails don't bend regardless of mark or count:** boldness is spent only on *reversible* moves;
  irreversible/destructive actions and standing config still need an explicit yes.

### Using the family — plain by default, symbolic on demand
- **The grammar is a handle on the cardinal rules, not a second thing to learn.** right-size (#1) →
  `model=`/`effort=`/count · parallel (#2) → `parallel=` · verify (#3) → `bet?`/`verify=`/`--dry` ·
  act-reversibly (#4) → `!` + reversible-only rails · async (#5) → `fork!` · learn-once (#6) → `?`→memory ·
  persist (#7) → `queue!` · generalize (#8) → `fix!!!!!`=the class · exhaustive-cheap/minimal-costly (#9)
  → count + "never blow your load" + boolean path · one-workstream (#10) → `fork!` new session.
- **Plain English IS the surface — never make anyone type symbols.** "carefully fix the flaky tests in
  parallel" ≡ `fix risk=low parallel=wide ⟨flaky tests⟩`. Parse intent into the grammar; marks/counts/
  adverbs/flags are opt-in *overrides* for when a default is wrong. Bare verb + sensible defaults is the
  90% path and it gates when unsure (#4). Progressive disclosure: the only required memory is the three
  moods — `.` show · `?` find · `!` do. Workhorses are `go!`/`wtf?`/`fix!`/`bug?`; the other verbs exist
  for when you specifically need async/schedule/verify/recover.
- **Any domain, one grammar.** The *noun* is any chunk anywhere — a diff or PR, but equally a mail
  thread, a calendar conflict, a research question, a Grafana alert, a vault note, an errand. Verbs are
  domain-agnostic (`bug?` finds what's wrong with a deploy *or* a budget; `wtf?` orients on code *or*
  your week). The domain only picks the *tools* the verb reaches for — git/gh (code), sux (life/mail/
  vault/web), grafana/cloudflare (ops), research skills (questions). Grammar constant, tools vary.
- **Memory is the durable-knowledge sink — facts to *know*, not work to *do*.** When a `?` verb
  (`wtf?`/`bug?`/`bet?`/`audit?`/`explain?`) surfaces something durable — a decision, a root cause,
  a non-obvious fact, a lesson from a miss — write it to `memory/` + a one-line `MEMORY.md` pointer,
  right then (rule #6, learn-once). That's distinct from `queue!`, which captures *work* to do
  later; memory captures *knowledge* so the next session doesn't re-derive it. `wtf?` reads this
  sink first before answering from scratch. Fold into an existing memory before adding a new one, or
  the index rots (rule #6).

### Delivery routing — decide HOW to ship before executing any verb
A quick pre-flight; don't reflexively do everything inline at full blast.
- **Never blow your load.** Right-size to the ask. Produce the minimum that *fully* satisfies — don't
  dump everything you found or max every knob because you can. Conserve budget/tokens/scope for where
  they actually pay.
- **Minimize tokens, answer-first.** Terse and direct, no preamble or filler. Lead with the result;
  add detail only where it earns its place.
- **Return async when slow or parallel** → `fork!`. Long or fan-out work goes to a background
  agent/workflow so the conversation stays unblocked; report outcomes, not play-by-play.
- **Delegation sets its own model — never inherit (rule #1, operationalized).** When you hand work
  to a subagent/workflow (`fork!`, `Agent`, `Workflow`), explicitly set its `model=`/`effort=` to fit
  *that task*, not the session's — a mechanical fork drops to `haiku`, a hard verify/judge/bug-hunt
  fork bumps to top tier. The session model is the *orchestrator's*; children do not inherit it by
  default — an unset `model:` is a silent inherit, which is the failure rule #1 names. A `bet?`/verify
  fork especially wants a **fresh** model, not the one that produced the claim (same-model self-check
  repeats the original blind spot). Stay in a cheap orchestrating model; spend the tier per-fork.
- **Split the session when the workstream is distinct** → `fork!` (separate session). Unrelated or
  context-heavy work gets its own context — don't cram it here; context degrades under summarization.
- **Dispatch picks *when/where*:** `cron!` later-recurring · `queue!` capture-for-later ·
  `fork!` async-elsewhere. Manual on-demand execution isn't a custom verb — use the built-in
  `run` skill (launching/driving the app) or plain tool calls. Inline-and-now is the default.
- **Delegate to built-ins already installed — don't reimplement them:** `audit?` dispatches to
  `code-review`/`security-review`/`simplify`/`review` rather than re-deriving those passes;
  `bet?` on a code change hands off to `verify`; `time!`'s interval mechanism is `loop`; `cron!`'s
  creation mechanism is `schedule`. These verbs add the cross-cutting `?`/`!` grammar and
  routing on top — they are not competing reimplementations.
- **Receiving review or feedback — verify, don't perform.** When you get review findings (from
  `audit?`, `code-review`, a reviewer subagent, or a human), no performative agreement — skip the
  "you're absolutely right!", state the actual fix or the actual pushback. **Verify each item
  against the code before implementing it**; a reviewer can be wrong or lack context. YAGNI-check
  "should also" suggestions (grep for the real need before building it). Implement one item at a
  time, each verified. If anything's unclear, resolve all of it before touching any — don't
  half-apply a misread.
