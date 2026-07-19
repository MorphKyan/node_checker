import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from models import ProbeData, VlessNode
from module_api_store import ApiStore
from module_node_identity import make_node_fingerprint, make_node_identity
from module_result_codec import restore_probe_data
from settings import settings


class ProbeCache:
    _write_lock = asyncio.Lock()

    @staticmethod
    def make_node_fingerprint(node: VlessNode) -> str:
        return make_node_fingerprint(node)

    @staticmethod
    def make_node_identity(node: VlessNode) -> str:
        return make_node_identity(node)

    @staticmethod
    def probe_config_snapshot(probe_config=None, api_sites=None) -> dict:
        if probe_config is not None:
            return probe_config
        if api_sites is None:
            return ApiStore.get_probe_config_snapshot()
        return {"api_sites": api_sites, "exit_ip_endpoint": ApiStore.get_exit_ip_endpoint()}

    @classmethod
    def config_signature(cls, api_sites=None, *, probe_config=None) -> str:
        snapshot = cls.probe_config_snapshot(probe_config, api_sites)
        payload = {"target": settings.TTFB_TARGET_URL, "times": settings.PROBE_TEST_TIMES, "ttfb_timeout": settings.TTFB_TIMEOUT, "api_timeout": settings.API_TIMEOUT, "exit_ip_endpoint": snapshot["exit_ip_endpoint"], "sites": snapshot["api_sites"]}
        # Keys must influence invalidation but never appear in paths or logs.
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]

    @classmethod
    def _path(cls, node: VlessNode, signature: str) -> Path:
        key = hashlib.sha256(f"{cls.make_node_fingerprint(node)}:{signature}".encode()).hexdigest()
        return ApiStore.data_dir() / "probe-cache" / f"{key}.json"

    @classmethod
    async def init_db(cls) -> None:
        (ApiStore.data_dir() / "probe-cache").mkdir(parents=True, exist_ok=True)

    @classmethod
    async def get(cls, node: VlessNode, api_sites=None, *, probe_config=None) -> ProbeData | None:
        if not settings.CACHE_ENABLED: return None
        snapshot = cls.probe_config_snapshot(probe_config, api_sites)
        path = cls._path(node, cls.config_signature(probe_config=snapshot))
        data = ApiStore._read_json(path)
        if not isinstance(data, dict) or data.get("expires_at", 0) < time.time():
            path.unlink(missing_ok=True)
            return None
        try:
            return restore_probe_data(data["probe"])
        except (KeyError, TypeError, ValueError):
            path.unlink(missing_ok=True)
            return None

    @classmethod
    async def set(cls, node: VlessNode, probe_data: ProbeData, api_sites=None, *, probe_config=None) -> None:
        if not settings.CACHE_ENABLED: return
        if not settings.CACHE_FAILURE_RESULTS and probe_data.ttfb_ms >= 9999.0: return
        snapshot = cls.probe_config_snapshot(probe_config, api_sites)
        signature = cls.config_signature(probe_config=snapshot)
        value = {"fingerprint": cls.make_node_fingerprint(node), "node_identity": cls.make_node_identity(node), "config_signature": signature, "created_at": int(time.time()), "expires_at": int(time.time()) + int(settings.PROBE_CACHE_TTL_SECONDS), "probe": asdict(probe_data)}
        async with cls._write_lock:
            ApiStore._atomic_write(cls._path(node, signature), value)
