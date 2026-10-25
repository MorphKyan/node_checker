import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from models import ProbeData, ProxyNode
from module_api_store import ApiStore
from module_node_identity import make_node_fingerprint
from module_result_codec import restore_probe_data
from settings import settings


class ProbeCache:
    _write_lock = asyncio.Lock()

    @classmethod
    def config_signature(cls, api_sites=None, *, probe_config=None) -> str:
        snapshot = ApiStore.get_probe_config_snapshot(probe_config, api_sites)
        payload = {"version": 6, "core": settings.PROXY_CORE, "target": settings.TTFB_TARGET_URL, "times": settings.PROBE_TEST_TIMES, "ttfb_timeout": settings.TTFB_TIMEOUT, "api_timeout": settings.API_TIMEOUT, "route": [settings.ROUTE_TIMEOUT, settings.ROUTE_MAX_HOPS, settings.ROUTE_HOP_TIMEOUT], "exit_ip_endpoint": snapshot["exit_ip_endpoint"], "sites": snapshot["api_sites"]}
        # Keys must influence invalidation but never appear in paths or logs.
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]

    @classmethod
    def _path(cls, node: ProxyNode, signature: str) -> Path:
        key = hashlib.sha256(f"{make_node_fingerprint(node)}:{signature}".encode()).hexdigest()
        return Path(settings.DATA_DIR) / "probe-cache" / f"{key}.json"

    @classmethod
    async def get(cls, node: ProxyNode, api_sites=None, *, probe_config=None) -> ProbeData | None:
        if not settings.CACHE_ENABLED: return None
        snapshot = ApiStore.get_probe_config_snapshot(probe_config, api_sites)
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
    async def set(cls, node: ProxyNode, probe_data: ProbeData, api_sites=None, *, probe_config=None, expected_signature: str | None = None) -> None:
        if not settings.CACHE_ENABLED: return
        if not settings.CACHE_FAILURE_RESULTS and probe_data.ttfb_ms >= 9999.0: return
        snapshot = ApiStore.get_probe_config_snapshot(probe_config, api_sites)
        signature = cls.config_signature(probe_config=snapshot)
        if expected_signature is not None and expected_signature != signature:
            return
        value = {"fingerprint": make_node_fingerprint(node), "config_signature": signature, "created_at": int(time.time()), "expires_at": int(time.time()) + int(settings.PROBE_CACHE_TTL_SECONDS), "probe": asdict(probe_data)}
        async with cls._write_lock:
            if signature != cls.config_signature(probe_config=snapshot):
                return
            ApiStore._atomic_write(cls._path(node, signature), value)
