import asyncio
import ipaddress
import os
import re
import shutil
import socket
import subprocess

import aiohttp

from settings import settings


# ASN hints identify observed networks, never retail products such as CN2 GIA.
BACKBONE_ASNS = {
    4134: "电信 163", 4809: "电信 CN2", 4837: "联通 169", 9929: "联通 9929",
    10099: "联通国际", 9808: "中国移动", 58453: "移动 CMI", 58807: "移动 CMIN2",
    2914: "NTT", 174: "Cogent",
}
# Core router addresses may have no public BGP origin: https://rdap.apnic.net/ip/59.43.0.0
# shortcut: curated network hints only; extend verified rules when more networks are needed.
BACKBONE_PREFIXES = {ipaddress.ip_network("59.43.0.0/16"): "电信 CN2"}


def parse_trace(output: str) -> list[tuple[int, list[str]]]:
    hops = []
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not match:
            continue
        addresses = []
        for token in match[2].split():
            try:
                address = str(ipaddress.ip_address(token.strip("[]()").split("%")[0]))
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
        if addresses or "*" in match[2]:
            hops.append((int(match[1]), addresses))
    return hops


class EntranceRouteProbe:
    """Share entrance traces and IP-to-ASN lookups within one refresh."""

    def __init__(self):
        self._routes = {}
        self._asns = {}
        self._trace_limit = asyncio.Semaphore(2)
        self._lookup_limit = asyncio.Semaphore(4)

    async def probe(self, host: str) -> dict:
        # Resolve separately from the tunnel: record the exact sampled address.
        try:
            try:
                target = str(ipaddress.ip_address(host))
            except ValueError:
                addresses = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM),
                    settings.API_TIMEOUT,
                )
                target = str(ipaddress.ip_address(addresses[0][4][0]))
        except (OSError, ValueError, IndexError, asyncio.TimeoutError):
            return {"route_status": "dns_failed"}
        if target not in self._routes:
            self._routes[target] = asyncio.create_task(self._probe_target(target))
        return await self._routes[target]

    async def _trace(self, target: str) -> tuple[str, str]:
        windows = os.name == "nt"
        tool = shutil.which("tracert" if windows else "traceroute")
        if not tool:
            return "", "missing_tool"
        family = "-6" if ":" in target else "-4"
        command = (
            [tool, "-d", family, "-h", str(settings.ROUTE_MAX_HOPS),
             "-w", str(int(settings.ROUTE_HOP_TIMEOUT * 1000)), target]
            if windows else
            [tool, "-n", family, "-m", str(settings.ROUTE_MAX_HOPS),
             "-q", "1", "-w", str(settings.ROUTE_HOP_TIMEOUT), target]
        )
        async with self._trace_limit:
            process = None
            reader = None
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if windows else {}),
            ))
            try:
                process = await asyncio.shield(spawn)
                reader = asyncio.create_task(process.communicate())
                try:
                    output, _ = await asyncio.wait_for(asyncio.shield(reader), settings.ROUTE_TIMEOUT)
                    status = "partial" if process.returncode == 0 else "failed"
                except asyncio.TimeoutError:
                    process.kill()
                    output, _ = await reader
                    status = "timeout"
                return output.decode("utf-8", errors="replace"), status
            finally:
                if process is None and not spawn.cancelled():
                    try:
                        process = await spawn
                    except OSError:
                        pass
                if process is not None:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                if reader is not None and not reader.done():
                    await reader

    async def _lookup_asns(self, address: str) -> list[int]:
        async with self._lookup_limit:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://stat.ripe.net/data/network-info/data.json",
                        params={"resource": address}, timeout=settings.API_TIMEOUT,
                    ) as response:
                        if response.status != 200:
                            return []
                        data = await response.json()
                        if data.get("status") != "ok":
                            return []
                        return [int(asn) for asn in data["data"]["asns"]]
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError, AttributeError):
                return []

    async def _asns_for(self, address: str) -> list[int]:
        if not ipaddress.ip_address(address).is_global:
            return []
        if address not in self._asns:
            self._asns[address] = asyncio.create_task(self._lookup_asns(address))
        return await self._asns[address]

    async def _probe_target(self, target: str) -> dict:
        try:
            output, status = await self._trace(target)
        except OSError:
            return {"route_target": target, "route_status": "failed"}
        hops = parse_trace(output)
        addresses = list(dict.fromkeys(ip for _, ips in hops for ip in ips))
        asns = dict(zip(addresses, await asyncio.gather(*(self._asns_for(ip) for ip in addresses))))
        lines, networks = [], {}
        for ttl, ips in hops:
            labels = []
            for ip in ips:
                evidence = []
                for asn in asns[ip]:
                    name = BACKBONE_ASNS.get(asn)
                    evidence.append(f"AS{asn}" + (f" {name}" if name else ""))
                    # A destination's own ASN is not evidence of transit through that network.
                    if ip != target and name:
                        networks.setdefault(name, f"{name} (AS{asn})")
                if not asns[ip]:
                    for prefix, name in BACKBONE_PREFIXES.items():
                        if ipaddress.ip_address(ip) in prefix:
                            evidence.append(f"{name} IP段 {prefix}")
                            if ip != target:
                                networks.setdefault(name, f"{name} (IP段 {prefix})")
                labels.append(ip + (f" [{' / '.join(evidence)}]" if evidence else ""))
            lines.append(f"{ttl}: " + (" | ".join(labels) or "*"))
        reached = target in addresses
        return {
            "route_target": target,
            "route_status": "completed" if reached else status,
            "trace_path": "\n".join(lines),
            "is_backbone": True if networks else None,
            "backbone_info": " / ".join(networks.values()),
        }
