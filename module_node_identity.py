import hashlib
import json

from models import VlessNode


def make_node_fingerprint(node: VlessNode) -> str:
    identity = {
        "uuid": node.uuid,
        "server_ip": node.server_ip,
        "server_port": node.server_port,
        "security": node.security,
        "sni": node.sni,
        "fp": node.fp,
        "pbk": node.pbk,
        "sid": node.sid,
        "type": node.type,
        "path": node.path,
        "host": node.host,
        "flow": node.flow,
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_node_identity(node: VlessNode) -> str:
    identity = {
        "server": f"{node.server_ip}:{node.server_port}",
        "security": node.security,
        "type": node.type,
        "sni": node.sni,
        "host": node.host,
    }
    return json.dumps(identity, sort_keys=True, ensure_ascii=False)
