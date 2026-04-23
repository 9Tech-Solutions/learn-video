import unittest

from learn_video.state import FrameRef, FusedBlock, Target, TargetList, VisionInput


class TestStateSchemas(unittest.TestCase):
    def test_target_rejects_negative_time(self):
        with self.assertRaises(Exception):
            Target(t=-1.0, why="x")

    def test_target_requires_nonempty_why(self):
        with self.assertRaises(Exception):
            Target(t=5.0, why="")

    def test_target_list_roundtrip(self):
        tl = TargetList(
            targets=[
                Target(t=3.5, why="shows code"),
                Target(t=30.0, why="architecture diagram"),
            ]
        )
        payload = tl.model_dump()
        self.assertEqual(len(payload["targets"]), 2)
        again = TargetList.model_validate(payload)
        self.assertEqual(again.targets[0].why, "shows code")

    def test_frame_ref(self):
        fr = FrameRef(t=12.3, image_path="/tmp/x.jpg", transcript_window="hello")
        self.assertEqual(fr.t, 12.3)

    def test_fused_block_optional_visual(self):
        b = FusedBlock(t=1.0, audio="hi", fused="summary")
        self.assertIsNone(b.visual)

    def test_vision_input_defaults(self):
        vi = VisionInput(text="describe")
        self.assertIsNone(vi.image_b64)
        self.assertIsNone(vi.video_path)


if __name__ == "__main__":
    unittest.main()
