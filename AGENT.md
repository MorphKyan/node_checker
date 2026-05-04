# 🤖 Vless Node Checker - Agent Context

## 📌 Project Overview
An asynchronous Python pipeline for comprehensive Vless node analysis. It performs subscription parsing, multi-layered connectivity testing (TCP Ping, TTFB), advanced IP intelligence audits (fraud scores, proxy detection), traceroute path analysis (backbone & detour detection), and high-load bandwidth testing. 

## 📁 Directory Structure
* `PLAN.md`: The original design doc.
* `AGENT.md`: Context for AI assistants (this file).
* `models.py`: Pydantic/Dataclass models for nodes, probes, and results.
* `settings.py`: Configuration (concurrency, timeouts, API endpoints).
* `module_setup.py`: Environment prep (downloads `sing-box.exe`).
* `module_parser.py`: Decodes subscriptions and parses `vless://` URIs.
* `module_tunnel.py`: Lifecycle management for `sing-box` subprocesses with dynamic JSON configs.
* `module_probe.py`: 
    - **Physical**: TCP Ping & TTFB.
    - **Intelligence**: Multi-API IP audit (IPWhoIs, ipapi.is, Scamalytics) for risk scores and tags (VPN/Proxy/Hosting).
    - **Route**: Traceroute analysis to detect routing detours and identify backbone providers (CN2, CU9929, CMI, NTT, etc.).
* `module_analyzer.py`: Logic engine for geo-matching, risk evaluation, and final score calculation.
* `module_speedtest.py`: 10s async download test using `httpx` and `httpx-socks` against a global CDN (CacheFly).
* `module_exporter.py`: Generates a summary `report.md` and individual detailed reports in `result/node_details/`.
* `main.py`: Orchestrator implementing a two-phase pipeline (Filter -> Top-N Speedtest).
* `inputs/`: Local subscription input files, including the default `inputs/test.txt`.
* `examples/`: Manual test scripts and sing-box example configs.

## 🛠️ Architecture Constraints
- **Concurrency**: Managed via `asyncio.Semaphore` (Filter: 10+, Speedtest: 1-2).
- **Network**: Uses `aiohttp` for general IO and `httpx` (HTTP/1.1) for speed testing to ensure stability.
- **Robustness**: All IO wrapped in `try...except`; `sing-box` processes guaranteed to be killed in `finally` blocks.
- **Optimization**: Speed testing is limited to the top 3 valid nodes by default to conserve bandwidth.
- **Reporting**: Detailed per-node analysis includes visual trace paths and backbone identification.
