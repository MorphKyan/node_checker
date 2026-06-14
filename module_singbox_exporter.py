import copy
import json
import re
from models import TestedNode
from module_subscription_exporter import SubscriptionExporter

def strip_comments(json_str: str) -> str:
    """
    Strips single-line (// ...) and multi-line (/* ... */) comments from JSON
    without affecting comments inside string literals.
    """
    pattern = r"(\".*?(?<!\\)\")|(/\*.*?\*/|//[^\r\n]*)"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)
    
    def replacer(match):
        if match.group(2) is not None:
            return ""  # It's a comment, replace with empty string
        return match.group(1)  # It's a string, keep it as-is
        
    return regex.sub(replacer, json_str)

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
    cleaned_json = strip_comments(template_str)
    try:
        config = json.loads(cleaned_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse template JSON: {e}")

    if not isinstance(config, dict):
        raise ValueError("Template must be a JSON object")

    # 2. Sort and build remark tags for the tested nodes
    sorted_nodes = SubscriptionExporter.sort_nodes(tested_nodes, valid_only=False)
    remarks = [
        SubscriptionExporter.build_remark(node, mode, max_name_length)
        for node in sorted_nodes
    ]
    remarks = SubscriptionExporter.deduplicate_names(remarks, max_name_length)

    # 3. Create outbound configurations for nodes
    node_outbounds = []
    node_tags = []
    for node, tag in zip(sorted_nodes, remarks):
        vless = node.analyzed_node.node
        outbound = {
            "type": "vless",
            "tag": tag,
            "server": vless.server_ip,
            "server_port": vless.server_port,
            "uuid": vless.uuid,
        }
        
        if vless.flow:
            outbound["flow"] = vless.flow

        # TLS / Reality
        if vless.security in ["tls", "reality"]:
            tls_config = {
                "enabled": True,
                "server_name": vless.sni or "",
                "insecure": False,
                "utls": {
                    "enabled": bool(vless.fp),
                    "fingerprint": vless.fp or "chrome"
                }
            }
            if vless.security == "reality":
                tls_config["reality"] = {
                    "enabled": True,
                    "public_key": vless.pbk or "",
                    "short_id": vless.sid or ""
                }
            outbound["tls"] = tls_config

        # Transport
        if vless.type == "ws":
            outbound["transport"] = {
                "type": "ws",
                "path": vless.path or "",
                "headers": {"Host": vless.host} if vless.host else {}
            }
        elif vless.type == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": vless.path or ""
            }
            
        node_outbounds.append(outbound)
        node_tags.append(tag)

    # 4. Modify outbounds in the template
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        outbounds = []

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

            outbound["outbounds"] = matched_tags

            # Clean template-specific keys
            outbound.pop("include", None)
            outbound.pop("exclude", None)
            outbound.pop("use_all_nodes", None)

    # 5. Append raw node outbounds to the end
    outbounds.extend(node_outbounds)
    config["outbounds"] = outbounds

    return config
