import unittest

from learn_video.summary import Chapter, _format_with_timestamps, _to_fused_blocks


class TestSummary(unittest.TestCase):
    def test_format_with_timestamps_prefixes_mmss(self):
        segs = [
            {"start": 5.0, "end": 10.0, "text": "hello world"},
            {"start": 65.5, "end": 70.0, "text": "later moment"},
        ]
        out = _format_with_timestamps(segs)
        self.assertIn("[00:05] hello world", out)
        self.assertIn("[01:05] later moment", out)

    def test_format_truncates_at_char_cap(self):
        # 10000 segments of ~20 chars each = ~200k chars → should truncate
        segs = [{"start": i, "end": i + 1, "text": "x" * 50} for i in range(10000)]
        out = _format_with_timestamps(segs)
        self.assertLess(len(out), 55_000)
        self.assertIn("[...truncated...]", out)

    def test_to_fused_blocks_maps_key_points_into_fused(self):
        chapters = [
            Chapter(
                t_start=30.0,
                t_end=120.0,
                topic="Intro to concept X",
                key_points=["X is useful for A", "X differs from Y by Z"],
            ),
        ]
        blocks = _to_fused_blocks(chapters)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].t, 30.0)
        self.assertEqual(blocks[0].audio, "Intro to concept X")
        self.assertIn("X is useful", blocks[0].fused)
        self.assertIn("differs from Y", blocks[0].fused)
        self.assertIsNone(blocks[0].visual)


if __name__ == "__main__":
    unittest.main()
