import asyncio
import time
from httpx_socks import AsyncProxyTransport
import httpx
from models import AnalyzedNode, TestedNode
from settings import settings

class BandwidthTester:
    @staticmethod
    def bytes_to_count(downloaded_bytes: int, chunk_size: int, max_bytes: int) -> int:
        remaining = max(0, max_bytes - downloaded_bytes)
        return min(chunk_size, remaining)

    @staticmethod
    async def run_speed_test(analyzed_node: AnalyzedNode, socks5_url: str) -> TestedNode:
        download_speed_mbps = 0.0
        transport = AsyncProxyTransport.from_url(socks5_url)
        start_time = time.perf_counter()
        downloaded_bytes = 0
        max_bytes = max(1, int(settings.SPEEDTEST_MAX_M)) * 1024 * 1024
        
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            # Disable http2 as it often causes RemoteProtocolError with some proxies/CDNs
            async with httpx.AsyncClient(transport=transport, headers=headers, http2=False, follow_redirects=True) as client:
                async with client.stream("GET", settings.SPEEDTEST_URL, timeout=settings.SPEEDTEST_TIMEOUT) as resp:
                    resp.raise_for_status()
                    
                    try:
                        async for chunk in resp.aiter_bytes(chunk_size=131072): # Larger chunk size
                            counted_bytes = BandwidthTester.bytes_to_count(
                                downloaded_bytes,
                                len(chunk),
                                max_bytes,
                            )
                            downloaded_bytes += counted_bytes
                            elapsed = time.perf_counter() - start_time
                            if counted_bytes < len(chunk) or elapsed >= settings.SPEEDTEST_TIMEOUT:
                                break
                    except (httpx.ReadTimeout, asyncio.TimeoutError, httpx.RemoteProtocolError):
                        pass
                        
        except Exception as e:
            # Only print error if we didn't download anything significant
            if downloaded_bytes < 1024 * 100:
                print(f"[SpeedTest Error] {analyzed_node.node.remark}: {repr(e)}")
            
        elapsed = time.perf_counter() - start_time
        if elapsed > 0:
            download_speed_mbps = (downloaded_bytes * 8) / (1024 * 1024) / elapsed

        return TestedNode(analyzed_node, download_speed_mbps)
