#!/usr/bin/env python3
"""Argv-echoing helper for tests/fuzz_argv_exec.py (#228). Dumps its OWN observed argv (as JSON,
to stdout) so the execution-grounded fuzzer can compare what a real wrapper binary
(env/timeout/nice/xargs/stdbuf/exec/sudo/...) actually execs against what
`_hookutil.strip_prefixes()` predicts for the same command string — ground truth from the OS
itself, not a model of it. Emits nothing else, so a wrapper's own diagnostics on stderr can't be
confused with this helper's output.
"""
import json
import sys

print(json.dumps(sys.argv))
