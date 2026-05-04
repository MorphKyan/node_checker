import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # 代理内核路径
    SING_BOX_PATH = os.getenv("SING_BOX_PATH", "sing-box.exe")

    # 并发与超时控制
    FILTER_CONCURRENCY = 10
    SPEEDTEST_CONCURRENCY = 2
    
    PROBE_TEST_TIMES = 3  # ping和TTFB测试次数
    
    TUNNEL_START_DELAY = 1.5  # 启动代理内核后的等待时间(秒)
    TUNNEL_LOCAL_PORT_START = 10000

    TCP_PING_TIMEOUT = 3.0
    TTFB_TIMEOUT = 5.0
    API_TIMEOUT = 5.0
    SPEEDTEST_TIMEOUT = 10.0

    # 测试目标 URLs
    TTFB_TARGET_URL = "http://www.gstatic.com/generate_204"
    IPWHOIS_API = "http://ipwho.is/"
    IPAPI_API = "https://api.ipapi.is?q={ip}&key=f61c48dc3d163908ae7c"
    SCAMALYTICS_API = "https://api13.scamalytics.com/v3/69f7fa7688915/?key=d28737974455ac4b60bd8168b1054f64df664fb2ac8e8320a18032e4539b1445&ip={ip}"
    SPEEDTEST_URL = "https://dl.google.com/android/repository/platform-tools_r35.0.0-windows.zip" # ~6MB

    # 评分规则阈值
    FRAUD_SCORE_TOLERANCE = 75
    MIN_TOTAL_SCORE = 50.0

    # 本地探测结果缓存
    CACHE_ENABLED = True
    CACHE_DB_PATH = "cache/probe_cache.sqlite3"
    PROBE_CACHE_TTL_SECONDS = 24 * 60 * 60
    CACHE_FAILURE_RESULTS = False

    @classmethod
    def load_from_file(cls, filepath="config.json"):
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if hasattr(cls, k):
                        setattr(cls, k, v)

settings = Config()
