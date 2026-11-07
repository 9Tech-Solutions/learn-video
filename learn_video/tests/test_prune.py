import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learn_video import cache, ingest, keyframes, pipeline, vision
from learn_video.state import FusedBlock, Target


def _seed(root: Path, *, video: bool = True, transcript: bool = True, fused: bool = True) -> cache.CachePaths:
    paths = cache.CachePaths(root=root)
    paths.frames_dir.mkdir(parents=True, exist_ok=True)
    cache.write_meta(paths, {"duration_s": 120.0, "title": "t", "url": "u"})
    if video:
        paths.video.write_bytes(b"\0" * 4096)
        (root / "video.en.vtt").write_bytes(b"WEBVTT\n")
        (root / "video.en-orig.vtt").write_bytes(b"WEBVTT\n")
    if transcript:
        paths.transcript.write_text(json.dumps({"text": "hi", "segments": []}), encoding="utf-8")
    if fused:
        paths.fused.write_text("# notes\n", encoding="utf-8")
    return paths


class TestPruneMedia(unittest.TestCase):
    def test_removes_video_and_captions_keeps_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _seed(Path(tmp))
            freed = cache.prune_media(paths)
            self.assertEqual(freed, 4096 + 7 + 7)
            self.assertIsNone(cache.find_video(paths))
            self.assertEqual(list(paths.root.glob("video*.vtt")), [])
            self.assertTrue(paths.meta.exists())
            self.assertTrue(paths.transcript.exists())
            self.assertTrue(paths.fused.exists())
            self.assertTrue(paths.frames_dir.exists())

    def test_keeps_captions_until_transcript_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _seed(Path(tmp), transcript=False, fused=False)
            cache.prune_media(paths)
            self.assertIsNone(cache.find_video(paths))
            self.assertEqual(len(list(paths.root.glob("video*.vtt"))), 2)

    def test_prune_all_touches_only_dirs_with_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            _seed(fake_root / "a")
            _seed(fake_root / "b", video=False)
            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                touched, freed = cache.prune_all()
                entries = {e["video_id"]: e for e in cache.list_entries()}
            self.assertEqual(touched, 1)
            self.assertGreater(freed, 0)
            self.assertFalse(entries["a"]["has_video"])
            self.assertFalse(entries["b"]["has_video"])


class TestPruneNode(unittest.TestCase):
    def test_prunes_after_fuse_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                out = pipeline._prune_node({"video_id": "vid"})
            self.assertEqual(out, {"video_path": None})
            self.assertIsNone(cache.find_video(paths))

    def test_keep_video_flag_skips_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                out = pipeline._prune_node({"video_id": "vid", "keep_video": True})
            self.assertEqual(out, {})
            self.assertIsNotNone(cache.find_video(paths))

    def test_no_fused_means_no_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid", fused=False)
            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                pipeline._prune_node({"video_id": "vid"})
            self.assertIsNotNone(cache.find_video(paths))

    def test_graph_ends_with_prune(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph not installed")
        graph = pipeline.build_graph()
        nodes = graph.get_graph().nodes
        self.assertIn("prune", nodes)


class TestIngestCacheHitWithoutVideo(unittest.TestCase):
    def test_pruned_cache_still_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            _seed(fake_root / "abc12345XYZ", video=False)
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), \
                 mock.patch.object(ingest, "_probe_metadata", side_effect=AssertionError("network hit")):
                out = ingest.node({"url": "https://youtu.be/abc12345XYZ"})
            self.assertEqual(out["video_id"], "abc12345XYZ")
            self.assertIsNone(out["video_path"])
            self.assertEqual(out["duration_s"], 120.0)

    def test_fresh_bypasses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            _seed(fake_root / "abc12345XYZ")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), \
                 mock.patch.object(ingest, "_probe_metadata", side_effect=RuntimeError("probed")), \
                 self.assertRaises(RuntimeError):
                ingest.node({"url": "https://youtu.be/abc12345XYZ", "fresh": True})

    def test_no_orphan_dir_before_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            fake_root.mkdir()
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), \
                 mock.patch.object(ingest, "_probe_metadata", side_effect=RuntimeError("probed")), \
                 self.assertRaises(RuntimeError):
                ingest.node({"url": "https://tiktok.com/@u/video/7123456789"})
            self.assertEqual(list(fake_root.iterdir()), [])


class TestKeyframesWithoutVideo(unittest.TestCase):
    def test_cached_frames_need_no_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid", video=False)
            paths.frame(10.0).write_bytes(b"jpg")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), \
                 mock.patch.object(keyframes, "extract_frame", side_effect=AssertionError("ffmpeg ran")):
                out = keyframes.node({"video_id": "vid", "targets": [Target(t=10.0, why="x")], "video_path": None})
            self.assertEqual(len(out["frames"]), 1)

    def test_missing_frame_without_video_is_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            _seed(fake_root / "vid", video=False)
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), self.assertRaises(Exception) as ctx:
                keyframes.node({"video_id": "vid", "targets": [Target(t=10.0, why="x")], "video_path": None})
            self.assertIn("--fresh", str(ctx.exception))


class TestVisionCache(unittest.TestCase):
    def test_blocks_reused_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid", video=False)
            vision._store_blocks(paths, [FusedBlock(t=1.0, audio="a", fused="f")], "m:x")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root), \
                 mock.patch.object(vision.model_client, "build_chat_model", side_effect=AssertionError("model built")):
                per = vision.per_frame_node({"video_id": "vid", "frames": []})
                whole = vision.whole_video_node({"video_id": "vid", "video_path": None})
            self.assertEqual(per["vision_model_id"], "m:x")
            self.assertEqual(whole["fused_blocks"][0].fused, "f")

    def test_fresh_ignores_cached_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "learn-video"
            paths = _seed(fake_root / "vid", video=False)
            vision._store_blocks(paths, [FusedBlock(t=1.0, audio="a", fused="f")], "m:x")
            with mock.patch.object(cache, "CACHE_ROOT", fake_root):
                self.assertIsNone(vision._cached_blocks(paths, {"fresh": True}))


if __name__ == "__main__":
    unittest.main()
