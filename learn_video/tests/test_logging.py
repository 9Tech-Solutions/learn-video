import io
import unittest
from contextlib import redirect_stderr

from learn_video import logging_


class TestLogging(unittest.TestCase):
    def test_emit_uses_stage_index(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            logging_.emit("TARGETING", "doing stuff")
        self.assertIn("[3/6 TARGETING]", buf.getvalue())

    def test_emit_unknown_stage_falls_back(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            logging_.emit("UNKNOWN", "hello")
        self.assertIn("[UNKNOWN]", buf.getvalue())

    def test_fatal_includes_fix_hint(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            logging_.fatal("bad thing", fix_hint="do the fix")
        text = buf.getvalue()
        self.assertIn("[FATAL]", text)
        self.assertIn("do the fix", text)


if __name__ == "__main__":
    unittest.main()
