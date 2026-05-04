import base64
import os
import urllib.parse
import unicodedata

from models import LabelEvidence, TestedNode
from module_profile import DISPLAY_LABELS


COUNTRY_FLAGS = {
    "HK": "🇭🇰",
    "TW": "🇹🇼",
    "JP": "🇯🇵",
    "SG": "🇸🇬",
    "US": "🇺🇸",
    "KR": "🇰🇷",
    "GB": "🇬🇧",
    "UK": "🇬🇧",
    "DE": "🇩🇪",
}


def get_visual_width(s: str) -> int:
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def truncate_visual(s: str, max_width: int) -> str:
    text = str(s)
    if max_width <= 0:
        return ""
    if get_visual_width(text) <= max_width:
        return text

    suffix = "..."
    suffix_width = get_visual_width(suffix)
    if max_width <= suffix_width:
        return suffix[:max_width]
    target_width = max(0, max_width - suffix_width)
    current_width = 0
    chars = []

    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if current_width + char_width > target_width:
            break
        chars.append(char)
        current_width += char_width

    return "".join(chars).rstrip() + suffix


class SubscriptionExporter:
    @staticmethod
    def format_labels(labels: list[LabelEvidence], fallback: str) -> str:
        display = [
            DISPLAY_LABELS.get(item.label, item.label)
            for item in labels
            if item.label != "unknown"
        ]
        return "/".join(display) if display else fallback

    @staticmethod
    def format_network_labels(profile) -> str:
        return SubscriptionExporter.format_labels(profile.network_labels, "未知网络")

    @staticmethod
    def format_type_labels(profile) -> str:
        return SubscriptionExporter.format_labels(profile.risk_labels, "未知类型")

    @staticmethod
    def format_location(geo: str) -> str:
        geo_code = (geo or "Unknown").upper()
        if geo_code == "UNKNOWN":
            return "Unknown"
        flag = COUNTRY_FLAGS.get(geo_code)
        return f"{flag} {geo_code}" if flag else geo_code

    @staticmethod
    def format_score(score: float) -> str:
        return f"{score:.0f}分"

    @staticmethod
    def format_latency(ms: float) -> str:
        if ms >= 9999.0:
            return "超时"
        return f"{ms:.0f}ms"

    @staticmethod
    def format_speed(mbps: float) -> str:
        if mbps <= 0:
            return "未测速"
        return f"{mbps:.2f}Mbps"

    @staticmethod
    def choose_geo(tested_node: TestedNode) -> str:
        analyzed = tested_node.analyzed_node
        actual_geo = analyzed.probe.actual_geo
        if actual_geo and actual_geo != "Unknown":
            return actual_geo
        return analyzed.node.expected_geo or "Unknown"

    @staticmethod
    def build_remark(tested_node: TestedNode, mode: str, max_length: int) -> str:
        analyzed = tested_node.analyzed_node
        node = analyzed.node
        probe = analyzed.probe
        profile = probe.profile

        parts = [
            SubscriptionExporter.format_location(SubscriptionExporter.choose_geo(tested_node)),
            SubscriptionExporter.format_network_labels(profile),
            SubscriptionExporter.format_type_labels(profile),
            SubscriptionExporter.format_score(analyzed.total_score),
        ]

        if mode == "compact":
            parts.append(SubscriptionExporter.format_latency(probe.ttfb_ms))
        elif mode == "detailed":
            parts.append(
                f"{SubscriptionExporter.format_latency(probe.tcp_ping_ms)}/"
                f"{SubscriptionExporter.format_latency(probe.ttfb_ms)}"
            )
            parts.append(SubscriptionExporter.format_speed(tested_node.download_speed_mbps))
            if probe.asn_org:
                parts.append(str(probe.asn_org))
            if node.remark:
                parts.append(str(node.remark))
        else:
            raise ValueError(f"Unsupported subscription remark mode: {mode}")

        remark = " | ".join(part for part in parts if part)
        return truncate_visual(remark, max_length)

    @staticmethod
    def rewrite_vless_remark(raw_uri: str, remark: str) -> str:
        base_uri = raw_uri.split("#", 1)[0]
        encoded_remark = urllib.parse.quote(remark, safe="")
        return f"{base_uri}#{encoded_remark}"

    @staticmethod
    def sort_nodes(nodes: list[TestedNode], valid_only: bool = True) -> list[TestedNode]:
        indexed_nodes = [
            (index, node)
            for index, node in enumerate(nodes)
            if not valid_only or node.analyzed_node.is_valid
        ]
        indexed_nodes.sort(
            key=lambda item: (
                -item[1].analyzed_node.total_score,
                item[1].analyzed_node.probe.ttfb_ms,
                -item[1].download_speed_mbps,
                item[0],
            )
        )
        return [node for _, node in indexed_nodes]

    @staticmethod
    def deduplicate_names(names: list[str], max_length: int) -> list[str]:
        seen: dict[str, int] = {}
        result = []

        for name in names:
            count = seen.get(name, 0) + 1
            seen[name] = count

            if count == 1:
                result.append(name)
                continue

            suffix = f" #{count}"
            trimmed_base = truncate_visual(name, max_length - get_visual_width(suffix))
            result.append(f"{trimmed_base}{suffix}")

        return result

    @staticmethod
    def build_uris(
        nodes: list[TestedNode],
        mode: str,
        max_name_length: int,
        valid_only: bool = True,
    ) -> list[str]:
        sorted_nodes = SubscriptionExporter.sort_nodes(nodes, valid_only=valid_only)
        remarks = [
            SubscriptionExporter.build_remark(node, mode, max_name_length)
            for node in sorted_nodes
        ]
        remarks = SubscriptionExporter.deduplicate_names(remarks, max_name_length)
        return [
            SubscriptionExporter.rewrite_vless_remark(node.analyzed_node.node.raw_uri, remark)
            for node, remark in zip(sorted_nodes, remarks)
        ]

    @staticmethod
    def encode_subscription(uris: list[str]) -> str:
        plain_text = "\n".join(uris)
        if plain_text:
            plain_text += "\n"
        return base64.b64encode(plain_text.encode("utf-8")).decode("ascii")

    @staticmethod
    def export_enhanced_subscriptions(
        nodes: list[TestedNode],
        output_dir: str,
        valid_only: bool = True,
        compact_max_length: int = 64,
        detailed_max_length: int = 96,
    ) -> None:
        os.makedirs(output_dir, exist_ok=True)

        outputs = {
            "enhanced_compact.txt": SubscriptionExporter.build_uris(
                nodes, "compact", compact_max_length, valid_only=valid_only
            ),
            "enhanced_detailed.txt": SubscriptionExporter.build_uris(
                nodes, "detailed", detailed_max_length, valid_only=valid_only
            ),
        }

        for filename, uris in outputs.items():
            path = os.path.join(output_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                content = "\n".join(uris)
                if content:
                    content += "\n"
                f.write(content)

            base64_path = path.replace(".txt", "_base64.txt")
            with open(base64_path, "w", encoding="utf-8") as f:
                f.write(SubscriptionExporter.encode_subscription(uris))

        print(f"[SubscriptionExporter] Enhanced subscriptions saved to {output_dir}")
