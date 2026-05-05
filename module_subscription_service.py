import asyncio
import os
import socket

from models import AnalyzedNode, ProbeData, TestedNode, VlessNode
from module_analyzer import NodeAnalyzer
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_parser import VlessParser
from module_probe import LightweightProbe
from module_setup import setup_singbox
from module_tunnel import TunnelController
from settings import settings


def get_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SubscriptionRefreshService:
    _running_tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    async def fetch_subscription_text(source: str) -> str:
        if VlessParser.is_http_source(source):
            return await VlessParser.fetch_subscription(source)
        if os.path.exists(source):
            max_bytes = max(1, int(settings.SUBSCRIPTION_MAX_BYTES))
            if os.path.getsize(source) > max_bytes:
                raise ValueError(f"Subscription file exceeds {max_bytes} bytes")
            with open(source, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            if raw_text.startswith("http") and "\n" not in raw_text:
                return await VlessParser.fetch_subscription(raw_text)
            return raw_text
        raise FileNotFoundError(f"Subscription source not found: {source}")

    @staticmethod
    async def process_node_filter(
        node: VlessNode,
        sem: asyncio.Semaphore,
        *,
        force_probe: bool = False,
    ) -> AnalyzedNode:
        async with sem:
            process = None
            config_path = None
            try:
                if not force_probe:
                    cached_probe = await ProbeCache.get(node)
                    if cached_probe is not None:
                        print(f"[Cache Hit] {node.remark}")
                        return NodeAnalyzer.analyze(node, cached_probe)

                local_port = get_free_local_port()
                process, config_path = await TunnelController.start_tunnel(node, local_port)
                socks5_url = f"socks5://127.0.0.1:{local_port}"
                probe_data = await LightweightProbe.run_probe(node, socks5_url)
                await ProbeCache.set(node, probe_data)
                return NodeAnalyzer.analyze(node, probe_data)
            except Exception as e:
                print(f"[Filter Error] {node.remark}: {e}")
                probe = ProbeData(9999.0, 9999.0, "", "Unknown", "", 0)
                return NodeAnalyzer.analyze(node, probe)
            finally:
                await TunnelController.stop_tunnel(process, config_path)

    @staticmethod
    async def run_speed_test(node_analyzed: AnalyzedNode) -> TestedNode:
        process = None
        config_path = None
        try:
            from module_speedtest import BandwidthTester

            local_port = get_free_local_port()
            process, config_path = await TunnelController.start_tunnel(node_analyzed.node, local_port)
            socks5_url = f"socks5://127.0.0.1:{local_port}"
            return await BandwidthTester.run_speed_test(node_analyzed, socks5_url)
        except Exception as e:
            print(f"[SpeedTest Tunnel Error] {node_analyzed.node.remark}: {e}")
            return TestedNode(node_analyzed, 0.0)
        finally:
            await TunnelController.stop_tunnel(process, config_path)

    @classmethod
    async def run_nodes(
        cls,
        nodes: list[VlessNode],
        *,
        speedtest_limit: int,
        force_probe: bool = False,
        progress_callback=None,
    ) -> list[TestedNode]:
        filter_sem = asyncio.Semaphore(settings.FILTER_CONCURRENCY)
        processed = 0

        async def filter_with_progress(node: VlessNode) -> AnalyzedNode:
            nonlocal processed
            result = await cls.process_node_filter(node, filter_sem, force_probe=force_probe)
            processed += 1
            if progress_callback:
                progress_callback("filter", processed, len(nodes))
            return result

        analyzed_nodes = await asyncio.gather(
            *(filter_with_progress(node) for node in nodes)
        )

        valid_nodes = [node for node in analyzed_nodes if node.is_valid]
        valid_nodes.sort(key=lambda node: node.total_score, reverse=True)

        tested_nodes: list[TestedNode] = []
        limit = max(0, int(speedtest_limit))
        nodes_to_test = valid_nodes[:limit]
        nodes_to_skip = valid_nodes[limit:] + [node for node in analyzed_nodes if not node.is_valid]

        if progress_callback:
            progress_callback("speedtest", 0, len(nodes_to_test))

        speed_processed = 0
        speed_sem = asyncio.Semaphore(max(1, int(settings.SPEEDTEST_CONCURRENCY)))

        async def speed_with_progress(node: AnalyzedNode) -> TestedNode:
            nonlocal speed_processed
            async with speed_sem:
                result = await cls.run_speed_test(node)
            speed_processed += 1
            if progress_callback:
                progress_callback("speedtest", speed_processed, len(nodes_to_test))
            return result

        if nodes_to_test:
            tested_nodes.extend(
                await asyncio.gather(*(speed_with_progress(node) for node in nodes_to_test))
            )

        tested_nodes.extend(TestedNode(node, 0.0) for node in nodes_to_skip)
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
        setup_singbox()
        await ProbeCache.init_db()
        subscription = ApiStore.get_subscription(subscription_id)
        if not subscription:
            raise ValueError(f"Subscription not found: {subscription_id}")
        subscription_url = subscription["url"]

        ApiStore.update_job(
            job_id,
            status="running",
            phase="fetch",
            started_at=ApiStore.now(),
        )

        raw_text = await cls.fetch_subscription_text(subscription["url"])
        nodes = VlessParser.parse_nodes(raw_text)
        if not nodes:
            raise ValueError("No valid VLESS nodes found in subscription")

        ApiStore.update_job(job_id, phase="filter", total_nodes=len(nodes), processed_nodes=0)

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
        except Exception as e:
            ApiStore.update_job(
                job_id,
                status="failed",
                phase="failed",
                error=str(e),
                finished_at=ApiStore.now(),
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
                finished_at=ApiStore.now(),
            )
            return ApiStore.get_job(job["id"])
        return job
