import unittest

from console_encoding import configure_stream


class FakeStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


class BrokenStream:
    def reconfigure(self, **kwargs):
        raise ValueError("closed stream")


class ConsoleEncodingTests(unittest.TestCase):
    def test_configure_stream_uses_utf8_replace_errors(self):
        stream = FakeStream()

        configure_stream(stream)

        self.assertEqual(stream.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_configure_stream_ignores_unavailable_or_closed_streams(self):
        configure_stream(None)
        configure_stream(BrokenStream())


if __name__ == "__main__":
    unittest.main()
