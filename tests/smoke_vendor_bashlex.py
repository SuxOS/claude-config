#!/usr/bin/env python3
"""Standalone smoke test for the vendored bashlex (#388 step 1/3): import it and parse a trivial
command without raising. Proves the vendored copy is importable from a `hooks/` directory — either
the repo tree directly, or an `install.sh`-built tree reached only via symlinks — before any rail
migration depends on it.

Usage: smoke_vendor_bashlex.py <hooks_dir>
Exit 0 = imported and parsed cleanly; exit 1 = failed.
"""
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: smoke_vendor_bashlex.py <hooks_dir>", file=sys.stderr)
        return 1
    hooks_dir = sys.argv[1]
    sys.path.insert(0, f"{hooks_dir}/vendor")
    import bashlex

    result = bashlex.parse("echo hi")
    if not result:
        print("bashlex.parse('echo hi') returned no nodes", file=sys.stderr)
        return 1
    print(f"OK: vendored bashlex parsed 'echo hi' -> {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
