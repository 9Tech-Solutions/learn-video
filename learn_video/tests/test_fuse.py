import unittest

from learn_video.fuse import format_markdown
from learn_video.state import FusedBlock


class TestFormatMarkdown(unittest.TestCase):
    def test_empty_blocks_produces_placeholder(self):
        md = format_markdown(
            title="T",
            url="https://x.test/v",
            video_id="abc",
            blocks=[],
            targeting_model_id="x:y",
            vision_model_id="x:y",
        )
        self.assertIn("# T", md)
        self.assertIn("No fused blocks", md)

    def test_blocks_sorted_by_time_and_mmss_format(self):
        md = format_markdown(
            title="Title",
            url="u",
            video_id="v",
            blocks=[
                FusedBlock(t=125.0, audio="a2", visual="v2", fused="f2"),
                FusedBlock(t=5.0, audio="a1", visual="v1", fused="f1"),
            ],
            targeting_model_id="tm",
            vision_model_id="vm",
        )
        # [00:05] must appear before [02:05]
        i1 = md.index("[00:05]")
        i2 = md.index("[02:05]")
        self.assertLess(i1, i2)

    def test_visual_omitted_when_none(self):
        md = format_markdown(
            title="T",
            url="u",
            video_id="v",
            blocks=[FusedBlock(t=1.0, audio="a", fused="f")],
            targeting_model_id="tm",
            vision_model_id="vm",
        )
        self.assertNotIn("VISUAL:", md)
        self.assertIn("AUDIO:", md)
        self.assertIn("FUSED:", md)


class TestHeaders(unittest.TestCase):
    def test_recommended_form_appears_when_set(self):
        md = format_markdown(
            title="T",
            url="u",
            video_id="v",
            blocks=[FusedBlock(t=1.0, audio="a", fused="f")],
            targeting_model_id="tm",
            vision_model_id="vm",
            recommended_form="skill",
            recommended_form_reason="teaches a reusable workflow",
        )
        self.assertIn("recommended-form:", md)
        self.assertIn("`skill`", md)
        self.assertIn("teaches a reusable workflow", md)

    def test_video_kind_renders_with_confidence(self):
        md = format_markdown(
            title="T",
            url="u",
            video_id="v",
            blocks=[],
            targeting_model_id="tm",
            vision_model_id="vm",
            video_kind="audio",
            video_kind_confidence=0.87,
            video_kind_reason="static podcast cover art",
        )
        self.assertIn("video-kind:", md)
        self.assertIn("`audio`", md)
        self.assertIn("0.87", md)

    def test_headers_omitted_when_none(self):
        md = format_markdown(
            title="T",
            url="u",
            video_id="v",
            blocks=[],
            targeting_model_id="tm",
            vision_model_id="vm",
        )
        self.assertNotIn("recommended-form:", md)
        self.assertNotIn("video-kind:", md)


if __name__ == "__main__":
    unittest.main()
