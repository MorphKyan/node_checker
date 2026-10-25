import asyncio
import ipaddress
import json
import time
import urllib.parse
from dataclasses import replace

import aiohttp
from aiohttp_socks import ProxyConnector

from models import ApiVerdict, NodeProfile, ProbeData, ProxyNode
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
    async def test_ttfb(socks5_url: str, target_url: str, times: int | None = None) -> float:
        values = []
        for _ in range(times or settings.PROBE_TEST_TIMES):
            started = time.perf_counter()
            try:
                connector = ProxyConnector.from_url(socks5_url, rdns=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(target_url, timeout=settings.TTFB_TIMEOUT) as response:
                        await response.content.read(1)
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
    async def _fetch_exit_ip(socks5_url: str, endpoint: str) -> tuple[str, dict | None]:
        for attempt in range(2):
            try:
                connector = ProxyConnector.from_url(socks5_url, rdns=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(endpoint, timeout=settings.API_TIMEOUT) as response:
                        if response.status >= 500 and attempt == 0:
                            continue
                        if response.status != 200:
                            return "", None
                        text = await response.text()
                        try:
                            data = json.loads(text)
                        except (TypeError, ValueError):
                            data = None
                        if isinstance(data, dict):
                            if data.get("error") or data.get("success") is False:
                                return "", None
                            return str(ipaddress.ip_address(data.get("ip", ""))), data
                        return str(ipaddress.ip_address(text.strip())), None
            except Exception:
                if attempt == 1:
                    return "", None

    @staticmethod
    async def _fetch_site(site: dict, ip: str, socks5_url: str) -> tuple[dict | None, str]:
        for attempt in range(2):
            try:
                url = str(site["url_template"]).format(ip=urllib.parse.quote(ip, safe=""), key=urllib.parse.quote(str(site.get("api_key", "")), safe=""))
                connector = ProxyConnector.from_url(socks5_url, rdns=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(url, timeout=settings.API_TIMEOUT) as response:
                        if response.status == 429: return None, "rate_limited"
                        if response.status >= 500 and attempt == 0:
                            continue
                        if response.status != 200: return None, "error"
                        data = await response.json(content_type=None)
                        return (data, "success") if isinstance(data, dict) else (None, "no_data")
            except asyncio.TimeoutError:
                if attempt == 1:
                    return None, "timeout"
            except Exception:
                if attempt == 1:
                    return None, "error"

    @staticmethod
    def _verdict_for_site(site: dict, data: dict | None, status: str, ip: str) -> ApiVerdict:
        adapter = getattr(ProfileAdapters, f"from_{site['provider']}", None)
        if status != "success" or not data or not adapter:
            return ApiVerdict(source=site.get("column_name", site["id"]), site_id=site["id"], status=status if status != "success" else "no_data")
        try:
            verdict = adapter(data, ip) if site["provider"] == "proxycheck" else adapter(data)
            has_evidence = verdict.risk_score is not None or bool(verdict.risk_labels)
            return replace(verdict, source=site.get("column_name", site["id"]), site_id=site["id"], status="success" if has_evidence else "no_data")
        except Exception:
            return ApiVerdict(source=site.get("column_name", site["id"]), site_id=site["id"], status="error")

    @staticmethod
    async def _ip_intelligence(socks5_url: str, probe_config: dict):
        actual_ip, exit_data = await LightweightProbe._fetch_exit_ip(socks5_url, probe_config["exit_ip_endpoint"])
        sites = [site for site in probe_config["api_sites"] if site.get("enabled")]
        responses = (
            await asyncio.gather(*(LightweightProbe._fetch_site(site, actual_ip, socks5_url) for site in sites))
            if actual_ip else [(None, "no_data")] * len(sites)
        )
        verdicts = [LightweightProbe._verdict_for_site(site, data, status, actual_ip) for site, (data, status) in zip(sites, responses)]
        weights = {site["id"]: float(site.get("weight", 1)) for site in sites}
        primary = next((verdict for site, verdict in zip(sites, verdicts)
                        if site["provider"] == "netcoffee" and (verdict.status == "success" or verdict.network_labels)), None)
        profile = NodeProfileAggregator.aggregate(verdicts, weights, primary=primary)
        geo, asn = "Unknown", ""
        primary_data = [data for site, (data, status) in zip(sites, responses)
                        if site["provider"] == "netcoffee" and status == "success"]
        for data in primary_data + [exit_data] + [data for data, status in responses if status == "success"]:
            if not isinstance(data, dict) or data.get("error") or data.get("success") is False:
                continue
            country = data.get("country_code") or data.get("countryCode") or data.get("country")
            if geo == "Unknown" and isinstance(country, str) and len(country) == 2 and country.isalpha():
                geo = country.upper()
            if not asn and isinstance(data.get("asOrganization"), str):
                asn = data["asOrganization"]
            for key in ("connection", "company", "asn"):
                connection = data.get(key)
                if isinstance(connection, dict):
                    organization = connection.get("org") or connection.get("name")
                    if not asn and isinstance(organization, str):
                        asn = organization
        return actual_ip, geo, asn, profile

    @staticmethod
    async def run_probe(
        node: ProxyNode,
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
        tcp, ttfb, ipv6, intelligence = await asyncio.gather(
            LightweightProbe.tcp_ping(node.server_ip, node.server_port),
            LightweightProbe.test_ttfb(socks5_url, settings.TTFB_TARGET_URL),
            LightweightProbe.detect_ipv6(socks5_url),
            LightweightProbe._ip_intelligence(socks5_url, probe_config),
            return_exceptions=True,
        )
        if isinstance(tcp, BaseException): tcp = 9999.0
        if isinstance(ttfb, BaseException): ttfb = 9999.0
        if isinstance(ipv6, BaseException): ipv6 = (False, "")
        if isinstance(intelligence, BaseException): intelligence = ("", "Unknown", "", NodeProfile())
        actual_ip, geo, asn, profile = intelligence
        return ProbeData(
            tcp_ping_ms=tcp, ttfb_ms=ttfb, actual_ip=actual_ip,
            actual_geo=geo, asn_org=asn,
            # shortcut: route measurement is not implemented; keep unknown defaults until it is.
            profile=profile, ipv6_support=ipv6[0], actual_ipv6=ipv6[1],
        )
