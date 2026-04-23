import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learn_video import cache


class TestCachePaths(unittest.TestCase):
    def test_derive_video_id_extracts_youtube_id(self):
        self.assertEqual(
            cache.derive_video_id("https://www.youtube.com/watch?v=abc12345XYZ"),
            "abc12345XYZ",
        )

    def test_derive_video_id_extracts_shorts_id(self):
        self.assertEqual(
            cache.derive_video_id("https://www.youtube.com/shorts/abcDEF12345"),
            "abcDEF12345",
        )

    def test_derive_video_id_extracts_youtu_be(self):
        self.assertEqual(
            cache.derive_video_id("https://youtu.be/xYz12345ABC"),
            "xYz12345ABC",
        )

    def test_derive_video_id_falls_back_to_hash(self):
        vid = cache.derive_video_id("https://tiktok.com/@u/video/7123456789")
        self.assertTrue("_" in vid)
        self.assertGreater(len(vid), 12)

    def test_paths_for_returns_expected_filenames(self):
        paths = cache.paths_for("abc12345XYZ")
        self.assertTrue(str(paths.meta).endswith("meta.json"))
        self.assertTrue(str(paths.transcript).endswith("transcript.json"))
        self.assertTrue(str(paths.targets).endswith("targets.json"))
        self.assertTrue(str(paths.fused).endswith("fused.md"))

    def test_frame_path_is_sortable(self):
        paths = cache.paths_for("abc")
        a = paths.frame(5.0).name
        b = paths.frame(12.5).name
        c = paths.frame(125.0).name
        self.assertLess(a, b)
        self.assertLess(b, c)  # lexicographic == chronological


class TestMetaRoundtrip(unittest.TestCase):
    def test_write_read_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = cache.CachePaths(root=root)
            cache.write_meta(paths, {"duration_s": 60.0, "tier": "lite"})
            self.assertEqual(cache.read_meta(paths)["duration_s"], 60.0)
            cache.update_meta(paths, new_field="hello")
            merged = cache.read_meta(paths)
            self.assertEqual(merged["tier"], "lite")
            self.assertEqual(merged["new_field"], "hello")

    def test_read_meta_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = cache.CachePaths(root=Path(tmp))
            self.assertEqual(cache.read_meta(paths), {})


class TestListEntriesAndClear(unittest.TestCase):
    def test_list_and_clear_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            fake_root.mkdir()
            (fake_root / "vid1").mkdir()
            (fake_root / "vid1" / "meta.json").write_text('{"a":1}')
            (fake_root / "vid2").mkdir()

            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                entries = cache.list_entries()
                self.assertEqual({e["video_id"] for e in entries}, {"vid1", "vid2"})
                self.assertTrue(cache.clear("vid1"))
                self.assertFalse(cache.clear("vid1"))  # gone
                self.assertEqual(cache.clear_all(), 1)  # only vid2 left


if __name__ == "__main__":
    unittest.main()
