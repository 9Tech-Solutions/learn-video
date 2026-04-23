import unittest

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
        paths = cache.paths_for("test-vid")
        # Note: this creates the frames subdir under the user cache,
        # we clean up after.
        result = _probe_frame_paths(paths, duration_s=600.0)
        try:
            self.assertEqual(len(result), len(_PROBE_FRACTIONS))
            for (t, p), frac in zip(result, _PROBE_FRACTIONS, strict=False):
                self.assertAlmostEqual(t, 600.0 * frac, places=1)
                self.assertTrue(str(p).endswith(".jpg"))
                self.assertIn("probe", str(p))
        finally:
            import shutil
            subdir = paths.frames_dir / "probe"
            if subdir.exists():
                shutil.rmtree(subdir)

    def test_clamps_low_fraction_when_duration_short(self):
        paths = cache.paths_for("test-vid-short")
        result = _probe_frame_paths(paths, duration_s=5.0)
        try:
            # All sample times must be >= 1.0s (per the min in probe.py)
            for t, _ in result:
                self.assertGreaterEqual(t, 1.0)
        finally:
            import shutil
            subdir = paths.frames_dir / "probe"
            if subdir.exists():
                shutil.rmtree(subdir)


if __name__ == "__main__":
    unittest.main()
