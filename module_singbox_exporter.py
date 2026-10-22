import json
import re
from models import TestedNode
from module_singbox_outbound import singbox_outbound
from module_subscription_exporter import SubscriptionExporter

def strip_comments(json_str: str) -> str:
    """
    Strips single-line (// ...) and multi-line (/* ... */) comments from JSON
    without affecting comments inside string literals.
    """
    pattern = r'("(?:\\.|[^"\\])*")|/\*.*?\*/|//[^\r\n]*'
    return re.sub(pattern, lambda match: match.group(1) or " ", json_str, flags=re.DOTALL)


def _parse_singbox_template(content: str) -> dict:
    cleaned_json = strip_comments(content)
    try:
        template = json.loads(cleaned_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse template JSON: {e}") from e

    if not isinstance(template, dict):
        raise ValueError("Template must be a JSON object")

    return template


def validate_singbox_template_content(content: str) -> None:
    _parse_singbox_template(content)


def generate_singbox_config(
    template_str: str,
    tested_nodes: list[TestedNode],
    mode: str = "compact",
    max_name_length: int = 64
) -> dict:
    """
    Merges tested nodes into a sing-box configuration template.
    Matches template outbounds by regex tags and appends node outbounds.
    """
    # 1. Clean and parse template
    config = _parse_singbox_template(template_str)

    # 2. Sort and build remark tags for the tested nodes
    sorted_nodes = SubscriptionExporter.sort_nodes(tested_nodes, valid_only=False)
    remarks = SubscriptionExporter.build_names(sorted_nodes, mode, max_name_length)

    # 3. Create outbound configurations for nodes
    node_outbounds = []
    node_tags = []
    for node, tag in zip(sorted_nodes, remarks):
        p_node = node.analyzed_node.node
        outbound = singbox_outbound(p_node, tag)
        node_outbounds.append(outbound)
        node_tags.append(tag)

    # 4. Modify outbounds in the template
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        outbounds = []

    needs_direct = False
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue

        has_include = "include" in outbound
        use_all = outbound.get("use_all_nodes", False)

        if has_include or use_all:
            include_pattern = outbound.get("include", ".*")
            exclude_pattern = outbound.get("exclude", "")

            try:
                inc_regex = re.compile(include_pattern, re.IGNORECASE)
            except Exception:
                inc_regex = re.compile(".*")

            exc_regex = None
            if exclude_pattern:
                try:
                    exc_regex = re.compile(exclude_pattern, re.IGNORECASE)
                except Exception:
                    pass

            matched_tags = []
            for tag in node_tags:
                if inc_regex.search(tag):
                    if exc_regex and exc_regex.search(tag):
                        continue
                    matched_tags.append(tag)

            if not matched_tags:
                matched_tags.append("DIRECT")
                needs_direct = True

            outbound["outbounds"] = matched_tags

            # Clean template-specific keys
            outbound.pop("include", None)
            outbound.pop("exclude", None)
            outbound.pop("use_all_nodes", None)

    # 5. Append raw node outbounds to the end
    if needs_direct and not any(isinstance(item, dict) and item.get("tag") == "DIRECT" for item in outbounds):
        outbounds.append({"type": "direct", "tag": "DIRECT"})
    outbounds.extend(node_outbounds)
    config["outbounds"] = outbounds

    return config
