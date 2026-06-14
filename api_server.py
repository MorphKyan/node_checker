from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from module_api_presenter import build_detail_nodes, build_plain_subscription, normalize_job
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_runtime_settings import RuntimeSettings
from module_subscription_exporter import SubscriptionExporter
from module_subscription_service import SubscriptionRefreshService
from module_singbox_exporter import generate_singbox_config



@asynccontextmanager
async def lifespan(app: FastAPI):
    RuntimeSettings.load()
    ApiStore.init_db()
    ApiStore.fail_stale_active_jobs("API server restarted before refresh completed")
    await ProbeCache.init_db()
    yield


app = FastAPI(title="Vless Node Checker API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubscriptionCreateRequest(BaseModel):
    url: str = Field(..., min_length=1)
    name: Optional[str] = None


class RefreshRequest(BaseModel):
    speedtest_limit: Optional[int] = Field(default=None, ge=0, le=100)
    force_probe: bool = False


class SubscriptionUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    url: Optional[str] = Field(default=None, min_length=1)


class RuntimeSettingsRequest(BaseModel):
    FILTER_CONCURRENCY: Optional[int] = Field(default=None, ge=1, le=100)
    SPEEDTEST_CONCURRENCY: Optional[int] = Field(default=None, ge=1, le=20)
    API_DEFAULT_SPEEDTEST_LIMIT: Optional[int] = Field(default=None, ge=0, le=100)
    CACHE_ENABLED: Optional[bool] = None
    PROBE_CACHE_TTL_SECONDS: Optional[int] = Field(default=None, ge=60)
    CACHE_FAILURE_RESULTS: Optional[bool] = None
    SUBSCRIPTION_MAX_M: Optional[int] = Field(default=None, ge=1, le=50)
    SPEEDTEST_MAX_M: Optional[int] = Field(default=None, ge=1, le=256)
    SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: Optional[int] = Field(default=None, ge=16, le=160)
    SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: Optional[int] = Field(default=None, ge=32, le=240)
    TTFB_TARGET_URL: Optional[str] = Field(default=None, min_length=1)
    SPEEDTEST_URL: Optional[str] = Field(default=None, min_length=1)


class SingboxTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class SingboxTemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    content: Optional[str] = Field(default=None, min_length=1)


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
            "last_job_id": row["last_job_id"],
        }
        for row in ApiStore.list_subscriptions()
    ]


@app.get("/subscriptions/enhanced", response_class=PlainTextResponse)
async def get_enhanced_subscription(
    subscription_ids: list[str] = Query(..., alias="subscription_id"),
    limit: Optional[int] = Query(default=None, ge=1),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=100.0),
    mode: Literal["compact", "detailed"] = "compact",
    format: Literal["base64", "plain"] = "base64",
    valid_only: bool = Query(default=True),
):
    from module_node_identity import make_node_fingerprint

    # 1. Verify all requested subscriptions exist
    for sub_id in subscription_ids:
        ensure_subscription(sub_id)

    # 2. Retrieve latest results and aggregate nodes
    aggregated_nodes_map = {}
    has_results = False
    for sub_id in subscription_ids:
        result = ApiStore.get_latest_result(sub_id)
        if result:
            has_results = True
            for node in result["nodes"]:
                # 3. Deduplication using make_node_fingerprint
                fp = make_node_fingerprint(node.analyzed_node.node)
                existing = aggregated_nodes_map.get(fp)
                if not existing or node.analyzed_node.total_score > existing.analyzed_node.total_score:
                    aggregated_nodes_map[fp] = node

    if not has_results:
        raise HTTPException(
            status_code=409,
            detail="No completed result is available for any of the subscriptions",
        )

    aggregated_nodes = list(aggregated_nodes_map.values())

    # 4. Filter nodes by validity and minimum score
    filtered_nodes = []
    for node in aggregated_nodes:
        if valid_only and not node.analyzed_node.is_valid:
            continue
        if min_score is not None and node.analyzed_node.total_score < min_score:
            continue
        filtered_nodes.append(node)

    # 5. Sort nodes using SubscriptionExporter.sort_nodes
    sorted_nodes = SubscriptionExporter.sort_nodes(filtered_nodes, valid_only=False)

    # 6. Apply limit parameter
    if limit is not None:
        sorted_nodes = sorted_nodes[:limit]

    # 7. Format remarks and construct base64 or plain output
    plain = build_plain_subscription(sorted_nodes, mode=mode, valid_only=False)
    if format == "plain":
        return PlainTextResponse(plain)
    uris = plain.splitlines()
    return PlainTextResponse(SubscriptionExporter.encode_subscription(uris))


@app.get("/subscriptions/{subscription_id}")
async def get_subscription(subscription_id: str) -> dict:
    subscription = ensure_subscription(subscription_id)
    result = ApiStore.get_latest_result(subscription_id)
    return {
        "id": subscription["id"],
        "name": subscription["name"],
        "url": subscription["url"],
        "last_status": subscription["last_status"],
        "node_count": result["node_count"] if result else 0,
        "valid_count": result["valid_count"] if result else 0,
        "updated_at": subscription["updated_at"],
        "last_job_id": subscription["last_job_id"],
    }


@app.patch("/subscriptions/{subscription_id}")
async def update_subscription(subscription_id: str, payload: SubscriptionUpdateRequest) -> dict:
    ensure_subscription(subscription_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail="No fields to update")
    updated = ApiStore.update_subscription(subscription_id, **data)
    if not updated:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return await get_subscription(subscription_id)


@app.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str) -> dict:
    if not ApiStore.delete_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"deleted": True, "subscription_id": subscription_id}



@app.get("/subscriptions/{subscription_id}/results")
async def get_subscription_results(subscription_id: str) -> dict:
    subscription = ensure_subscription(subscription_id)
    result = latest_result_or_409(subscription_id)
    return {
        "subscription_id": subscription_id,
        "status": "completed",
        "subscription_status": subscription["last_status"],
        "last_job_id": subscription["last_job_id"],
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


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    job = SubscriptionRefreshService.cancel_refresh(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return normalize_job(job)


@app.get("/settings")
async def get_settings() -> dict:
    return RuntimeSettings.get_editable()


@app.get("/settings/metadata")
async def get_settings_metadata() -> dict:
    return RuntimeSettings.get_metadata()


@app.patch("/settings")
async def update_settings(payload: RuntimeSettingsRequest) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail="No settings to update")
    return RuntimeSettings.apply(data)


@app.get("/singbox/templates")
async def list_singbox_templates() -> list[dict]:
    return ApiStore.list_singbox_templates()


@app.post("/singbox/templates")
async def create_singbox_template(payload: SingboxTemplateCreateRequest) -> dict:
    return ApiStore.create_singbox_template(payload.name, payload.content)


@app.get("/singbox/templates/{template_id}")
async def get_singbox_template(template_id: str) -> dict:
    template = ApiStore.get_singbox_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@app.patch("/singbox/templates/{template_id}")
async def update_singbox_template(template_id: str, payload: SingboxTemplateUpdateRequest) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail="No fields to update")
    updated = ApiStore.update_singbox_template(template_id, **data)
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found")
    return updated


@app.delete("/singbox/templates/{template_id}")
async def delete_singbox_template(template_id: str) -> dict:
    if not ApiStore.delete_singbox_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True, "template_id": template_id}


@app.get("/subscriptions/singbox")
async def get_singbox_subscription(
    subscription_ids: list[str] = Query(..., alias="subscription_id"),
    template_id: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=100.0),
    mode: Literal["compact", "detailed"] = "compact",
    valid_only: bool = Query(default=True),
):
    from module_node_identity import make_node_fingerprint

    # 1. Fetch template content
    if template_id:
        template = ApiStore.get_singbox_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
    else:
        templates = ApiStore.list_singbox_templates()
        if not templates:
            raise HTTPException(status_code=400, detail="No templates available")
        template = templates[0]

    # 2. Verify all requested subscriptions exist
    for sub_id in subscription_ids:
        ensure_subscription(sub_id)

    # 3. Retrieve latest results and aggregate nodes
    aggregated_nodes_map = {}
    has_results = False
    for sub_id in subscription_ids:
        result = ApiStore.get_latest_result(sub_id)
        if result:
            has_results = True
            for node in result["nodes"]:
                # Deduplication using make_node_fingerprint
                fp = make_node_fingerprint(node.analyzed_node.node)
                existing = aggregated_nodes_map.get(fp)
                if not existing or node.analyzed_node.total_score > existing.analyzed_node.total_score:
                    aggregated_nodes_map[fp] = node

    if not has_results:
        raise HTTPException(
            status_code=409,
            detail="No completed result is available for any of the subscriptions",
        )

    aggregated_nodes = list(aggregated_nodes_map.values())

    # 4. Filter nodes by validity and minimum score
    filtered_nodes = []
    for node in aggregated_nodes:
        if valid_only and not node.analyzed_node.is_valid:
            continue
        if min_score is not None and node.analyzed_node.total_score < min_score:
            continue
        filtered_nodes.append(node)

    # 5. Apply limit
    sorted_nodes = SubscriptionExporter.sort_nodes(filtered_nodes, valid_only=False)
    if limit is not None:
        sorted_nodes = sorted_nodes[:limit]

    # 6. Generate configuration
    try:
        config = generate_singbox_config(
            template["content"],
            sorted_nodes,
            mode=mode,
            max_name_length=96 if mode == "detailed" else 64
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Configuration generation error: {e}")

    return config


def frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parent / "frontend" / "dist"


@app.get("/")
async def serve_frontend_root():
    index_path = frontend_dist_dir() / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")
    return FileResponse(index_path)


@app.get("/{path:path}")
async def serve_frontend_asset_or_route(path: str):
    dist_dir = frontend_dist_dir()
    index_path = dist_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    requested = (dist_dir / path).resolve()
    dist_root = dist_dir.resolve()
    if requested.is_file() and dist_root in requested.parents:
        return FileResponse(requested)
    return FileResponse(index_path)
