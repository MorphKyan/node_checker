import tempfile
import unittest
from pathlib import Path

from module_runtime_settings import RuntimeSettings
from settings import settings


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = settings.RUNTIME_SETTINGS_PATH
        self.original_values = RuntimeSettings.get_editable()
        settings.RUNTIME_SETTINGS_PATH = str(Path(self.tmpdir.name, "runtime_settings.json"))

    def tearDown(self):
        settings.RUNTIME_SETTINGS_PATH = self.original_path
        for key, value in self.original_values.items():
            setattr(settings, key, value)
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

    def test_get_metadata_exposes_types_and_limits(self):
        metadata = RuntimeSettings.get_metadata()

        self.assertEqual(metadata["FILTER_CONCURRENCY"]["type"], "int")
        self.assertEqual(metadata["FILTER_CONCURRENCY"]["min"], 1)
        self.assertEqual(metadata["FILTER_CONCURRENCY"]["max"], 100)
        self.assertEqual(metadata["CACHE_ENABLED"]["type"], "bool")
        self.assertEqual(metadata["TTFB_TARGET_URL"]["type"], "str")
        self.assertEqual(metadata["TTFB_TARGET_URL"]["min_length"], 1)

    def test_apply_rejects_values_outside_runtime_limits(self):
        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"FILTER_CONCURRENCY": 0}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"SPEEDTEST_CONCURRENCY": 21}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"API_DEFAULT_SPEEDTEST_LIMIT": 101}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"PROBE_CACHE_TTL_SECONDS": 59}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"SUBSCRIPTION_MAX_M": 0}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"SPEEDTEST_MAX_M": 0}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH": 15}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH": 241}, persist=False)

        with self.assertRaises(ValueError):
            RuntimeSettings.apply({"TTFB_TARGET_URL": ""}, persist=False)

    def test_load_ignores_invalid_persisted_settings(self):
        Path(settings.RUNTIME_SETTINGS_PATH).write_text(
            '{"FILTER_CONCURRENCY": "bad"}',
            encoding="utf-8",
        )

        RuntimeSettings.load()

        self.assertEqual(settings.FILTER_CONCURRENCY, self.original_values["FILTER_CONCURRENCY"])

    def test_load_ignores_persisted_values_outside_runtime_limits(self):
        Path(settings.RUNTIME_SETTINGS_PATH).write_text(
            '{"FILTER_CONCURRENCY": 0}',
            encoding="utf-8",
        )

        RuntimeSettings.load()

        self.assertEqual(settings.FILTER_CONCURRENCY, self.original_values["FILTER_CONCURRENCY"])

    def test_apply_rejects_invalid_batch_without_partial_update(self):
        with self.assertRaises(ValueError):
            RuntimeSettings.apply(
                {
                    "FILTER_CONCURRENCY": 7,
                    "API_DEFAULT_SPEEDTEST_LIMIT": 101,
                },
                persist=False,
            )

        self.assertEqual(settings.FILTER_CONCURRENCY, self.original_values["FILTER_CONCURRENCY"])

    def test_load_rejects_invalid_batch_without_partial_update(self):
        Path(settings.RUNTIME_SETTINGS_PATH).write_text(
            '{"FILTER_CONCURRENCY": 7, "API_DEFAULT_SPEEDTEST_LIMIT": 101}',
            encoding="utf-8",
        )

        RuntimeSettings.load()

        self.assertEqual(settings.FILTER_CONCURRENCY, self.original_values["FILTER_CONCURRENCY"])


if __name__ == "__main__":
    unittest.main()
