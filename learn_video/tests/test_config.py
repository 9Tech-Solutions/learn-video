import os
import unittest
from unittest import mock

from learn_video import config


class TestPrecedence(unittest.TestCase):
    def test_tier_default_lite(self):
        loaded = config.LoadedConfig(
            tier_default="lite",
            model_overrides={},
            notes_only_default=False,
            rate_limits={},
            whisper={},
        )
        self.assertEqual(
            config.resolve_model_id(
                role="targeting", tier="lite", offline=False,
                model_override=None, loaded=loaded,
            ),
            "google_genai:gemini-flash-lite-latest",
        )
        self.assertEqual(
            config.resolve_model_id(
                role="vision", tier="max", offline=False,
                model_override=None, loaded=loaded,
            ),
            "anthropic:claude-opus-4-7",
        )

    def test_offline_beats_tier(self):
        loaded = config.LoadedConfig("lite", {}, False, {}, {})
        self.assertEqual(
            config.resolve_model_id(
                role="vision", tier="max", offline=True,
                model_override=None, loaded=loaded,
            ),
            "ollama:qwen2.5vl:3b",
        )

    def test_model_flag_overrides_everything_for_vision(self):
        loaded = config.LoadedConfig("lite", {"vision": "cfg-only"}, False, {}, {})
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_MODEL": "env-only"}):
            self.assertEqual(
                config.resolve_model_id(
                    role="vision", tier="lite", offline=False,
                    model_override="flag-wins", loaded=loaded,
                ),
                "flag-wins",
            )

    def test_env_var_beats_config_and_tier_for_vision(self):
        loaded = config.LoadedConfig("lite", {}, False, {}, {})
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_MODEL": "env-wins"}):
            self.assertEqual(
                config.resolve_model_id(
                    role="vision", tier="lite", offline=False,
                    model_override=None, loaded=loaded,
                ),
                "env-wins",
            )

    def test_config_toml_overrides_tier_default(self):
        loaded = config.LoadedConfig("lite", {"vision": "cfg-wins"}, False, {}, {})
        # Env not set:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                config.resolve_model_id(
                    role="vision", tier="lite", offline=False,
                    model_override=None, loaded=loaded,
                ),
                "cfg-wins",
            )

    def test_targeting_ignores_model_flag_and_env(self):
        """--model only rerouts vision; targeting stays cheap."""
        loaded = config.LoadedConfig("lite", {}, False, {}, {})
        with mock.patch.dict(os.environ, {"LEARN_VIDEO_MODEL": "env-should-not-apply"}):
            self.assertEqual(
                config.resolve_model_id(
                    role="targeting", tier="lite", offline=False,
                    model_override="flag-should-not-apply", loaded=loaded,
                ),
                "google_genai:gemini-flash-lite-latest",
            )


class TestShortPathTiers(unittest.TestCase):
    def test_short_path_only_lite_and_pro(self):
        self.assertIn("lite", config.SHORT_PATH_TIERS)
        self.assertIn("pro", config.SHORT_PATH_TIERS)
        self.assertNotIn("max", config.SHORT_PATH_TIERS)


if __name__ == "__main__":
    unittest.main()
