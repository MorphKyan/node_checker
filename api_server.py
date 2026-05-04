from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from models import TestedNode
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_subscription_exporter import SubscriptionExporter
from module_subscription_service import SubscriptionRefreshService
from settings import settings


app = FastAPI(title="Vless Node Checker API")


class SubscriptionCreateRequest(BaseModel):
    url: str = Field(..., min_length=1)
    name: Optional[str] = None


class RefreshRequest(BaseModel):
    speedtest_limit: Optional[int] = Field(default=None, ge=0)
    force_probe: bool = False


@app.on_event("startup")
async def startup() -> None:
    ApiStore.init_db()
    await ProbeCache.init_db()


def normalize_job(row: dict) -> dict:
    return {
        "job_id": row["id"],
        "subscription_id": row["subscription_id"],
        "status": row["status"],
        "phase": row["phase"],
        "processed_nodes": row["processed_nodes"],
        "total_nodes": row["total_nodes"],
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def ensure_subscription(subscription_id: str) -> dict:
    subscription = ApiStore.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription


def schedule_refresh_response(
    subscription_id: str,
    *,
    speedtest_limit: int | None = None,
    force_probe: bool = False,
) -> dict:
    try:
        job = SubscriptionRefreshService.schedule_refresh(
            subscription_id,
            speedtest_limit=speedtest_limit,
            force_probe=force_probe,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {
        "subscription_id": job["subscription_id"],
        "job_id": job["id"],
        "status": job["status"],
    }


def latest_result_or_409(subscription_id: str) -> dict:
    ensure_subscription(subscription_id)
    result = ApiStore.get_latest_result(subscription_id)
    if not result:
        raise HTTPException(status_code=409, detail="No completed result is available")
    return result


def build_plain_subscription(
    nodes: list[TestedNode],
    *,
    mode: Literal["compact", "detailed"],
    valid_only: bool,
) -> str:
    max_length = (
        settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH
        if mode == "compact"
        else settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH
    )
    uris = SubscriptionExporter.build_uris(
        nodes,
        mode,
        max_length,
        valid_only=valid_only,
    )
    content = "\n".join(uris)
    return content + "\n" if content else ""


def build_detail_nodes(nodes: list[TestedNode]) -> list[dict]:
    sorted_nodes = SubscriptionExporter.sort_nodes(nodes, valid_only=False)
    compact_names = SubscriptionExporter.deduplicate_names(
        [
            SubscriptionExporter.build_remark(
                node,
                "compact",
                settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH,
            )
            for node in sorted_nodes
        ],
        settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH,
    )
    detailed_names = SubscriptionExporter.deduplicate_names(
        [
            SubscriptionExporter.build_remark(
                node,
                "detailed",
                settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH,
            )
            for node in sorted_nodes
        ],
        settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH,
    )

    response_nodes = []
    for tested, compact_name, detailed_name in zip(sorted_nodes, compact_names, detailed_names):
        analyzed = tested.analyzed_node
        node = analyzed.node
        probe = analyzed.probe
        profile = probe.profile
        response_nodes.append(
            {
                "fingerprint": ProbeCache.make_node_fingerprint(node),
                "original_name": node.remark,
                "enhanced_name_compact": compact_name,
                "enhanced_name_detailed": detailed_name,
                "raw_uri": node.raw_uri,
                "is_valid": analyzed.is_valid,
                "reject_reason": analyzed.reject_reason,
                "total_score": analyzed.total_score,
                "download_speed_mbps": tested.download_speed_mbps,
                "probe": {
                    "tcp_ping_ms": probe.tcp_ping_ms,
                    "ttfb_ms": probe.ttfb_ms,
                    "actual_ip": probe.actual_ip,
                    "actual_geo": probe.actual_geo,
                    "asn_org": probe.asn_org,
                    "risk_score": profile.risk_score,
                    "network_labels": [
                        SubscriptionExporter.format_labels([label], "")
                        for label in profile.network_labels
                    ],
                    "type_labels": [
                        SubscriptionExporter.format_labels([label], "")
                        for label in profile.risk_labels
                    ],
                    "confidence": profile.confidence,
                    "is_detour": probe.is_detour,
                    "is_backbone": probe.is_backbone,
                    "backbone_info": probe.backbone_info,
                    "evidence": [
                        f"{verdict.source}: {verdict.raw_summary or 'No signal'}"
                        for verdict in profile.evidence
                    ],
                },
            }
        )
    return response_nodes


@app.post("/subscriptions")
async def create_subscription(payload: SubscriptionCreateRequest) -> dict:
    subscription = ApiStore.create_subscription(payload.url, payload.name)
    return schedule_refresh_response(subscription["id"])


@app.get("/subscriptions")
async def list_subscriptions() -> list[dict]:
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "last_status": row["last_status"],
            "node_count": row["node_count"],
            "valid_count": row["valid_count"],
            "updated_at": row["updated_at"],
        }
        for row in ApiStore.list_subscriptions()
    ]


@app.get("/subscriptions/{subscription_id}/enhanced", response_class=PlainTextResponse)
async def get_enhanced_subscription(
    subscription_id: str,
    mode: Literal["compact", "detailed"] = "compact",
    format: Literal["base64", "plain"] = "base64",
    valid_only: bool = Query(default=True),
):
    result = latest_result_or_409(subscription_id)
    plain = build_plain_subscription(result["nodes"], mode=mode, valid_only=valid_only)
    if format == "plain":
        return PlainTextResponse(plain)
    uris = plain.splitlines()
    return PlainTextResponse(SubscriptionExporter.encode_subscription(uris))


@app.get("/subscriptions/{subscription_id}/results")
async def get_subscription_results(subscription_id: str) -> dict:
    result = latest_result_or_409(subscription_id)
    return {
        "subscription_id": subscription_id,
        "status": "completed",
        "node_count": result["node_count"],
        "valid_count": result["valid_count"],
        "updated_at": result["updated_at"],
        "nodes": build_detail_nodes(result["nodes"]),
    }


@app.post("/subscriptions/{subscription_id}/refresh")
async def refresh_subscription(subscription_id: str, payload: RefreshRequest | None = None) -> dict:
    payload = payload or RefreshRequest()
    ensure_subscription(subscription_id)
    return schedule_refresh_response(
        subscription_id,
        speedtest_limit=payload.speedtest_limit,
        force_probe=payload.force_probe,
    )


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = ApiStore.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return normalize_job(job)
