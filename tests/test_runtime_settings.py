import tempfile
import unittest
from pathlib import Path

from module_runtime_settings import RuntimeSettings
from settings import settings


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = settings.RUNTIME_SETTINGS_PATH
        self.original_filter_concurrency = settings.FILTER_CONCURRENCY
        settings.RUNTIME_SETTINGS_PATH = str(Path(self.tmpdir.name, "runtime_settings.json"))

    def tearDown(self):
        settings.RUNTIME_SETTINGS_PATH = self.original_path
        settings.FILTER_CONCURRENCY = self.original_filter_concurrency
        self.tmpdir.cleanup()

    def test_apply_rejects_wrong_scalar_types(self):
        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"FILTER_CONCURRENCY": "10"}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"CACHE_ENABLED": 1}, persist=False)

    def test_apply_accepts_valid_editable_settings(self):
        updated = RuntimeSettings.apply({"FILTER_CONCURRENCY": 7}, persist=False)

        self.assertEqual(updated["FILTER_CONCURRENCY"], 7)
        self.assertEqual(settings.FILTER_CONCURRENCY, 7)

    def test_load_ignores_invalid_persisted_settings(self):
        Path(settings.RUNTIME_SETTINGS_PATH).write_text(
            '{"FILTER_CONCURRENCY": "bad"}',
            encoding="utf-8",
        )

        RuntimeSettings.load()

        self.assertEqual(settings.FILTER_CONCURRENCY, self.original_filter_concurrency)


if __name__ == "__main__":
    unittest.main()
