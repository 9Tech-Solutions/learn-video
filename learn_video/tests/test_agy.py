import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from learn_video import agy, cache, cli, config, pipeline
from learn_video.errors import ConfigurationError, TransientError
from learn_video.state import PipelineState

NOTES = {
    "video_kind": "visual",
    "video_kind_confidence": 0.9,
    "video_kind_reason": "code on screen",
    "recommended_form": "skill",
    "recommended_form_reason": "step by step workflow",
    "blocks": [
        {"t": 65, "audio": "second", "visual": "terminal", "fused": "runs the build"},
        {"t": 5, "audio": "first", "visual": "", "fused": "opens the app"},
    ],
}


def _envelope(**overrides):
    env = {"status": "SUCCESS", "response": json.dumps(NOTES), "structured_output": NOTES}
    env.update(overrides)
    return json.dumps(env)


def _args(**overrides):
    base = dict(no_agy=False, offline=False, model=None, tier=None)
    base.update(overrides)
    return argparse.Namespace(**base)


class TestFindAgy(unittest.TestCase):
    def test_env_switch_turns_agy_off(self):
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_AGY": "off"}), \
             mock.patch("shutil.which", return_value="C:/agy.exe"):
            self.assertIsNone(agy.find_agy())

    def test_found_on_path(self):
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_AGY": ""}), \
             mock.patch("shutil.which", return_value="C:/agy.exe"):
            self.assertEqual(agy.find_agy(), "C:/agy.exe")

    def test_model_precedence(self):
        loaded = config.LoadedConfig("lite", {}, False, {}, {}, agy={"model": "gemini-3.8-flash-high"})
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_AGY_MODEL": ""}):
            self.assertEqual(agy.agy_model(loaded), "gemini-3.8-flash-high")
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_AGY_MODEL": "x-model"}):
            self.assertEqual(agy.agy_model(loaded), "x-model")
        empty = config.LoadedConfig("lite", {}, False, {}, {})
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_AGY_MODEL": ""}):
            self.assertEqual(agy.agy_model(empty), agy.DEFAULT_MODEL)


class TestParseOutput(unittest.TestCase):
    def test_structured_output(self):
        notes = agy.parse_output(_envelope())
        self.assertEqual(notes.recommended_form, "skill")
        self.assertEqual(len(notes.blocks), 2)

    def test_falls_back_to_fenced_response(self):
        out = _envelope(structured_output=None, response="```json\n" + json.dumps(NOTES) + "\n```")
        self.assertEqual(agy.parse_output(out).video_kind, "visual")

    def test_cannot_view(self):
        with self.assertRaises(TransientError):
            agy.parse_output(_envelope(structured_output=None, response="CANNOT_VIEW_VIDEO"))

    def test_failed_status(self):
        with self.assertRaises(TransientError):
            agy.parse_output(_envelope(status="ERROR"))

    def test_no_verdict(self):
        with self.assertRaises(TransientError):
            agy.parse_output(json.dumps({"status": "SUCCESS", "response": ""}))

    def test_schema_violation(self):
        bad = dict(NOTES, recommended_form="essay")
        with self.assertRaises(TransientError):
            agy.parse_output(_envelope(structured_output=bad))


class TestCommandAndSizing(unittest.TestCase):
    def test_command_is_sandboxed_read_only_json(self):
        cmd = agy.build_command("agy", "p", model="m", workdir=Path("w"), minutes=20, schema_path=Path("s.json"))
        for flag in ("--sandbox", "--output-format", "--json-schema", "--add-dir"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--mode") + 1], "plan")
        self.assertEqual(cmd[cmd.index("--print-timeout") + 1], "20m")

    def test_block_count_and_timeout_bounds(self):
        self.assertEqual(agy.target_block_count(10), 6)
        self.assertEqual(agy.target_block_count(20 * 60), 30)
        self.assertEqual(agy.target_block_count(3 * 3600), 40)
        self.assertEqual(agy.timeout_minutes(30), 15)
        self.assertEqual(agy.timeout_minutes(5 * 3600), 60)

    def test_small_video_is_used_as_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = cache.CachePaths(root=Path(tmp))
            video = Path(tmp) / "video.mp4"
            video.write_bytes(b"\0" * 1024)
            with mock.patch.object(agy, "make_proxy") as proxy:
                self.assertEqual(agy.prepare_input(paths, video, 60.0), video)
                proxy.assert_not_called()

    def test_big_video_gets_a_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = cache.CachePaths(root=Path(tmp))
            video = Path(tmp) / "video.mp4"
            video.write_bytes(b"\0" * 1024)
            with mock.patch.object(agy, "AGY_MAX_BYTES", 10), \
                 mock.patch.object(agy, "make_proxy", return_value=Path(tmp) / "agy_input.mp4") as proxy:
                self.assertEqual(agy.prepare_input(paths, video, 60.0).name, "agy_input.mp4")
                proxy.assert_called_once()


class TestNode(unittest.TestCase):
    def _seed(self, root: Path) -> cache.CachePaths:
        paths = cache.CachePaths(root=root / "vid")
        paths.root.mkdir(parents=True)
        paths.video.write_bytes(b"\0" * 2048)
        segs = [{"start": 3.0, "end": 5.0, "text": "hello"}]
        paths.transcript.write_text(json.dumps({"text": "hello", "segments": segs}), encoding="utf-8")
        cache.write_meta(paths, {"duration_s": 90.0})
        return paths

    def _state(self, paths: cache.CachePaths, **extra):
        state = {"video_id": "vid", "video_path": str(paths.video), "duration_s": 90.0, "title": "T"}
        state.update(extra)
        return state

    def test_runs_agy_and_stores_notes(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cache, "CACHE_ROOT", Path(tmp)), \
             mock.patch.object(agy, "find_agy", return_value="agy"), \
             mock.patch.object(agy, "agy_model", return_value="gemini-4-argon-high"):
            paths = self._seed(Path(tmp))
            seen = {}

            def fake_run(cmd, *, workdir, minutes):
                seen["cmd"], seen["files"] = cmd, sorted(p.name for p in workdir.iterdir())
                return _envelope()

            with mock.patch.object(agy, "run_agy", side_effect=fake_run):
                out = agy.node(self._state(paths))
            self.assertEqual([b.t for b in out["fused_blocks"]], [5, 65])
            self.assertEqual(out["vision_model_id"], "agy:gemini-4-argon-high")
            self.assertIn("agy_transcript.txt", seen["files"])
            self.assertIn("video.mp4", seen["cmd"][2])
            meta = cache.read_meta(paths)
            self.assertEqual(meta["engine"], "agy")
            self.assertEqual(len(meta["vision_blocks"]), 2)
            self.assertFalse((paths.root / "agy_transcript.txt").exists())
            self.assertFalse((paths.root / "agy_schema.json").exists())

    def test_cache_hit_skips_agy(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cache, "CACHE_ROOT", Path(tmp)):
            paths = self._seed(Path(tmp))
            block = {"t": 1.0, "audio": "a", "visual": None, "fused": "f"}
            cache.update_meta(paths, vision_blocks=[block], recommended_form="tip", video_kind="audio")
            with mock.patch.object(agy, "run_agy") as run:
                out = agy.node(self._state(paths))
                run.assert_not_called()
            self.assertEqual(out["recommended_form"], "tip")

    def test_pruned_media_needs_fresh(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cache, "CACHE_ROOT", Path(tmp)), \
             mock.patch.object(agy, "find_agy", return_value="agy"):
            paths = self._seed(Path(tmp))
            paths.video.unlink()
            with self.assertRaises(ConfigurationError):
                agy.node(self._state(paths))

    def test_temp_files_removed_when_agy_fails(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cache, "CACHE_ROOT", Path(tmp)), \
             mock.patch.object(agy, "find_agy", return_value="agy"), \
             mock.patch.object(agy, "run_agy", side_effect=TransientError("boom")):
            paths = self._seed(Path(tmp))
            with self.assertRaises(TransientError):
                agy.node(self._state(paths))
            self.assertEqual(sorted(p.name for p in paths.root.glob("agy_*")), [])


class TestRouting(unittest.TestCase):
    def test_engine_router(self):
        self.assertEqual(pipeline._engine_router({"engine": "agy"}), "agy_watch")
        self.assertEqual(pipeline._engine_router({"engine": "api"}), "probe_short")
        self.assertEqual(pipeline._engine_router({}), "probe_short")

    def test_pick_engine(self):
        with mock.patch.object(agy, "find_agy", return_value="agy"):
            self.assertEqual(cli._pick_engine(_args()), "agy")
            for flag in ({"no_agy": True}, {"offline": True}, {"model": "x:y"}, {"tier": "pro"}):
                self.assertEqual(cli._pick_engine(_args(**flag)), "api", flag)
        with mock.patch.object(agy, "find_agy", return_value=None):
            self.assertEqual(cli._pick_engine(_args()), "api")

    def test_missing_key_on_api_route_fails_before_download(self):
        loaded = config.LoadedConfig("lite", {}, False, {}, {})
        state = cast(PipelineState, {"engine": "api", "offline": False, "tier": "lite", "model_override": None})
        no_keys = {"GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""}
        with mock.patch.dict(os.environ, no_keys), self.assertRaises(ConfigurationError) as ctx:
            cli._require_api_keys(state, loaded)
        self.assertIn("NO_AGY_NO_API_KEY", str(ctx.exception))

    def test_agy_route_needs_no_key(self):
        loaded = config.LoadedConfig("lite", {}, False, {}, {})
        state = cast(PipelineState, {"engine": "agy", "offline": False, "tier": "lite", "model_override": None})
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""}):
            cli._require_api_keys(state, loaded)

    def test_gemini_api_version_default_keeps_explicit_value(self):
        with mock.patch.dict(os.environ, {"GOOGLE_GENAI_API_VERSION": "v1"}):
            cli._default_gemini_api_version()
            self.assertEqual(os.environ["GOOGLE_GENAI_API_VERSION"], "v1")
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_GENAI_API_VERSION"}
        with mock.patch.dict(os.environ, env, clear=True):
            cli._default_gemini_api_version()
            self.assertEqual(os.environ["GOOGLE_GENAI_API_VERSION"], "v1beta")


if __name__ == "__main__":
    unittest.main()
