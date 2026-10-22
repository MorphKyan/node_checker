import asyncio
import os
from settings import settings
from module_setup import setup_singbox, setup_xray
from module_parser import NodeParser
from module_exporter import ResultExporter
from module_subscription_exporter import SubscriptionExporter
from module_subscription_service import SubscriptionRefreshService
from module_api_store import ApiStore


async def main():
    await asyncio.to_thread(setup_xray if settings.PROXY_CORE == "xray" else setup_singbox)
    
    sub_url = input("Enter subscription URL or file path (leave empty for inputs/test.txt): ").strip()
    if not sub_url:
        sub_url = os.path.join("inputs", "test.txt")
        
    try:
        raw_text = await SubscriptionRefreshService.fetch_subscription_text(sub_url)
    except FileNotFoundError:
        print(f"File {sub_url} not found. Exiting.")
        return

    nodes = NodeParser.parse_nodes(raw_text)
    print(f"Parsed {len(nodes)} proxy nodes.")
    if not nodes:
        return

    print("Starting Filter Phase...")
    tested_nodes = await SubscriptionRefreshService.run_nodes(
        nodes,
        speedtest_limit=settings.API_DEFAULT_SPEEDTEST_LIMIT,
        probe_config=ApiStore.get_probe_config_snapshot(),
    )
    valid_count = sum(1 for n in tested_nodes if n.analyzed_node.is_valid)
    print(f"Filter Phase completed. {valid_count} nodes passed.")
            
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
