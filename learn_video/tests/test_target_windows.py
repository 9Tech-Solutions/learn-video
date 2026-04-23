import unittest

from learn_video.target import (
    _SINGLE_PASS_MAX_S,
    _WINDOW_S,
    _segments_to_windows,
)


def _mk_segments(count: int, step_s: float = 5.0) -> list[dict]:
    return [
        {"start": i * step_s, "end": (i + 1) * step_s, "text": f"line {i}"}
        for i in range(count)
    ]


class TestSegmentsToWindows(unittest.TestCase):
    def test_single_window_for_short_video(self):
        segs = _mk_segments(30, step_s=10.0)  # 300s of content
        windows = _segments_to_windows(segs, duration_s=300.0)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0][0], 0.0)
        # Every segment appears
        self.assertEqual(windows[0][2].count("line"), 30)

    def test_long_video_splits_into_15min_windows(self):
        # 2 hours of content, expect 8 windows of 15 min each
        segs = _mk_segments(1440, step_s=5.0)  # 7200s
        windows = _segments_to_windows(segs, duration_s=7200.0)
        self.assertEqual(len(windows), 8)
        # Windows advance by exactly _WINDOW_S
        self.assertAlmostEqual(windows[1][0] - windows[0][0], _WINDOW_S)

    def test_windows_overlap_slightly(self):
        """A segment at a window boundary should appear in both adjacent
        windows (30s overlap), so the model doesn't miss cross-boundary
        references."""
        segs = _mk_segments(2000, step_s=1.0)
        windows = _segments_to_windows(segs, duration_s=2000.0)
        # Segment at 900s sits on the edge between window 0 and window 1
        self.assertIn("[15:00]", windows[0][2])
        self.assertIn("[15:00]", windows[1][2])

    def test_constants_consistent(self):
        self.assertGreater(_SINGLE_PASS_MAX_S, 0)
        self.assertEqual(_WINDOW_S, 900.0)


if __name__ == "__main__":
    unittest.main()
