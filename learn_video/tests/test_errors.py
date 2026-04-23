import unittest

from learn_video.errors import (
    ConfigurationError,
    EnvironmentError_,
    LearnVideoError,
    TargetError,
    TransientError,
)


class TestErrorTaxonomy(unittest.TestCase):
    def test_all_inherit_base(self):
        for cls in (
            TransientError,
            ConfigurationError,
            EnvironmentError_,
            TargetError,
        ):
            self.assertTrue(issubclass(cls, LearnVideoError))

    def test_configuration_carries_fix_hint(self):
        err = ConfigurationError("missing X", fix_hint="export X=...")
        self.assertEqual(err.fix_hint, "export X=...")
        self.assertEqual(str(err), "missing X")

    def test_environment_carries_install_cmd(self):
        err = EnvironmentError_("need Y", install_cmd="apt install y")
        self.assertEqual(err.install_cmd, "apt install y")

    def test_transient_and_target_are_distinct(self):
        with self.assertRaises(TransientError):
            raise TransientError("429")
        with self.assertRaises(TargetError):
            raise TargetError("DRM")


if __name__ == "__main__":
    unittest.main()
