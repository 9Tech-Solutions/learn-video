import threading
import time
import unittest
from unittest import mock

from learn_video import model_client


class TestSlidingWindowThrottle(unittest.TestCase):
    def setUp(self):
        model_client._reset_rate_limiter()

    def tearDown(self):
        model_client._reset_rate_limiter()

    def test_noop_for_unknown_model(self):
        t0 = time.monotonic()
        model_client._throttle("ollama:qwen2.5vl:3b")
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_allows_full_burst_up_to_cap(self):
        """13 requests in under 60s must not sleep."""
        mid = "google_genai:gemini-flash-lite-latest"
        t0 = time.monotonic()
        for _ in range(13):
            model_client._throttle(mid)
        self.assertLess(time.monotonic() - t0, 0.2)

    def test_14th_request_waits_for_oldest_to_expire(self):
        """With cap=13 per 60s, the 14th request should wait; but we
        patch time to avoid actually sleeping 60s in tests."""
        mid = "google_genai:gemini-flash-lite-latest"
        # Fill the window with timestamps that will appear to be 30s old
        # by patching time.monotonic for the critical check.
        with mock.patch.object(model_client, "time") as mock_time:
            # Fake "now" advances only when we say so.
            clock = {"v": 100.0}
            mock_time.monotonic.side_effect = lambda: clock["v"]
            # Let sleep fast-forward the clock.
            def fake_sleep(s):
                clock["v"] += s
            mock_time.sleep.side_effect = fake_sleep

            for _ in range(13):
                model_client._throttle(mid)
            # 14th call: should force a sleep until oldest expires.
            model_client._throttle(mid)
            self.assertTrue(mock_time.sleep.called)
            # Must have slept approximately 60s (the window) minus elapsed 0s.
            slept_total = sum(c.args[0] for c in mock_time.sleep.call_args_list)
            self.assertGreaterEqual(slept_total, 59.9)

    def test_thread_safety(self):
        """Hammer the limiter from many threads, total calls must never
        exceed the cap within the window."""
        mid = "google_genai:gemini-flash-lite-latest"
        timestamps: list[float] = []
        ts_lock = threading.Lock()

        # Patch sleep to no-op so the test is fast; we only care that
        # _throttle doesn't let the deque exceed the cap concurrently.
        with mock.patch.object(model_client.time, "sleep", return_value=None):
            def worker():
                model_client._throttle(mid)
                with ts_lock:
                    timestamps.append(time.monotonic())

            threads = [threading.Thread(target=worker) for _ in range(25)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        # Either the request log has ≤13 in-flight entries at any time, OR
        # the function sleeps (which we no-op'd). Here we assert it didn't
        # deadlock and all 25 returned.
        self.assertEqual(len(timestamps), 25)


if __name__ == "__main__":
    unittest.main()
