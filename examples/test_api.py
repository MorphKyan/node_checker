import asyncio
import os

import aiohttp


async def main():
    async with aiohttp.ClientSession() as session:
        # Test ipapi
        ipapi_key = os.getenv("IPAPI_KEY", "")
        ipapi_url = f"https://api.ipapi.is?q=8.8.8.8{'&key=' + ipapi_key if ipapi_key else ''}"
        async with session.get(ipapi_url) as resp:
            print("ipapi status:", resp.status)
            print("ipapi response:", await resp.text())
        
        # Test scamalytics
        scamalytics_url = os.getenv("SCAMALYTICS_API", "").format(ip="8.8.8.8")
        if scamalytics_url:
            async with session.get(scamalytics_url) as resp:
                print("scamalytics status:", resp.status)
                print("scamalytics response:", await resp.text())

asyncio.run(main())
