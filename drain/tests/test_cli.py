from __future__ import annotations

import unittest

from drain.cli import build_parser


class TestCli(unittest.TestCase):
    def test_global_flag_before_subcommand(self) -> None:
        args = build_parser().parse_args(["--json", "audit"])
        self.assertEqual(args.cmd, "audit")
        self.assertTrue(args.json)

    def test_global_flag_after_subcommand(self) -> None:
        # The papercut fix: globals must work in both positions.
        args = build_parser().parse_args(["audit", "--json"])
        self.assertTrue(args.json)

    def test_apply_verdicts_with_mode_and_global(self) -> None:
        args = build_parser().parse_args(["apply-verdicts", "--mode", "run", "--json"])
        self.assertEqual(args.cmd, "apply-verdicts")
        self.assertEqual(args.mode, "run")
        self.assertTrue(args.json)

    def test_limit_and_source(self) -> None:
        args = build_parser().parse_args(["run", "--limit", "5", "--source", "mock"])
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.source, ["mock"])

    def test_subcommand_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])


if __name__ == "__main__":
    unittest.main()
