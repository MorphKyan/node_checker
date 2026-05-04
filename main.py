import asyncio
import os
from settings import settings
from module_setup import setup_singbox
from module_parser import VlessParser
from module_tunnel import TunnelController
from module_probe import LightweightProbe
from module_analyzer import NodeAnalyzer
from module_exporter import ResultExporter
from module_cache import ProbeCache
from module_subscription_exporter import SubscriptionExporter
from models import TestedNode, AnalyzedNode

async def process_node_filter(node, local_port: int, sem: asyncio.Semaphore):
    async with sem:
        process = None
        config_path = None
        try:
            cached_probe = await ProbeCache.get(node)
            if cached_probe is not None:
                print(f"[Cache Hit] {node.remark}")
                return NodeAnalyzer.analyze(node, cached_probe)

            process, config_path = await TunnelController.start_tunnel(node, local_port)
            socks5_url = f"socks5://127.0.0.1:{local_port}"
            probe_data = await LightweightProbe.run_probe(node, socks5_url)
            await ProbeCache.set(node, probe_data)
            analyzed = NodeAnalyzer.analyze(node, probe_data)
            return analyzed
        except Exception as e:
            print(f"[Filter Error] {node.remark}: {e}")
            from models import ProbeData
            probe = ProbeData(9999.0, 9999.0, "", "Unknown", "", 0)
            return NodeAnalyzer.analyze(node, probe)
        finally:
            await TunnelController.stop_tunnel(process, config_path)


async def main():
    setup_singbox()
    await ProbeCache.init_db()
    
    sub_url = input("Enter subscription URL or file path (leave empty for inputs/test.txt): ").strip()
    if not sub_url:
        sub_url = os.path.join("inputs", "test.txt")
        
    if sub_url.startswith("http"):
        raw_text = await VlessParser.fetch_subscription(sub_url)
    else:
        if os.path.exists(sub_url):
            with open(sub_url, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            if raw_text.startswith("http") and "\n" not in raw_text:
                print(f"Detected URL in {sub_url}, fetching subscription...")
                raw_text = await VlessParser.fetch_subscription(raw_text)
        else:
            print(f"File {sub_url} not found. Exiting.")
            return

    nodes = VlessParser.parse_nodes(raw_text)
    print(f"Parsed {len(nodes)} valid Vless nodes.")
    if not nodes:
        return

    print("Starting Filter Phase...")
    filter_sem = asyncio.Semaphore(settings.FILTER_CONCURRENCY)
    filter_tasks = []
    
    for i, node in enumerate(nodes):
        port = settings.TUNNEL_LOCAL_PORT_START + i
        filter_tasks.append(process_node_filter(node, port, filter_sem))
        
    analyzed_nodes = await asyncio.gather(*filter_tasks)
    
    valid_nodes = [n for n in analyzed_nodes if n.is_valid]
    # Sort valid nodes by score descending to test the top ones
    valid_nodes.sort(key=lambda n: n.total_score, reverse=True)
    
    print(f"Filter Phase completed. {len(valid_nodes)} nodes passed.")
    
    tested_nodes = []
    
    print("\nStarting Speed Test Phase for the top 3 valid nodes...")
    from module_speedtest import BandwidthTester
    
    nodes_to_test = valid_nodes[:3]
    nodes_to_skip = valid_nodes[3:] + [n for n in analyzed_nodes if not n.is_valid]
    
    async def process_speed_test(node_analyzed, local_port):
        process = None
        config_path = None
        try:
            process, config_path = await TunnelController.start_tunnel(node_analyzed.node, local_port)
            socks5_url = f"socks5://127.0.0.1:{local_port}"
            tested = await BandwidthTester.run_speed_test(node_analyzed, socks5_url)
            return tested
        except Exception as e:
            print(f"[SpeedTest Tunnel Error] {node_analyzed.node.remark}: {e}")
            return TestedNode(node_analyzed, 0.0)
        finally:
            await TunnelController.stop_tunnel(process, config_path)

    test_tasks = []
    for i, n in enumerate(nodes_to_test):
        port = settings.TUNNEL_LOCAL_PORT_START + 1000 + i
        test_tasks.append(process_speed_test(n, port))
        
    if test_tasks:
        tested_results = await asyncio.gather(*test_tasks)
        tested_nodes.extend(tested_results)
        
    for n in nodes_to_skip:
        tested_nodes.append(TestedNode(n, 0.0))
            
    ResultExporter.export_markdown_report(tested_nodes)
    if settings.SUBSCRIPTION_EXPORT_ENABLED:
        SubscriptionExporter.export_enhanced_subscriptions(
            tested_nodes,
            output_dir=settings.SUBSCRIPTION_EXPORT_DIR,
            valid_only=settings.SUBSCRIPTION_EXPORT_VALID_ONLY,
            compact_max_length=settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH,
            detailed_max_length=settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH,
        )
    print("All tasks completed.")

if __name__ == "__main__":
    asyncio.run(main())
