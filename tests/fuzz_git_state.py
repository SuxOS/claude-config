#!/usr/bin/env python3
"""Execution-grounded differential fuzzer over block-destructive-git.py's git-STATE predicates (#310).

tests/fuzz_argv_canon.py (and its execution-grounded sibling tests/fuzz_argv_exec.py) already give
the argv-CANONICALIZATION half of this hook's rails serious combinatorial/differential coverage.
But block-destructive-git.py's other half — the predicates that consult LIVE git repo state to
decide whether a matched argv shape is actually destructive (`_push_force_hit`'s fast-forward
check, `_clean_force_hit`'s `-n` dry-run preview, `_branch_delete_hit`'s merged-into-HEAD check,
`_reset_hard_hit`/`_discard_hit`'s shared `_working_tree_dirty()` check) — has only ever been
covered by a handful of hand-picked scratch-repo scenarios in tests/test_hooks.sh. That's exactly
the "hand-picked shapes only" gap #199 named as the reason the argv-canon fuzzer exists in the
first place: a new gap in an untested repo-state combination goes unnoticed until it bites.

This harness generates randomized real git repo states (varying working-tree/index dirtiness,
untracked/ignored files, commit-graph ancestry, remote-tracking divergence) and, for each state,
checks the predicate's verdict against GROUND TRUTH obtained by actually performing the real git
action in a disposable copy of the repo and observing what really happened — never by re-deriving
the same answer through a second call to the same git plumbing the predicate itself already
trusts (that would just test internal consistency, not correctness):

  - `_working_tree_dirty()` (which `_reset_hard_hit`/`_discard_hit` both key off) is checked by
    actually running `git reset --hard` in a disposable clone and diffing every tracked file's
    content before vs. after — if anything actually changed, something real was there to lose.
  - `_clean_force_hit` is checked by actually running the same `-f`/`-fd`/`-fx`/`-fdx` clean flags
    (no `-n`) in a disposable clone and diffing the real file listing before vs. after, mirroring
    the module's own docstring ("actually run `git clean -f` in a throwaway clone and compare
    against what the `-n` preview said").
  - `_branch_delete_hit` is checked by actually attempting a real, non-force `git branch -d` in a
    disposable clone: git itself refuses that exact command when the branch isn't fully merged,
    which is independent ground truth for "would `-D` discard commits `-d` would have refused."
  - `_push_force_hit` is checked by actually attempting a real, non-force `git push` to a real bare
    "remote" repo: git rejects it as non-fast-forward exactly when the predicate should flag the
    force-push as unsafe.

Deliberately scoped to these four (the ones the issue names and that have a repo-state-consulting
predicate at all) — `_push_protected_hit` needs a live `gh api` call against a real GitHub repo,
which is out of scope for a local/CI-runnable fuzzer, and `_stash_drop_hit`/`_merge_publish_hit`
have no interesting state-dependent ground truth to differentially check (empty-or-not, and
unconditional-once-matched, respectively).

Standalone ADVISORY job in CI (see .github/workflows/ci.yml), never folded into the required
`shellcheck` job — same reasoning as fuzz-argv-exec/skill-evals (CLAUDE.md): this depends on
real git subprocess behavior across many generated repo states, a strictly heavier and slower
dependency than the pure-computation fuzzer already folded into the required job.

Exit 0 = no violation found; exit 1 = at least one genuine mismatch between a predicate's verdict
and real git ground truth, each printed with the seed that reproduces it.
"""
import importlib.util
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(HERE, "..", "home", ".claude", "hooks")
sys.path.insert(0, HOOKS_DIR)

ITERATIONS_PER_AXIS = 20


def _load_hook_module(filename, name):
    """Every rail's filename has a `-` in it, so none can be `import`ed by name."""
    path = os.path.join(HOOKS_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BDG = _load_hook_module("block-destructive-git.py", "block_destructive_git_under_test")


def sh(args, cwd, check=True):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=10)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd!r}: {r.stderr}")
    return r


def commit(cwd, message, extra_args=()):
    sh(["commit", "-q", "-m", message, *extra_args], cwd)


def init_repo(path):
    os.makedirs(path)
    sh(["init", "-q", "-b", "main"], path)
    sh(["config", "user.email", "t@t"], path)
    sh(["config", "user.name", "t"], path)
    commit(path, "init", ["--allow-empty"])


def snapshot_tracked(repo):
    """{path: bytes-or-None} for every currently tracked file, read straight off disk."""
    names = sh(["ls-files"], repo).stdout.splitlines()
    snap = {}
    for name in names:
        p = os.path.join(repo, name)
        snap[name] = open(p, "rb").read() if os.path.exists(p) else None
    return snap


def list_all_files(repo):
    out = set()
    for root, dirs, files in os.walk(repo):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            out.add(os.path.relpath(os.path.join(root, f), repo))
    return out


# --- axis 1: _working_tree_dirty() (shared by _reset_hard_hit / _discard_hit) -----------------

def make_dirty_scenario(repo, rng):
    with open(os.path.join(repo, "tracked.txt"), "w") as f:
        f.write("orig\n")
    sh(["add", "tracked.txt"], repo)
    commit(repo, "add tracked")
    if rng.random() < 0.5:
        with open(os.path.join(repo, "tracked.txt"), "a") as f:
            f.write("modified unstaged\n")
    if rng.random() < 0.3:
        with open(os.path.join(repo, "staged_new.txt"), "w") as f:
            f.write("new\n")
        sh(["add", "staged_new.txt"], repo)
    if rng.random() < 0.3:  # untracked-only noise — must NOT count as dirty
        with open(os.path.join(repo, "untracked.txt"), "w") as f:
            f.write("untracked\n")


def check_dirty_axis(rng):
    failures = []
    for i in range(ITERATIONS_PER_AXIS):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            init_repo(repo)
            make_dirty_scenario(repo, rng)
            reset_verdict = BDG._reset_hard_hit(["--hard"], repo)
            discard_verdict = BDG._discard_hit("checkout", ["--", "."], repo)

            clone = os.path.join(td, "clone")
            shutil.copytree(repo, clone, symlinks=True)
            before = snapshot_tracked(clone)
            sh(["reset", "-q", "--hard"], clone)
            after = snapshot_tracked(clone)
            ground_truth = before != after

            if reset_verdict != ground_truth:
                failures.append(
                    f"dirty axis #{i}: _reset_hard_hit={reset_verdict} but real "
                    f"`git reset --hard` {'changed' if ground_truth else 'did not change'} "
                    f"tracked files"
                )
            if discard_verdict != ground_truth:
                failures.append(
                    f"dirty axis #{i}: _discard_hit(checkout, --, .)={discard_verdict} but real "
                    f"`git reset --hard` {'changed' if ground_truth else 'did not change'} "
                    f"tracked files"
                )
    return failures


# --- axis 2: _clean_force_hit (dry-run preview vs. a real clean) ------------------------------

FLAG_SETS = [["-f"], ["-fd"], ["-fx"], ["-fdx"]]


def make_clean_scenario(repo, rng):
    if rng.random() < 0.5:
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("*.log\n")
        sh(["add", ".gitignore"], repo)
        commit(repo, "add gitignore")
    if rng.random() < 0.6:
        open(os.path.join(repo, "junk.tmp"), "w").close()
    if rng.random() < 0.5:
        open(os.path.join(repo, "debug.log"), "w").close()  # ignored — only -x/-fx removes it
    if rng.random() < 0.4:
        os.makedirs(os.path.join(repo, "untracked_dir"))
        open(os.path.join(repo, "untracked_dir", "x.txt"), "w").close()


def check_clean_axis(rng):
    failures = []
    for i in range(ITERATIONS_PER_AXIS):
        flags = rng.choice(FLAG_SETS)
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            init_repo(repo)
            make_clean_scenario(repo, rng)
            verdict = BDG._clean_force_hit(flags, repo)

            clone = os.path.join(td, "clone")
            shutil.copytree(repo, clone, symlinks=True)
            before = list_all_files(clone)
            sh(["clean"] + flags, clone)
            after = list_all_files(clone)
            ground_truth = before != after

            if verdict != ground_truth:
                failures.append(
                    f"clean axis #{i} (flags={flags}): _clean_force_hit={verdict} but real "
                    f"`git clean {' '.join(flags)}` "
                    f"{'removed something' if ground_truth else 'removed nothing'}"
                )
    return failures


# --- axis 3: _branch_delete_hit (merged-into-HEAD check) --------------------------------------

def make_branch_scenario(repo, rng):
    merged = rng.random() < 0.5
    sh(["checkout", "-q", "-b", "topic"], repo)
    with open(os.path.join(repo, "topic.txt"), "w") as f:
        f.write("x\n")
    sh(["add", "topic.txt"], repo)
    commit(repo, "topic commit")
    sh(["checkout", "-q", "main"], repo)
    if merged:
        sh(["merge", "-q", "--no-ff", "topic", "-m", "merge topic"], repo)
    return "topic"


def check_branch_delete_axis(rng):
    failures = []
    for i in range(ITERATIONS_PER_AXIS):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            init_repo(repo)
            branch = make_branch_scenario(repo, rng)
            verdict = BDG._branch_delete_hit(["-D", branch], repo)

            clone = os.path.join(td, "clone")
            shutil.copytree(repo, clone, symlinks=True)
            r = sh(["branch", "-d", branch], clone, check=False)
            would_lose_commits = r.returncode != 0  # git itself refused: not fully merged

            if verdict != would_lose_commits:
                failures.append(
                    f"branch-delete axis #{i}: _branch_delete_hit={verdict} but real "
                    f"`git branch -d {branch}` {'was refused' if would_lose_commits else 'succeeded'}"
                )
    return failures


# --- axis 4: _push_force_hit (fast-forward check against a real remote) -----------------------

def make_push_scenario(td, rng):
    bare = os.path.join(td, "origin.git")
    sh(["init", "-q", "--bare", "-b", "main", bare], td)
    repo = os.path.join(td, "repo")
    sh(["clone", "-q", bare, repo], td)
    sh(["config", "user.email", "t@t"], repo)
    sh(["config", "user.name", "t"], repo)
    with open(os.path.join(repo, "f.txt"), "w") as f:
        f.write("x\n")
    sh(["add", "f.txt"], repo)
    commit(repo, "init")
    sh(["push", "-q", "-u", "origin", "main"], repo)

    is_fast_forward = rng.random() < 0.5
    if is_fast_forward:
        commit(repo, "ff commit", ["--allow-empty"])
    else:
        # amend the tip that origin/main still points at: same position, different commit
        # identity (no parent in common) — origin/main is provably NOT an ancestor any more.
        sh(["commit", "--amend", "-q", "-m", "diverged"], repo)
    return repo, is_fast_forward


def check_push_force_axis(rng):
    failures = []
    for i in range(ITERATIONS_PER_AXIS):
        with tempfile.TemporaryDirectory() as td:
            repo, is_fast_forward = make_push_scenario(td, rng)
            verdict = BDG._push_force_hit(["-f"], repo)

            r = sh(["push", "-q", "origin", "main"], repo, check=False)
            would_lose_commits = r.returncode != 0  # real git rejected it as non-fast-forward

            if verdict == would_lose_commits:
                continue
            failures.append(
                f"push-force axis #{i} (fast_forward={is_fast_forward}): "
                f"_push_force_hit={verdict} but a real non-force `git push` "
                f"{'was rejected' if would_lose_commits else 'succeeded'}"
            )
    return failures


def main():
    rng = random.Random(0)  # fixed seed: a failure here must reproduce deterministically
    all_failures = []
    for axis in (check_dirty_axis, check_clean_axis, check_branch_delete_axis, check_push_force_axis):
        all_failures.extend(axis(rng))

    if all_failures:
        print(f"{len(all_failures)} git-state predicate violation(s) found:", file=sys.stderr)
        for f in all_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"no violations found ({ITERATIONS_PER_AXIS} iterations x 4 axes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
