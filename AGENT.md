# Vless Node Checker - Agent Context

## Project Overview

Vless Node Checker is a local VLESS subscription enhancement and node intelligence service. It accepts a subscription URL or local subscription file, parses `vless://` URIs, starts temporary `sing-box` tunnels, probes node quality, queries IP intelligence APIs, builds a node profile, scores each node, and exports both human-readable reports and enhanced subscription links.

The practical product direction is:

```text
raw subscription URL
  -> node parsing
  -> temporary tunnel probing
  -> IP intelligence aggregation
  -> node profile and risk aggregation
  -> JSON result storage
  -> enhanced subscription URL / dashboard / reports
```

The service should be treated as a "subscription relay + node profiling + quality filtering" tool, not only a one-off scanner.

## Primary Use Cases

- Personal enhanced subscription relay: convert unreadable provider node names into names that include geo, network type, risk type, risk, and latency.
- Node quality dashboard: inspect latency, TTFB, speed, ASN, exit IP, route detour, backbone hints, risk score, source-by-source API verdicts, and conflict warning indicators.
- Subscription cleanup: export only valid nodes and sort by risk, TTFB, and speed.
- Multi-source aggregation: combine several upstream subscriptions, deduplicate via connection fingerprint, filter (e.g., by max_risk), limit returned quantity, and publish one clean aggregated downstream subscription.
- Policy exports: generate different subscription URLs for different client needs, such as filtering by max_risk, valid_only, and limit.

## Directory Structure

- `api_server.py`: FastAPI backend for subscriptions, refresh jobs, enhanced subscription output, detailed results, and runtime settings.
- `models.py`: Dataclasses for VLESS nodes, probe data, IP intelligence verdicts, node profiles, analyzed nodes, and speed-tested nodes.
- `settings.py`: Runtime defaults for concurrency, timeouts, API endpoints, cache paths, name length limits, and speedtest defaults.
- `module_runtime_settings.py`: Editable runtime settings persisted for the API service.
- `module_setup.py`: Environment preparation for local `sing-box.exe`.
- `module_parser.py`: Subscription fetch/decode logic and `vless://` URI parsing.
- `module_tunnel.py`: Temporary `sing-box` process lifecycle and per-node tunnel config handling.
- `module_probe.py`: TCP ping, TTFB, exit IP lookup, IP intelligence API calls, traceroute analysis, and profile aggregation input.
- `module_profile.py`: Normalizes IP intelligence responses into network labels, risk labels, risk scores, confidence, and evidence.
- `module_analyzer.py`: Validity checks based solely on successful TTFB.
- `module_speedtest.py`: Top-N download speed test for selected valid nodes.
- `module_cache.py`: Probe result cache backed by JSON files.
- `module_api_store.py`: JSON storage for subscriptions, refresh jobs, and latest completed results.
- `module_subscription_service.py`: Async refresh orchestration for API jobs.
- `module_subscription_exporter.py`: Enhanced VLESS URI generation, name templating, sorting, dedupe, truncation, and base64 encoding.
- `module_exporter.py`: CLI Markdown summary and per-node detailed report generation.
- `main.py`: CLI orchestrator implementing fetch, filter, Top-N speedtest, and export.
- `frontend/`: React/Vite dashboard for subscriptions, jobs, nodes, export preview, and runtime settings.
- `tests/`: Unit tests for profile/report behavior, subscription export, API behavior, and frontend helpers.

## Current Label Model

Network labels live in `NodeProfile.network_labels`:

- `residential`: home broadband.
- `likely_residential`: likely home broadband.
- `mobile`: mobile network.
- `business`: business ISP.
- `datacenter`: datacenter.
- `hosting`: hosting provider.
- `unknown`: unknown.

Risk/type labels live in `NodeProfile.risk_labels`:

- `clean`: no strong proxy/VPN/Tor/abuse signal.
- `vpn`: VPN signal.
- `proxy`: proxy signal.
- `tor`: Tor signal.
- `abuser`: abuse/fraud signal.
- `unknown`: unknown.

The profile output is evidence-based and probabilistic. Residential detection is not guaranteed; use "likely" and confidence where the upstream APIs disagree or provide weak signals.

## Architecture Constraints

- Enhanced subscriptions must only rewrite the URI fragment remark (`#remark`). Do not alter UUID, host, port, query parameters, transport, TLS/Reality, SNI, path, host header, or other connection settings.
- Use the existing `NodeProfile` and `SubscriptionExporter` path for enhanced names. Do not duplicate classification logic in API handlers or frontend code.
- Keep compact and detailed subscription names readable. Full evidence belongs in `/results` and the dashboard, not necessarily in every node name.
- Default API binding is local-first (`127.0.0.1`) and unauthenticated. Public deployment requires tokenized subscription URLs, secret handling, log redaction, rate limiting, and likely Docker/service packaging.
- Probe and speedtest work is network-heavy. Preserve Top-N speedtest behavior and concurrency controls unless the user explicitly asks for a wider scan.
- Cache probe results when possible. `force_probe` should bypass cache reads but still write fresh results.
- Avoid starting duplicate refresh jobs for the same subscription. The API should return the active queued/running job instead.
- Keep JSON as the default local storage layer unless the user asks for a multi-user or server deployment design.

## Product Roadmap Notes

Near-term useful improvements:

- Configurable naming templates while preserving safe URI rewriting.
- Configurable routing filters (e.g., region-specific geo, network type, exclude_type, max_ttfb).
- Better profile transparency in the frontend, including source-by-source API verdicts and conflict display (implemented).
- Historical result storage so users can see nodes changing IP, label, risk, or route over time.
- Multi-subscription merge, dedupe, risk filtering, and limit slicing (implemented in `/subscriptions/enhanced`).

Public or shared deployments should be a separate milestone because they require security and operational work beyond the current local tool design.

## Verification

Run backend tests:

```powershell
python -m unittest discover -s tests
```

Run frontend tests when touching `frontend/`:

```powershell
cd frontend
npm test
```
