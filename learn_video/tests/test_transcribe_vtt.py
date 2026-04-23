import tempfile
import textwrap
import unittest
from pathlib import Path

from learn_video.transcribe import _parse_vtt, _strip_overlap


class TestVttParser(unittest.TestCase):
    def test_parses_simple_cues(self):
        vtt = textwrap.dedent(
            """\
            WEBVTT
            Kind: captions
            Language: en

            00:00:01.000 --> 00:00:04.000
            Welcome to the show

            00:00:05.500 --> 00:00:08.000
            <c>Second cue</c>
            """
        )
        with tempfile.NamedTemporaryFile("w", suffix=".vtt", delete=False, encoding="utf-8") as fh:
            fh.write(vtt)
            path = Path(fh.name)
        try:
            text, segments = _parse_vtt(path)
            self.assertIn("Welcome", text)
            self.assertIn("Second cue", text)
            self.assertEqual(len(segments), 2)
            self.assertAlmostEqual(segments[0]["start"], 1.0)
            self.assertAlmostEqual(segments[1]["end"], 8.0)
        finally:
            path.unlink(missing_ok=True)


class TestStripOverlap(unittest.TestCase):
    def test_strips_prefix_matching_previous_suffix(self):
        self.assertEqual(_strip_overlap("hello world", "world today"), "today")

    def test_no_overlap_returns_input(self):
        self.assertEqual(_strip_overlap("alpha beta", "gamma delta"), "gamma delta")

    def test_full_overlap_yields_empty(self):
        self.assertEqual(_strip_overlap("foo bar", "foo bar"), "")

    def test_preserves_word_boundary(self):
        # "and" appears inside "sandbox"; we must not cut mid-word
        self.assertEqual(
            _strip_overlap("testing and", "sandbox is fine"),
            "sandbox is fine",
        )

    def test_youtube_scroll_captions_pattern(self):
        """Simulate the exact pattern seen on YouTube auto-captions."""
        vtt = textwrap.dedent(
            """\
            WEBVTT

            00:00:01.000 --> 00:00:02.000
            React server components. Love them or

            00:00:02.000 --> 00:00:04.000
            React server components. Love them or
            hate them seems mostly hate these days.

            00:00:04.000 --> 00:00:04.010
            hate them seems mostly hate these days.

            00:00:04.010 --> 00:00:06.000
            hate them seems mostly hate these days.
            But that might be about to change as
            """
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".vtt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(vtt)
            path = Path(fh.name)
        try:
            text, _ = _parse_vtt(path)
            # Each phrase should appear exactly once
            self.assertEqual(text.count("React server components"), 1)
            self.assertEqual(text.count("hate them seems"), 1)
            self.assertEqual(text.count("But that might"), 1)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
