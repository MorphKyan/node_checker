import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager

from models import AnalyzedNode, ProbeData, TestedNode, ProxyNode
from module_analyzer import NodeAnalyzer
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_parser import NodeParser
from module_probe import LightweightProbe
from module_setup import setup_core
from module_tunnel import TunnelController
from settings import settings


def get_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SubscriptionRefreshService:
    _running_tasks: dict[str, asyncio.Task] = {}

    _limit_loop = None
    _limits = {}

    @classmethod
    @asynccontextmanager
    async def limit(cls, setting: str):
        loop = asyncio.get_running_loop()
        if cls._limit_loop is not loop:
            cls._limit_loop, cls._limits = loop, {}
        if setting not in cls._limits:
            cls._limits[setting] = {"condition": asyncio.Condition(), "active": 0}
        state = cls._limits[setting]
        condition = state["condition"]
        async with condition:
            await condition.wait_for(lambda: state["active"] < max(1, int(getattr(settings, setting))))
            state["active"] += 1
        try:
            yield
        finally:
            async with condition:
                state["active"] -= 1
                condition.notify_all()

    @staticmethod
    def select_speedtest_nodes_per_region(
        analyzed_nodes: list[AnalyzedNode],
        speedtest_limit: int,
        coarse_results: list[TestedNode] | None = None,
    ) -> tuple[list[AnalyzedNode], list[AnalyzedNode]]:
        limit = max(0, int(speedtest_limit))
        speeds = {id(item.analyzed_node): item.download_speed_mbps for item in coarse_results or []}
        valid_nodes = [node for node in analyzed_nodes if node.is_valid and (coarse_results is None or speeds.get(id(node)) is not None)]
        invalid_nodes = [node for node in analyzed_nodes if not node.is_valid or (coarse_results is not None and speeds.get(id(node)) is None)]
        if limit <= 0:
            return [], valid_nodes + invalid_nodes

        nodes_by_region: dict[str, list[AnalyzedNode]] = {}
        for node in valid_nodes:
            region = node.probe.actual_geo or node.node.expected_geo or "Unknown"
            nodes_by_region.setdefault(region, []).append(node)

        nodes_to_test: list[AnalyzedNode] = []
        nodes_to_skip: list[AnalyzedNode] = []
        for region_nodes in nodes_by_region.values():
            region_nodes.sort(key=lambda node: (-(speeds.get(id(node)) or 0), node.probe.profile.risk_score is None, node.probe.profile.risk_score or 0, node.probe.ttfb_ms))
            nodes_to_test.extend(region_nodes[:limit])
            nodes_to_skip.extend(region_nodes[limit:])

        nodes_to_test.sort(key=lambda node: (node.probe.profile.risk_score is None, node.probe.profile.risk_score or 0, node.probe.ttfb_ms))
        nodes_to_skip.sort(key=lambda node: (node.probe.profile.risk_score is None, node.probe.profile.risk_score or 0, node.probe.ttfb_ms))
        nodes_to_skip.extend(invalid_nodes)
        return nodes_to_test, nodes_to_skip

    @staticmethod
    async def fetch_subscription_text(source: str) -> str:
        if NodeParser.is_http_source(source):
            return await NodeParser.fetch_subscription(source)
        if os.path.exists(source):
            max_bytes = max(1, int(settings.SUBSCRIPTION_MAX_M)) * 1024 * 1024
            if os.path.getsize(source) > max_bytes:
                raise ValueError(f"Subscription file exceeds {max_bytes} bytes")
            with open(source, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            if raw_text.startswith("http") and "\n" not in raw_text:
                return await NodeParser.fetch_subscription(raw_text)
            return raw_text
        raise FileNotFoundError(f"Subscription source not found: {source}")

    @staticmethod
    async def process_node_filter(
        node: ProxyNode,
        sem,
        *,
        force_probe: bool = False,
        api_sites: list[dict] | None = None,
        probe_config: dict | None = None,
    ) -> AnalyzedNode:
        # Direct callers must get the same immutable per-node snapshot as
        # run_nodes; otherwise cache lookup and the ensuing probe can observe
        # different site configurations.
        probe_config = ApiStore.get_probe_config_snapshot(probe_config, api_sites)
        async with sem:
            signature = ProbeCache.config_signature(probe_config=probe_config)
            process = None
            config_path = None
            try:
                if not force_probe:
                    try:
                        cached_probe = await ProbeCache.get(node, probe_config=probe_config)
                    except OSError as e:
                        print(f"[Cache Error] {node.remark}: {e}")
                        cached_probe = None
                    if cached_probe is not None:
                        print(f"[Cache Hit] {node.remark}")
                        return NodeAnalyzer.analyze(node, cached_probe)

                local_port = get_free_local_port()
                process, config_path = await TunnelController.start_tunnel(node, local_port)
                socks5_url = f"socks5://127.0.0.1:{local_port}"
                probe_data = await LightweightProbe.run_probe(node, socks5_url, probe_config=probe_config)
                try:
                    await ProbeCache.set(node, probe_data, probe_config=probe_config, expected_signature=signature)
                except OSError as e:
                    print(f"[Cache Error] {node.remark}: {e}")
                return NodeAnalyzer.analyze(node, probe_data)
            except Exception as e:
                print(f"[Filter Error] {node.remark}: {e}")
                probe = ProbeData(9999.0, 9999.0, "", "Unknown", "")
                return NodeAnalyzer.analyze(node, probe)
            finally:
                await TunnelController.stop_tunnel(process, config_path)

    @staticmethod
    async def run_speed_test(node_analyzed: AnalyzedNode, *, precise: bool = False) -> TestedNode:
        process = None
        config_path = None
        try:
            from module_speedtest import BandwidthTester

            local_port = get_free_local_port()
            process, config_path = await TunnelController.start_tunnel(node_analyzed.node, local_port)
            socks5_url = f"socks5://127.0.0.1:{local_port}"
            return await BandwidthTester.run_speed_test(node_analyzed, socks5_url, precise=precise)
        except Exception as e:
            print(f"[SpeedTest Tunnel Error] {node_analyzed.node.remark}: {e}")
            return TestedNode(node_analyzed, None, "failed")
        finally:
            await TunnelController.stop_tunnel(process, config_path)

    @classmethod
    async def run_nodes(
        cls,
        nodes: list[ProxyNode],
        *,
        speedtest_limit: int,
        force_probe: bool = False,
        progress_callback=None,
        api_sites: list[dict] | None = None,
        probe_config: dict | None = None,
    ) -> list[TestedNode]:
        # Freeze once for every caller (including CLI) before cache/probe work.
        probe_config = ApiStore.get_probe_config_snapshot(probe_config, api_sites)
        processed = 0

        async def filter_with_progress(node: ProxyNode) -> AnalyzedNode:
            nonlocal processed
            result = await cls.process_node_filter(node, cls.limit("FILTER_CONCURRENCY"), force_probe=force_probe, probe_config=probe_config)
            processed += 1
            if progress_callback:
                progress_callback("filter", processed, len(nodes))
            return result

        analyzed_nodes = await asyncio.gather(
            *(filter_with_progress(node) for node in nodes)
        )

        speed_processed = 0
        coarse_nodes = [node for node in analyzed_nodes if node.is_valid] if speedtest_limit > 0 else []
        speed_total = len(coarse_nodes)
        if progress_callback:
            progress_callback("speedtest", 0, speed_total)

        async def speed_with_progress(node: AnalyzedNode, *, precise: bool = False) -> TestedNode:
            nonlocal speed_processed
            async with cls.limit("SPEEDTEST_CONCURRENCY"):
                result = await cls.run_speed_test(node, precise=precise)
            speed_processed += 1
            if progress_callback:
                progress_callback("speedtest", speed_processed, speed_total)
            return result

        coarse_results = await asyncio.gather(*(speed_with_progress(node) for node in coarse_nodes))
        nodes_to_test, nodes_to_skip = cls.select_speedtest_nodes_per_region(
            analyzed_nodes, speedtest_limit, coarse_results if speedtest_limit > 0 else None,
        )
        speed_total += len(nodes_to_test)
        if progress_callback:
            progress_callback("speedtest", speed_processed, speed_total)
        tested_nodes = await asyncio.gather(*(speed_with_progress(node, precise=True) for node in nodes_to_test))
        tested_nodes.extend(TestedNode(node, None, "not_tested") for node in nodes_to_skip)
        return tested_nodes

    @classmethod
    async def run_subscription_refresh(
        cls,
        subscription_id: str,
        job_id: str,
        *,
        speedtest_limit: int,
        force_probe: bool = False,
    ) -> list[TestedNode]:
        await asyncio.to_thread(setup_core)
        subscription = ApiStore.get_subscription(subscription_id)
        if not subscription:
            raise ValueError(f"Subscription not found: {subscription_id}")
        subscription_url = subscription["url"]

        ApiStore.update_job(
            job_id,
            status="running",
            phase="fetch",
            started_at=int(time.time()),
        )

        raw_text = await cls.fetch_subscription_text(subscription["url"])
        nodes = NodeParser.parse_nodes(raw_text)
        if not nodes:
            raise ValueError("No valid proxy nodes found in subscription")

        ApiStore.update_job(job_id, phase="filter", total_nodes=len(nodes), processed_nodes=0)

        job = ApiStore.get_job(job_id)
        if not job:
            raise ValueError("Refresh job no longer exists")
        probe_config = job.get("probe_config_snapshot") or {
            "api_sites": job.get("api_sites_snapshot", []),
            "exit_ip_endpoint": job.get("exit_ip_endpoint_snapshot") or ApiStore.get_exit_ip_endpoint(),
        }

        def update_progress(phase: str, processed_nodes: int, total_nodes: int) -> None:
            ApiStore.update_job(
                job_id,
                phase=phase,
                processed_nodes=processed_nodes,
                total_nodes=total_nodes,
            )

        tested_nodes = await cls.run_nodes(
            nodes,
            speedtest_limit=speedtest_limit,
            force_probe=force_probe,
            progress_callback=update_progress,
            probe_config=probe_config,
        )
        if not ApiStore.save_results_if_current(
            subscription_id,
            job_id,
            subscription_url,
            tested_nodes,
        ):
            raise ValueError("Refresh job is no longer current; discarding results")
        return tested_nodes

    @classmethod
    async def run_job(cls, job_id: str) -> None:
        job = ApiStore.get_job(job_id)
        if not job:
            return
        try:
            await cls.run_subscription_refresh(
                job["subscription_id"],
                job_id,
                speedtest_limit=job["speedtest_limit"],
                force_probe=bool(job["force_probe"]),
            )
        except asyncio.CancelledError:
            ApiStore.cancel_job(job_id)
            raise
        except Exception as e:
            ApiStore.update_job(
                job_id,
                status="failed",
                phase="failed",
                error=str(e),
                finished_at=int(time.time()),
            )
        finally:
            cls._running_tasks.pop(job_id, None)

    @classmethod
    def schedule_refresh(
        cls,
        subscription_id: str,
        *,
        speedtest_limit: int | None = None,
        force_probe: bool = False,
    ) -> dict:
        subscription = ApiStore.get_subscription(subscription_id)
        if not subscription:
            raise KeyError(subscription_id)

        active_job = ApiStore.find_active_job(subscription_id)
        if active_job:
            return active_job

        limit = settings.API_DEFAULT_SPEEDTEST_LIMIT if speedtest_limit is None else speedtest_limit
        job = ApiStore.create_refresh_job(
            subscription_id,
            speedtest_limit=max(0, int(limit)),
            force_probe=force_probe,
            probe_config_snapshot=ApiStore.get_probe_config_snapshot(),
        )
        coro = cls.run_job(job["id"])
        try:
            task = asyncio.create_task(coro)
            cls._running_tasks[job["id"]] = task
        except RuntimeError as e:
            coro.close()
            ApiStore.update_job(
                job["id"],
                status="failed",
                phase="failed",
                error=f"Unable to schedule refresh task: {e}",
                finished_at=int(time.time()),
            )
            return ApiStore.get_job(job["id"])
        return job

    @classmethod
    def cancel_subscription_refreshes(cls, subscription_id: str) -> None:
        for job_id in list(cls._running_tasks):
            job = ApiStore.get_job(job_id)
            if job and job["subscription_id"] == subscription_id:
                cls.cancel_refresh(job_id)

    @classmethod
    def cancel_refresh(cls, job_id: str) -> dict | None:
        job = ApiStore.get_job(job_id)
        if not job:
            return None

        task = cls._running_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()

        canceled = ApiStore.cancel_job(job_id)
        return canceled or ApiStore.get_job(job_id)
