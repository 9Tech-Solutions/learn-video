import unittest

from learn_video.ingest import _format_for_duration, _timeout_for_duration


class TestFormatForDuration(unittest.TestCase):
    def test_short_video_capped_at_480p(self):
        self.assertIn("480", _format_for_duration(600.0))
        self.assertNotIn("720", _format_for_duration(600.0))

    def test_medium_video_gets_480p(self):
        self.assertIn("480", _format_for_duration(60 * 60.0))

    def test_long_video_gets_360p(self):
        self.assertIn("360", _format_for_duration(2 * 60 * 60.0))

    def test_boundary_90_min(self):
        self.assertIn("480", _format_for_duration(90 * 60))
        self.assertIn("360", _format_for_duration(90 * 60 + 1))


class TestTimeoutForDuration(unittest.TestCase):
    def test_short_video_uses_floor(self):
        self.assertEqual(_timeout_for_duration(60.0), 900)

    def test_long_video_clamps_to_ceiling(self):
        self.assertEqual(_timeout_for_duration(5 * 3600.0), 3600)

    def test_scales_between(self):
        t = _timeout_for_duration(30 * 60.0)
        self.assertGreater(t, 900)
        self.assertLess(t, 3600)


if __name__ == "__main__":
    unittest.main()
