import asyncio
import ipaddress
import json
import socket
import time
import urllib.parse
from dataclasses import replace

import aiohttp
from aiohttp_socks import ProxyConnector

from models import ApiVerdict, ProbeData, VlessNode
from module_profile import NodeProfileAggregator, ProfileAdapters
from settings import settings


class LightweightProbe:
    """Tunnel probes plus registry-driven IP-intelligence requests."""

    @staticmethod
    async def tcp_ping(ip: str, port: int, times: int | None = None) -> float:
        values = []
        for _ in range(times or settings.PROBE_TEST_TIMES):
            started = time.perf_counter()
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), settings.TCP_PING_TIMEOUT)
                writer.close(); await writer.wait_closed()
                values.append((time.perf_counter() - started) * 1000)
            except Exception:
                pass
        return sum(values) / len(values) if values else 9999.0

    @staticmethod
    async def resolve_probe_target_ip(host: str) -> str:
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            return next((str(info[4][0]) for info in infos if info[0] in {socket.AF_INET, socket.AF_INET6}), host)

    @staticmethod
    async def test_ttfb(socks5_url: str, target_url: str, times: int | None = None) -> float:
        values = []
        for _ in range(times or settings.PROBE_TEST_TIMES):
            started = time.perf_counter()
            try:
                connector = ProxyConnector.from_url(socks5_url, rdns=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(target_url, timeout=settings.TTFB_TIMEOUT) as response:
                        await response.read()
                        values.append((time.perf_counter() - started) * 1000)
            except Exception:
                pass
        return sum(values) / len(values) if values else 9999.0

    @staticmethod
    async def detect_ipv6(socks5_url: str) -> tuple[bool, str]:
        try:
            connector = ProxyConnector.from_url(socks5_url, rdns=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("https://api6.ipify.org?format=json", timeout=settings.API_TIMEOUT) as response:
                    data = await response.json()
                    return response.status == 200, str(data.get("ip", ""))
        except Exception:
            return False, ""

    @staticmethod
    async def trace_route(ip: str) -> tuple[str, bool, bool, str]:
        # Route analysis is auxiliary and intentionally cannot affect validity.
        return "", False, False, ""

    @staticmethod
    async def _fetch_exit_ip(socks5_url: str, endpoint: str) -> tuple[str, dict | None]:
        try:
            connector = ProxyConnector.from_url(socks5_url, rdns=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(endpoint, timeout=settings.API_TIMEOUT) as response:
                    if response.status != 200:
                        return "", None
                    text = await response.text()
                    try:
                        data = json.loads(text)
                    except (TypeError, ValueError):
                        data = None
                    if isinstance(data, dict):
                        return str(data.get("ip", "")), data
                    return text.strip(), None
        except Exception:
            return "", None

    @staticmethod
    async def _fetch_site(site: dict, ip: str) -> tuple[dict | None, str]:
        try:
            url = str(site["url_template"]).format(ip=urllib.parse.quote(ip, safe=""), key=urllib.parse.quote(str(site.get("api_key", "")), safe=""))
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as response:
                    if response.status == 429: return None, "rate_limited"
                    if response.status != 200: return None, "error"
                    data = await response.json(content_type=None)
                    return (data, "success") if isinstance(data, dict) else (None, "no_data")
        except asyncio.TimeoutError:
            return None, "timeout"
        except Exception:
            return None, "error"

    @staticmethod
    def _verdict_for_site(site: dict, data: dict | None, status: str, ip: str) -> ApiVerdict:
        adapter = getattr(ProfileAdapters, f"from_{site['provider']}", None)
        if status != "success" or not data or not adapter:
            return ApiVerdict(source=site.get("column_name", site["id"]), site_id=site["id"], status=status)
        try:
            verdict = adapter(data, ip) if site["provider"] == "proxycheck" else adapter(data)
            has_evidence = verdict.risk_score is not None or bool(verdict.risk_labels)
            return replace(verdict, source=site.get("column_name", site["id"]), site_id=site["id"], status="success" if has_evidence else "no_data")
        except Exception:
            return ApiVerdict(source=site.get("column_name", site["id"]), site_id=site["id"], status="error")

    @staticmethod
    async def run_probe(
        node: VlessNode,
        socks5_url: str,
        api_sites: list[dict] | None = None,
        *,
        probe_config: dict | None = None,
    ) -> ProbeData:
        from module_api_store import ApiStore

        if probe_config is None:
            probe_config = ApiStore.get_probe_config_snapshot() if api_sites is None else {
                "api_sites": api_sites,
                "exit_ip_endpoint": ApiStore.get_exit_ip_endpoint(),
            }
        tcp_task = asyncio.create_task(LightweightProbe.tcp_ping(node.server_ip, node.server_port))
        ttfb_task = asyncio.create_task(LightweightProbe.test_ttfb(socks5_url, settings.TTFB_TARGET_URL))
        trace_task = asyncio.create_task(LightweightProbe.trace_route(node.server_ip))
        ipv6_task = asyncio.create_task(LightweightProbe.detect_ipv6(socks5_url))
        actual_ip, exit_data = await LightweightProbe._fetch_exit_ip(socks5_url, probe_config["exit_ip_endpoint"])
        if not actual_ip:
            actual_ip = await LightweightProbe.resolve_probe_target_ip(node.server_ip)
        configured = probe_config["api_sites"]
        sites = [site for site in configured if site.get("enabled")]
        responses = await asyncio.gather(*(LightweightProbe._fetch_site(site, actual_ip) for site in sites)) if actual_ip else []
        verdicts = [LightweightProbe._verdict_for_site(site, data, status, actual_ip) for site, (data, status) in zip(sites, responses)]
        weights = {site.get("column_name", site["id"]): float(site.get("weight", 1)) for site in sites}
        profile = NodeProfileAggregator.aggregate(verdicts, weights)
        metadata = next((data for data, status in responses if status == "success" and data), exit_data or {})
        connection = metadata.get("connection") or metadata.get("company") or {}
        tcp, ttfb, trace, ipv6 = await asyncio.gather(tcp_task, ttfb_task, trace_task, ipv6_task)
        return ProbeData(
            tcp_ping_ms=tcp, ttfb_ms=ttfb, actual_ip=actual_ip,
            actual_geo=metadata.get("country_code") or metadata.get("country") or "Unknown",
            asn_org=connection.get("org") or connection.get("name") or "",
            trace_path=trace[0], is_detour=trace[1], is_backbone=trace[2], backbone_info=trace[3],
            profile=profile, ipv6_support=ipv6[0], actual_ipv6=ipv6[1],
        )
