import asyncio
import zipfile
import tempfile
import threading
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from api_server import app, lifespan
import deploy
import main as cli
from models import AnalyzedNode, ProbeData, TestedNode, VlessNode
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_exporter import ResultExporter
from module_parser import NodeParser
from module_runtime_settings import RuntimeSettings
from module_subscription_service import SubscriptionRefreshService
from module_tunnel import TunnelController
from settings import settings


def sample_node():
    return VlessNode("vless://uuid@example.test:443#JP", "example.test", 443, "JP", "JP", uuid="uuid")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = patch.object(settings, "DATA_DIR", directory.name)
        data_dir.start()
        self.addCleanup(data_dir.stop)

    def test_site_ids_are_unique_after_trimming(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            ApiStore.create_api_site({"id": " netcoffee ", "column_name": "Duplicate",
                                      "provider": "netcoffee", "url_template": "https://example.test/{ip}"})
        self.assertEqual(len(ApiStore.get_api_sites()), 7)

    def test_site_weights_must_be_finite(self):
        for weight in (float("inf"), float("nan")):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                ApiStore.update_api_site("netcoffee", {"weight": weight})
        self.assertEqual(ApiStore.get_api_sites()[0]["weight"], 1)

    def test_failed_settings_save_does_not_change_running_settings(self):
        before = RuntimeSettings.get_editable()
        with patch.object(ApiStore, "save_runtime_settings", side_effect=OSError("disk full")):
            try:
                with self.assertRaises(OSError):
                    RuntimeSettings.apply({"FILTER_CONCURRENCY": before["FILTER_CONCURRENCY"] + 1})
                self.assertEqual(RuntimeSettings.get_editable(), before)
            finally:
                RuntimeSettings.apply(before, persist=False)

    def test_terminal_job_cannot_be_restarted_or_have_progress_overwritten(self):
        sub = ApiStore.create_subscription("https://example.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0)
        ApiStore.cancel_job(job["id"])
        ApiStore.update_job(job["id"], status="running", phase="filter", processed_nodes=2)
        canceled = ApiStore.get_job(job["id"])
        self.assertEqual(canceled["status"], "canceled")
        self.assertEqual(canceled["phase"], "canceled")
        self.assertEqual(canceled["processed_nodes"], 0)

    def test_report_export_preserves_unrelated_files(self):
        base = Path(settings.DATA_DIR, "reports")
        base.mkdir()
        (base / "notes.txt").write_text("keep me", encoding="utf-8")
        (base / "subscriptions").mkdir()
        subscription = base / "subscriptions" / "saved.txt"
        subscription.write_text("keep subscription", encoding="utf-8")
        item = TestedNode(AnalyzedNode(sample_node(), ProbeData(1, 2, "", "JP", ""), True))
        ResultExporter.export_markdown_report([item], str(base))
        self.assertEqual((base / "notes.txt").read_text(encoding="utf-8"), "keep me")
        self.assertEqual(subscription.read_text(encoding="utf-8"), "keep subscription")
        self.assertEqual(len(list((base / "node_details").glob("*.md"))), 1)
        ResultExporter.export_markdown_report([], str(base))
        self.assertEqual(list((base / "node_details").glob("*.md")), [])

    def test_report_filenames_support_control_characters_and_long_unicode(self):
        node = sample_node()
        node.remark = "name\x00\n" + "😀" * 100
        item = TestedNode(AnalyzedNode(node, ProbeData(1, 2, "", "JP", ""), True))
        ResultExporter.export_markdown_report([item], settings.DATA_DIR)
        paths = list(Path(settings.DATA_DIR, "node_details").glob("*.md"))
        self.assertEqual(len(paths), 1)
        self.assertLessEqual(len(paths[0].name.encode("utf-8")), 255)

    def test_canceled_job_is_removed_from_task_registry_when_it_starts(self):
        async def run():
            sub = ApiStore.create_subscription("https://example.test/sub")
            job = ApiStore.create_refresh_job(sub["id"], 0)
            ApiStore.cancel_job(job["id"])
            task = asyncio.create_task(SubscriptionRefreshService.run_job(job["id"]))
            SubscriptionRefreshService._running_tasks[job["id"]] = task
            await task
            self.assertNotIn(job["id"], SubscriptionRefreshService._running_tasks)
        asyncio.run(run())

    def test_custom_deployment_archive_does_not_include_itself(self):
        with chdir(settings.DATA_DIR):
            Path("source.py").write_text("print('example')", encoding="utf-8")
            deploy.create_archive("custom.zip")
            with zipfile.ZipFile("custom.zip") as archive:
                self.assertEqual(archive.namelist(), ["source.py"])

    def test_cli_uses_saved_core_setting_before_setup(self):
        observed = []
        ApiStore.save_runtime_settings({**RuntimeSettings.get_editable(), "PROXY_CORE": "xray"})
        with patch.object(settings, "PROXY_CORE", "sing-box"), \
             patch("builtins.input", return_value="example.txt"), \
             patch.object(cli, "setup_core", side_effect=lambda: observed.append(settings.PROXY_CORE)), \
             patch.object(SubscriptionRefreshService, "fetch_subscription_text", new=AsyncMock(return_value="")):
            asyncio.run(cli.main())
        self.assertEqual(observed, ["xray"])


class AsyncMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_shutdown_waits_for_running_job_cleanup(self):
        started, stopped = asyncio.Event(), asyncio.Event()

        async def refresh(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory), \
             patch.object(SubscriptionRefreshService, "run_subscription_refresh", side_effect=refresh):
            try:
                async with lifespan(app):
                    sub = ApiStore.create_subscription("https://example.test/sub")
                    job = SubscriptionRefreshService.schedule_refresh(sub["id"])
                    task = SubscriptionRefreshService._running_tasks[job["id"]]
                    await asyncio.wait_for(started.wait(), 1)
                self.assertTrue(stopped.is_set())
                self.assertEqual(ApiStore.get_job(job["id"])["status"], "canceled")
                self.assertNotIn(job["id"], SubscriptionRefreshService._running_tasks)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_core_command_resolves_custom_name_on_path(self):
        process = MagicMock(returncode=None)
        with patch.object(settings, "SING_BOX_PATH", "custom-core.exe"), \
             patch.object(settings, "PROXY_CORE", "sing-box"), \
             patch.object(settings, "TUNNEL_START_DELAY", 0), \
             patch.object(TunnelController, "generate_singbox_config", return_value="config.json"), \
             patch("module_tunnel.os.path.exists", return_value=False), \
             patch("shutil.which", return_value="C:/cores/custom-core.exe"), \
             patch("module_tunnel.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
            await TunnelController.start_tunnel(sample_node(), 10001)
            self.assertEqual(spawn.await_args.args[0], "C:/cores/custom-core.exe")

    async def test_exited_core_is_rejected_before_using_its_port(self):
        process = MagicMock(returncode=1)
        process.wait = AsyncMock()
        with patch.object(settings, "TUNNEL_START_DELAY", 0), \
             patch.object(settings, "PROXY_CORE", "sing-box"), \
             patch.object(TunnelController, "generate_singbox_config", return_value="config.json"), \
             patch("module_tunnel.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)), \
             patch.object(TunnelController, "stop_tunnel", new=AsyncMock()) as stop:
            with self.assertRaisesRegex(RuntimeError, "exited"):
                await TunnelController.start_tunnel(sample_node(), 10001)
            stop.assert_awaited_once_with(process, "config.json")

    async def test_malformed_cache_expiration_is_a_cache_miss(self):
        node = sample_node()
        config = {"api_sites": [], "exit_ip_endpoint": "https://exit.test"}
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory):
            for expires_at in (None, "later", [], float("nan")):
                with self.subTest(expires_at=expires_at):
                    path = ProbeCache._path(node, ProbeCache.config_signature(probe_config=config))
                    ApiStore._atomic_write(path, {"expires_at": expires_at, "probe": {}})
                    self.assertIsNone(await ProbeCache.get(node, probe_config=config))
                    self.assertFalse(path.exists())

    async def test_url_change_during_setup_discards_job_before_fetch(self):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()

        def setup():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(2):
                raise AssertionError("setup was not released")

        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory):
            sub = ApiStore.create_subscription("https://old.test/sub")
            job = ApiStore.create_refresh_job(sub["id"], 0)
            with patch("module_subscription_service.setup_core", side_effect=setup), \
                 patch.object(SubscriptionRefreshService, "fetch_subscription_text", new=AsyncMock(return_value="")) as fetch:
                task = asyncio.create_task(SubscriptionRefreshService.run_job(job["id"]))
                try:
                    await asyncio.wait_for(started.wait(), 1)
                    ApiStore.update_subscription(sub["id"], url="https://new.test/sub")
                finally:
                    release.set()
                    await task
                fetch.assert_not_called()
                self.assertEqual(ApiStore.get_job(job["id"])["status"], "failed")

    async def test_progress_failure_waits_for_other_nodes_to_stop(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        node = sample_node()

        async def probe(current, *args, **kwargs):
            if current is node:
                await started.wait()
                return AnalyzedNode(current, ProbeData(1, 2, "", "JP", ""), True)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        def progress(*args):
            raise OSError("disk full")

        with patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=probe):
            with self.assertRaisesRegex(OSError, "disk full"):
                await SubscriptionRefreshService.run_nodes(
                    [node, sample_node()], speedtest_limit=0, progress_callback=progress,
                    probe_config={"api_sites": [], "exit_ip_endpoint": "https://exit.test"},
                )
            self.assertTrue(stopped.is_set(), "a failed refresh left another node running")
