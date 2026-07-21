#!/usr/bin/env python3
"""Run the real-shape hook fixture corpus and assert each hook's exit-code contract (#117).

A large share of the hook bug history is one root cause: the hooks parse real Claude Code
tool-input / transcript JSON and repeatedly get the SHAPE wrong (#62, #80, #105, #108, #111,
#112). tests/test_hooks.sh already exercises the hooks, but with hand-authored synthetic JSON —
the same shape the author guessed. A wrong guess in the hook and a matching wrong guess in the
test then pass together, so the test cannot catch the very bug class it exists for.

This runner closes that: it drives each live hook under home/.claude/hooks/ against a committed
corpus captured in the REAL Claude Code envelope shape (tests/fixtures/), and asserts the
documented exit-code contract (2 = block, 0 = allow). If Claude Code's schema drifts and a hook
mis-models it, a fixture flips and CI fails here instead of the hook silently wedging a session
or neutering a gate at runtime. See tests/fixtures/README.md for the corpus layout and how to
regenerate/redact fixtures when the schema evolves.

The manifest (tests/fixtures/manifest.json) lists cases of two kinds:
  - "stdin"      : a full PreToolUse hook-input payload piped straight to the hook. A case may
                   also set "cwd_template" to a name in CWD_TEMPLATES ("held_branch_repo" (#170),
                   "destructive_git_repo" (#291)) when the hook under test reads live git state
                   from `cwd` — the fixture's placeholder cwd is swapped for a throwaway repo built
                   by that template's builder function.
  - "transcript" : a Stop-hook transcript JSONL; the runner synthesizes the Stop envelope
                   ({stop_hook_active, transcript_path -> the fixture}) and pipes that.

Exit 0 = every case matched its expected exit code; exit 1 = one or more mismatched (each
printed with hook + fixture + expected/actual + description). Run: python3 tests/run_fixture_corpus.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent            # tests/
FIXTURES = HERE / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
REPO_ROOT = HERE.parent
HOOKS = REPO_ROOT / "home" / ".claude" / "hooks"

# Redacted, deterministic values for the synthesized Stop envelope. The transcript_path is the
# one field the Stop hook actually reads to a file, so it is filled in per case at run time.
STOP_ENVELOPE_BASE = {
    "session_id": "00000000-0000-0000-0000-000000000000",
    "cwd": "/home/user/example-project",
    "hook_event_name": "Stop",
    "stop_hook_active": False,
}

# block-checkout-held-branch.py consults live `git worktree list` state in the fixture's `cwd`
# (#170) — unlike the other hooks here it cannot be exercised by static JSON alone. A case with
# "cwd_template": "held_branch_repo" gets this placeholder swapped for a throwaway repo (mirrors
# tests/test_hooks.sh's #123 setup: branch `held` checked out in a second worktree) built once and
# torn down at the end of main().
HELD_BRANCH_PLACEHOLDER = "__HELD_BRANCH_REPO__"

# block-destructive-git.py's force-push and clean-force predicates likewise consult live git
# state (a remote-tracking ref, `git clean -n`'s preview) that a static JSON fixture can't
# capture (#291) — same "cwd_template" shape as held_branch_repo, a distinct placeholder/builder
# pair registered in CWD_TEMPLATES below.
DESTRUCTIVE_GIT_PLACEHOLDER = "__DESTRUCTIVE_GIT_REPO__"


def make_held_branch_repo():
    """Build a throwaway repo whose branch `held` is checked out in a second worktree. Returns
    (tmp_dir_to_clean_up, repo_path). Raises on any git failure — a broken fixture setup should
    fail the corpus loudly, not silently skip the cases that need it."""
    tmp = tempfile.mkdtemp(prefix="fixture-held-branch-")
    repo = str(Path(tmp) / "repo")
    heldwt = str(Path(tmp) / "heldwt")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", repo, "branch", "held"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", heldwt, "held"], check=True, capture_output=True)
    return tmp, repo


def make_destructive_git_repo():
    """Build a throwaway repo whose `origin/main` remote-tracking ref sits AHEAD of the local
    `main` tip (a real `git push`, then a local `reset --hard` back a commit, leaves the
    remote-tracking ref cached at the newer commit) plus one untracked file. Returns
    (tmp_dir_to_clean_up, repo_path). Raises on any git failure (#291).

    This one repo state serves all four block-destructive-git.py fixtures: `git push -f origin
    main` is a real (non-fast-forward) force-push hit — `origin/main` is not an ancestor of the
    local `main` tip, so forcing it would discard the `feature` commit; `git push -f origin
    new-feature` is a safe force-push (no `origin/new-feature` remote-tracking ref exists at all,
    same as pushing a brand-new branch); `git clean -f` is a clean-force hit (the untracked file
    would actually be removed); `git clean -nf` is the dry-run form, always safe by construction."""
    tmp = tempfile.mkdtemp(prefix="fixture-destructive-git-")
    bare = str(Path(tmp) / "remote.git")
    repo = str(Path(tmp) / "repo")
    subprocess.run(["git", "init", "--bare", "-q", bare], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "feature"],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", repo, "push", "-q", "origin", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "reset", "-q", "--hard", "HEAD~1"], check=True, capture_output=True)
    (Path(repo) / "untracked.txt").write_text("fixture\n")
    return tmp, repo


# Registry of every "cwd_template" name a manifest case can reference: placeholder text -> builder.
# A builder runs at most once per corpus run, only when at least one case actually needs it.
CWD_TEMPLATES = {
    "held_branch_repo": (HELD_BRANCH_PLACEHOLDER, make_held_branch_repo),
    "destructive_git_repo": (DESTRUCTIVE_GIT_PLACEHOLDER, make_destructive_git_repo),
}


def run_hook(hook_path, stdin_bytes):
    """Pipe stdin_bytes to the hook and return its exit code (stdout/stderr suppressed)."""
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin_bytes,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode


def validate_transcript(transcript):
    """Assert every non-empty line of a transcript fixture is valid JSON, else raise ValueError.

    verify-completion-claim.py's loader fails OPEN on any parse error — turn_lines() catches the
    JSONDecodeError, returns [], and the hook exits 0. So a corrupted line in an allow-expected
    (expect_exit 0) fixture would still yield exit 0 and the case would PASS despite the fixture
    being inert — the silent-rot failure mode json-validate/evals-lint exist to prevent, but which
    *.jsonl is exempt from (JSONL is not single-document JSON). Parse each line here so a broken
    transcript fixture fails the corpus loudly instead of passing on the hook's fail-open path (#139).
    """
    for lineno, line in enumerate(transcript.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"malformed JSONL at {transcript.name}:{lineno} — {e}")


def build_stdin(case, template_repos):
    """The stdin payload bytes for a case: a raw PreToolUse fixture, or a synthesized Stop envelope.

    `template_repos` maps a "cwd_template" name (see CWD_TEMPLATES) to the live repo path built
    for it; a case's fixture placeholder is substituted for that path when the case sets one.
    """
    if "stdin" in case:
        raw = (FIXTURES / case["stdin"]).read_bytes()
        template = case.get("cwd_template")
        if template:
            placeholder, _builder = CWD_TEMPLATES[template]
            raw = raw.replace(placeholder.encode(), template_repos[template].encode())
        return raw
    if "transcript" in case:
        transcript = FIXTURES / case["transcript"]
        if not transcript.exists():
            raise FileNotFoundError(f"transcript fixture not found: {transcript}")
        validate_transcript(transcript)
        envelope = dict(STOP_ENVELOPE_BASE, transcript_path=str(transcript))
        return json.dumps(envelope).encode()
    raise ValueError("case has neither 'stdin' nor 'transcript'")


def main():
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"fixture corpus: cannot read manifest {MANIFEST} — {e}", file=sys.stderr)
        return 1

    cases = manifest.get("cases", [])
    if not cases:
        print("fixture corpus: manifest has no cases", file=sys.stderr)
        return 1

    fails = 0

    needed_templates = {case["cwd_template"] for case in cases if case.get("cwd_template")}
    template_tmp_dirs = {}
    template_repos = {}
    for name in needed_templates:
        _placeholder, builder = CWD_TEMPLATES[name]
        template_tmp_dirs[name], template_repos[name] = builder()

    referenced = {
        (FIXTURES / (case["stdin"] if "stdin" in case else case["transcript"])).resolve()
        for case in cases
        if "stdin" in case or "transcript" in case
    }
    tracked = set((FIXTURES / "pretooluse").glob("*.json")) | set((FIXTURES / "transcripts").glob("*.jsonl"))
    orphans = sorted(f for f in tracked if f.resolve() not in referenced)
    for orphan in orphans:
        print(
            f"  FAIL: {orphan.relative_to(FIXTURES)} — fixture not referenced by any manifest case "
            "(dropped-in-but-unwired, never runs)",
            file=sys.stderr,
        )
        fails += 1

    for case in cases:
        src = case.get("stdin") or case.get("transcript") or "?"
        hook_name = case.get("hook", "?")
        hook_path = HOOKS / hook_name
        expect = case.get("expect_exit")
        desc = case.get("desc", "")

        if not hook_path.exists():
            print(f"  FAIL: {hook_name} <- {src} — hook not found at {hook_path}", file=sys.stderr)
            fails += 1
            continue

        try:
            stdin_bytes = build_stdin(case, template_repos)
        except (FileNotFoundError, ValueError) as e:
            print(f"  FAIL: {hook_name} <- {src} — {e}", file=sys.stderr)
            fails += 1
            continue

        actual = run_hook(hook_path, stdin_bytes)
        if actual == expect:
            print(f"  ok: {hook_name} <- {src} (exit={actual}) — {desc}")
        else:
            print(
                f"  FAIL: {hook_name} <- {src} — expected exit={expect}, got exit={actual} — {desc}",
                file=sys.stderr,
            )
            fails += 1

    for tmp_dir in template_tmp_dirs.values():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    total = len(cases) + len(orphans)
    if fails:
        print(f"fixture corpus: {fails}/{total} case(s) FAILED", file=sys.stderr)
        return 1
    print(f"fixture corpus: all {total} case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
