import tempfile
import unittest
from pathlib import Path

from learn_video import cache
from learn_video.probe import _PROBE_FRACTIONS, _probe_frame_paths


class TestProbeFramePaths(unittest.TestCase):
    def test_fractions_are_between_0_and_1_exclusive(self):
        for f in _PROBE_FRACTIONS:
            self.assertGreater(f, 0.0)
            self.assertLess(f, 1.0)

    def test_fractions_are_sorted(self):
        self.assertEqual(list(_PROBE_FRACTIONS), sorted(_PROBE_FRACTIONS))

    def test_produces_one_path_per_fraction(self):
        # Temp root: the old version wrote into the real user cache and left
        # empty `test-vid` dirs behind.
        with tempfile.TemporaryDirectory() as tmp:
            paths = cache.CachePaths(root=Path(tmp))
            result = _probe_frame_paths(paths, duration_s=600.0)
            self.assertEqual(len(result), len(_PROBE_FRACTIONS))
            for (t, p), frac in zip(result, _PROBE_FRACTIONS, strict=False):
                self.assertAlmostEqual(t, 600.0 * frac, places=1)
                self.assertTrue(str(p).endswith(".jpg"))
                self.assertIn("probe", str(p))

    def test_clamps_low_fraction_when_duration_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = cache.CachePaths(root=Path(tmp))
            result = _probe_frame_paths(paths, duration_s=5.0)
            # All sample times must be >= 1.0s (per the min in probe.py)
            for t, _ in result:
                self.assertGreaterEqual(t, 1.0)


if __name__ == "__main__":
    unittest.main()
