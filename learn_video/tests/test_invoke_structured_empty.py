import unittest
from unittest import mock

from learn_video import model_client
from learn_video.state import TargetList


class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeModel:
    """Minimal stand-in for a LangChain chat model. We make the structured
    path explode so the fallback kicks in, then control what raw ``invoke``
    returns."""

    def __init__(self, raw_content):
        self._raw_content = raw_content
        self._lv_model_id = ""

    def with_structured_output(self, schema):
        def boom(messages):
            raise RuntimeError("no structured output here")
        inner = mock.Mock()
        inner.invoke.side_effect = boom
        return inner

    def invoke(self, messages):
        return _FakeMessage(self._raw_content)


class TestInvokeStructuredEmptyResponses(unittest.TestCase):
    def setUp(self):
        model_client._reset_rate_limiter()

    def test_empty_string_returns_default_for_schema_with_defaults(self):
        m = _FakeModel("")
        result = model_client.invoke_structured(m, TargetList, [])
        self.assertEqual(result.targets, [])

    def test_whitespace_only_returns_default(self):
        m = _FakeModel("   \n  ")
        result = model_client.invoke_structured(m, TargetList, [])
        self.assertEqual(result.targets, [])

    def test_unparseable_text_returns_default(self):
        m = _FakeModel("this is not JSON at all and has no braces")
        result = model_client.invoke_structured(m, TargetList, [])
        self.assertEqual(result.targets, [])

    def test_valid_json_array_parses(self):
        m = _FakeModel('{"targets": [{"t": 10, "why": "see code"}]}')
        result = model_client.invoke_structured(m, TargetList, [])
        self.assertEqual(len(result.targets), 1)
        self.assertEqual(result.targets[0].why, "see code")


if __name__ == "__main__":
    unittest.main()
