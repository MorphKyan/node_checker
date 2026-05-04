import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        # Test ipapi
        async with session.get("https://api.ipapi.is?q=8.8.8.8&key=f61c48dc3d163908ae7c") as resp:
            print("ipapi status:", resp.status)
            print("ipapi response:", await resp.text())
        
        # Test scamalytics
        async with session.get("https://scamalytics.com/pvt/57ad6c72c5388a16cd3578685714be16?ip=8.8.8.8") as resp:
            print("scamalytics status:", resp.status)
            print("scamalytics response:", await resp.text())

asyncio.run(main())
