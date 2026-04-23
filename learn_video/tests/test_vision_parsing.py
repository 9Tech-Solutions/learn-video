import unittest

from learn_video.vision import _extract_visual_and_fused, _parse_timeline


class TestExtractVisualAndFused(unittest.TestCase):
    def test_extracts_both(self):
        body = """VISUAL: code editor showing Express route
FUSED: basic route returning JSON; they refactor this later"""
        visual, fused = _extract_visual_and_fused(body)
        self.assertEqual(visual, "code editor showing Express route")
        self.assertIn("basic route", fused)

    def test_missing_visual_is_none(self):
        visual, fused = _extract_visual_and_fused("FUSED: just the fused line")
        self.assertIsNone(visual)
        self.assertIn("just the fused", fused)

    def test_unparseable_preserves_raw(self):
        raw = "this is a completely unstructured response with no markers"
        visual, fused = _extract_visual_and_fused(raw)
        self.assertIsNone(visual)
        self.assertEqual(fused, raw.strip())


class TestParseTimeline(unittest.TestCase):
    def test_parses_multiple_blocks(self):
        txt = """
[00:05]
AUDIO: Speaker introduces the topic
VISUAL: title slide
FUSED: sets up the demo

[00:20]
AUDIO: Running the command
VISUAL: terminal with `npm run dev`
FUSED: entry-point for the dev server
"""
        blocks = _parse_timeline(txt)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].t, 5.0)
        self.assertEqual(blocks[1].t, 20.0)
        self.assertIn("dev server", blocks[1].fused)


if __name__ == "__main__":
    unittest.main()
