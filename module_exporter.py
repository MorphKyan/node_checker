import os
import re
import unicodedata
from models import TestedNode

def get_visual_width(s: str) -> int:
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width

def pad_string(s: str, width: int) -> str:
    vw = get_visual_width(s)
    return str(s) + " " * max(0, width - vw)

class ResultExporter:
    @staticmethod
    def sanitize_filename(name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", name)

    @staticmethod
    def export_markdown_report(nodes: list[TestedNode], base_dir: str = "result"):
        import shutil
        if os.path.exists(base_dir):
            try:
                shutil.rmtree(base_dir)
            except Exception as e:
                print(f"[Exporter] Warning: Failed to clear old results: {e}")
                
        os.makedirs(base_dir, exist_ok=True)
        details_dir = os.path.join(base_dir, "node_details")
        os.makedirs(details_dir, exist_ok=True)
        
        report_path = os.path.join(base_dir, "report.md")

        sorted_nodes = sorted(
            nodes,
            key=lambda n: (
                n.analyzed_node.is_valid,
                n.analyzed_node.total_score
            ),
            reverse=True
        )
        
        headers = ["Status", "Remark", "Actual IP", "Geo", "Ping(ms)", "TTFB(ms)", "Speed(Mbps)", "Detour", "Backbone", "Score", "Reject Reason"]
        rows = []
        
        for tn in sorted_nodes:
            an = tn.analyzed_node
            probe = an.probe
            status = "✅" if an.is_valid else "❌"
            ping = f"{probe.tcp_ping_ms:.0f}"
            ttfb = f"{probe.ttfb_ms:.0f}"
            score = f"{an.total_score:.1f}"
            geo = str(probe.actual_geo)
            remark = str(an.node.remark)[:40]
            actual_ip = str(probe.actual_ip)
            
            speed = f"{tn.download_speed_mbps:.2f}"
            
            speed = f"{tn.download_speed_mbps:.2f}"
            
            rows.append([
                status, remark, actual_ip, geo, ping, ttfb, speed,
                "Yes" if probe.is_detour else "No",
                "Yes" if probe.is_backbone else "No",
                score, str(an.reject_reason)
            ])
            
        widths = [get_visual_width(h) for h in headers]
        for row in rows:
            for i, col in enumerate(row):
                widths[i] = max(widths[i], get_visual_width(col))
                
        def format_row(row_data):
            return "| " + " | ".join(pad_string(val, widths[i]) for i, val in enumerate(row_data)) + " |"

        lines = []
        lines.append("# 🚀 Vless Node Checker Report\n")
        lines.append(format_row(headers))
        lines.append("|" + "|".join("-" * (widths[i] + 2) for i in range(len(widths))) + "|")
        
        for row in rows:
            lines.append(format_row(row))
            
        for tn in sorted_nodes:
            an = tn.analyzed_node
            probe = an.probe
            
            # Write detailed report for each node
            safe_remark = ResultExporter.sanitize_filename(an.node.remark or "Unnamed")
            # Use last part of IP/Domain as suffix to avoid collision
            addr_parts = an.node.server_ip.split('.')
            ip_suffix = addr_parts[-1] if addr_parts else "node"
            safe_remark = f"{safe_remark}_{ip_suffix}"
            detail_path = os.path.join(details_dir, f"{safe_remark}.md")
            
            detail_content = f"""# Node Detail: {an.node.remark}

## 1. Basic Info
- **UUID**: `{an.node.uuid}`
- **Server**: `{an.node.server_ip}:{an.node.server_port}`
- **Expected Geo**: `{an.node.expected_geo}`
- **Security**: `{an.node.security}`
- **Transport**: `{an.node.type}`
- **SNI**: `{an.node.sni}`

## 2. Probe Results
- **TCP Ping**: `{probe.tcp_ping_ms:.2f} ms`
- **TTFB**: `{probe.ttfb_ms:.2f} ms`
- **Actual IP**: `{probe.actual_ip}`
- **Actual Geo**: `{probe.actual_geo}`
- **ASN Org**: `{probe.asn_org}`

### IP Intelligence
- **IPWhoIs**: `{probe.ipwhois_info}`
- **IPApi**: `{probe.ipapi_info}`
- **Scamalytics**: `{probe.scamalytics_info}`

## 3. Analysis & Scoring
- **Is Valid**: `{an.is_valid}`
- **Reject Reason**: `{an.reject_reason or "None"}`
- **Score Details**: `{an.score_details}`
- **Total Score**: `{an.total_score:.2f}`

## 4. Route Trace
- **Trace Path**: `{probe.trace_path}`
- **Is Detour**: `{"Yes" if probe.is_detour else "No"}`
- **Is Backbone**: `{"Yes" if probe.is_backbone else "No"}`
- **Backbone Info**: `{probe.backbone_info}`

## 5. Performance
- **Download Speed**: `{tn.download_speed_mbps:.2f} Mbps`
"""
            with open(detail_path, "w", encoding="utf-8") as df:
                df.write(detail_content)
            
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        print(f"[Exporter] Report saved to {report_path}")
        print(f"[Exporter] Detailed node reports saved to {details_dir}")
