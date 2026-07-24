from __future__ import annotations

import unittest

from drain.runtime import CircuitBreaker, RetryError, run_with_retry


class TestRetry(unittest.TestCase):
    def test_success_first_try(self) -> None:
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return 42

        self.assertEqual(run_with_retry(fn, retries=2, sleep=lambda _: None), 42)
        self.assertEqual(calls["n"], 1)

    def test_success_after_one_failure(self) -> None:
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("transient")
            return "ok"

        self.assertEqual(run_with_retry(fn, retries=2, sleep=lambda _: None), "ok")
        self.assertEqual(calls["n"], 2)

    def test_exhaustion_raises_retryerror(self) -> None:
        slept = []

        def fn():
            raise RuntimeError("always")

        with self.assertRaises(RetryError) as ctx:
            run_with_retry(fn, retries=2, backoff_base=0.1, sleep=slept.append)
        self.assertEqual(ctx.exception.attempts, 3)
        # backoff sequence: 0.1 * 2**0, 0.1 * 2**1 between the 3 attempts.
        self.assertEqual(len(slept), 2)
        self.assertAlmostEqual(slept[0], 0.1)
        self.assertAlmostEqual(slept[1], 0.2)


class TestCircuitBreaker(unittest.TestCase):
    def test_opens_at_threshold(self) -> None:
        cb = CircuitBreaker(threshold=2)
        self.assertFalse(cb.is_open("s"))
        cb.record_fail("s")
        self.assertFalse(cb.is_open("s"))
        cb.record_fail("s")
        self.assertTrue(cb.is_open("s"))

    def test_ok_resets_counter(self) -> None:
        cb = CircuitBreaker(threshold=2)
        cb.record_fail("s")
        cb.record_ok("s")
        cb.record_fail("s")
        self.assertFalse(cb.is_open("s"))


if __name__ == "__main__":
    unittest.main()
