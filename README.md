# Node Checker

Node Checker 是一个支持多协议的本地节点分析网站与订阅增强工具，支持 VLESS、Hysteria2 和 Shadowsocks。它可以解析订阅链接或本地订阅文件，启动 `sing-box` 或 `Xray` 隧道检测节点连通性，查询可配置的 IP 情报 API，生成节点画像，并输出 Markdown 报告、增强订阅文件和本地 FastAPI 后端服务。

增强订阅只重写原始 URI 的 `#remark` 节点名，不修改密码、加密方法、UUID、地址、端口、传输层、安全参数、SNI、path、host 等连接参数。

## 项目定位

这个项目适合作为一个本地优先的「订阅链接中转 + 节点画像增强 + 节点质量看板」服务。

很多订阅源里的节点名只包含国家或简单序号，不方便判断节点到底是机房、托管、VPN、Proxy、Tor、滥用风险，还是疑似家庭宽带。Node Checker 的目标是把原始订阅转换为一个更可读、更可筛选的新订阅链接，并保留完整检测结果供 Web 面板或 API 查询。

推荐使用方式：

```text
原始订阅 URL
  -> Node Checker 拉取和检测
  -> 生成节点画像、风险证据和增强节点名
  -> 客户端订阅增强后的本地 URL
```

例如，原始节点名可能只有：

```text
JP
US
SG
```

增强后可以变成：

```text
🇯🇵 JP | 机房 | VPN | 风险 70 | 210ms
🇺🇸 US | 疑似家宽 | Clean | 风险 10 | 180ms
🇸🇬 SG | 托管机房 | Proxy | 风险 80 | 420ms
```

## 功能概览

- 解析 VLESS、Hysteria2（hy2 / hysteria2）和 Shadowsocks（ss）订阅，支持混合明文 URI 列表和 base64 订阅内容。
- SS 支持 SIP002（Base64URL 或明文转义凭据）、旧版整段 Base64、IPv6 和 SS2022；可通过 Xray / sing-box 检测，并导出增强 URI、sing-box 配置。SIP003 插件参数保留并传给 sing-box，Xray 遇到插件会明确拒绝。
- VLESS 的 TCP、WebSocket、gRPC 可用于两种内核；XHTTP 使用 Xray 检测，导出为 sing-box 配置时会返回 422，不会静默转换为 TCP。
- Hysteria2 的混淆、上下行带宽和 `ports` 端口跳跃参数由 sing-box 保留；Xray 检测遇到这些参数会明确拒绝，请选用 sing-box。
- 检测 TCP Ping、TTFB、出口 IP、实际地区、ASN，以及到节点入口的路径和骨干网络线索；绕路判断暂未实现。
- 查询 IP 情报并生成节点画像，包括网络分类、类型分类、风险分和证据。
- 节点是否有效仅由 TTFB 决定；IP 情报 API 只提供画像与风险证据。
- 普通刷新默认不测速；测速刷新显式指定每区域 Top-N。
- 导出 Markdown 总览报告和每个节点的详细报告。
- 导出 compact/detailed 两种增强订阅，并同时提供 plain/base64 文件。
- 提供本地 FastAPI 后端，支持添加订阅、刷新检测、返回增强订阅和查询详细结果。
- 提供 React 控制台，用于订阅管理、任务监控、节点筛选、结果查看和增强订阅预览。

## 典型使用场景

### 1. 自用订阅增强器

把原始订阅 URL 添加到本地 API 服务后，项目会在后台检测节点，并输出一个新的增强订阅 URL。代理客户端只需要订阅增强 URL，就能看到包含地区、网络类型、风险类型、风险值和延迟的节点名。

### 2. 节点质量筛选

当前增强订阅会按风险、TTFB 和测速结果排序，并默认只导出有效节点。后续可以继续扩展为策略化导出，例如只保留：

- 低于指定风险阈值的节点。
- 指定地区的节点。
- 家宽或疑似家宽节点。
- 排除 VPN、Proxy、Tor、滥用风险的节点。
- 低 TTFB 或高测速节点。

### 3. 节点画像和证据查看

节点名适合放关键摘要，完整证据适合放在 API 和 Web 控制台中查看。当前详细结果会展示出口 IP、ASN、风险分、网络标签、类型标签、置信度、绕路、骨干网和每个 API 的证据摘要。

### 4. 多订阅聚合基础

项目现在已经支持保存多个订阅和各自的检测结果。后续可以扩展为多源聚合器，把多个上游订阅统一检测、去重、排序、过滤，并发布一个干净的下游订阅。

## 工作流

```text
订阅 URL 或本地文件
  -> 拉取订阅文本
  -> 解析多协议节点 URI
  -> 为每个节点启动临时 sing-box 隧道
  -> 检测 TCP Ping、TTFB、出口 IP、地区、ASN、路由
  -> 查询当前已启用的 IP 情报站点
  -> 聚合 NodeProfile 网络标签、类型标签、风险分和置信度
  -> 以 TTFB 判断有效性，并保留 API 风险证据
  -> 对 Top-N 有效节点测速
  -> 保存最新结果到 JSON
  -> 生成报告、增强订阅和 API 响应
```

## 判断边界

IP 情报 API 对「家宽」「机房」「VPN」的判断不是绝对事实。项目会把多个来源的信号聚合为标签和置信度：

- `hosting=true`、`is_datacenter=true` 通常强烈指向机房或托管机房。
- `is_vpn=true`、`is_proxy=true`、`is_tor=true` 通常指向 VPN、代理或 Tor。
- ASN、公司类型、ISP 信息可能指向家宽、疑似家宽、移动网络或商宽。
- API 之间冲突时，应优先查看 `confidence` 和 `evidence`，不要只依赖节点名里的简短标签。

因此，增强订阅适合做日常筛选和快速识别；严肃判断应结合详细结果和证据。

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

项目会使用当前选择的 `sing-box` 或 `Xray` 启动临时代理隧道。Windows amd64 下缺少所选内核时会自动下载，请求超时为 30 秒；API 在后台线程中准备内核，期间仍可查看状态或取消任务。

## 可选 API 配置

默认会查询预置且已启用的站点。请在仪表盘的“API 站点”页中配置 URL 模板、权重、启用状态和本地 API Key；Key 不会由读取接口返回，也不会写入任务结果快照。

IP 情报查询通过当前被检测节点的 SOCKS 隧道发出，DNS 也经由代理解析；请求中的目标 IP 为该节点检测到的出口 IP。节点无法访问情报站点时不会回退到本机直连。

API 请求每次超时为 3 秒（订阅获取与 IPv6 查询也共用此值）。出口 IP 与情报查询遇到超时、连接错误、响应解析异常或 HTTP 5xx 时最多重试 1 次；HTTP 429 和其他 4xx 不重试，缺少风险字段也不重复请求。节点检测默认并发 10 个，可通过运行设置 `FILTER_CONCURRENCY` 调整；同一节点的已启用情报站点并发查询。

Net.Coffee 是主信息源，使用其网页查询接口 `https://ip.net.coffee/api/ip/lookup/{ip}`，无需 Key。网络分类、风险标签、风险分、国家和 ASN 组织优先采用其有效数据；缺失的维度由其他启用来源补充，主来源不可用时回退到原有聚合逻辑，所有来源证据仍保留。`isResidential` 和 `is_mobile` 用于识别家宽和移动网络，AI 判断保留在证据摘要中。原始信任分 `trust_score`（越高越可信）按 `100 - trust_score` 转为项目风险分。该接口尚无公开 API 文档或额度承诺，可能变更；已有配置可在“API 站点”页添加 `netcoffee` 类型的站点。

新配置默认禁用 ipwho.is、ipapi.is、Scamalytics 和 Abstract API；已有配置保持原值，可在“API 站点”页调整。节点详情按当前启用状态显示来源列和证据，历史结果也会隐藏已禁用的来源。更新后的解析逻辑会使旧探测缓存失效，已有检测结果需重新刷新才会采用新画像。

## CLI 使用

启动交互式检测：

```powershell
python main.py
```

程序会提示输入订阅 URL 或本地文件路径：

```text
Enter subscription URL or file path (leave empty for inputs/test.txt):
```

留空时默认读取：

```text
inputs/test.txt
```

请自行创建该文件并填入订阅内容；它已被 Git 忽略，避免提交节点凭证。

如果本地文件内容本身是单行 URL，程序会自动拉取该 URL 对应的订阅内容。

## CLI 输出

检测完成后会生成：

```text
result/report.md
result/node_details/
result/subscriptions/enhanced_compact.txt
result/subscriptions/enhanced_compact_base64.txt
result/subscriptions/enhanced_detailed.txt
result/subscriptions/enhanced_detailed_base64.txt
```

其中：

- `report.md` 是节点总览表。
- `result/node_details/` 包含每个节点的详细检测报告。
- `enhanced_compact.txt` 是紧凑命名的明文节点 URI 列表。
- `enhanced_compact_base64.txt` 是紧凑命名的 base64 订阅。
- `enhanced_detailed.txt` 是详细命名的明文节点 URI 列表。
- `enhanced_detailed_base64.txt` 是详细命名的 base64 订阅。

## 增强订阅命名

增强订阅复用当前画像规则，不重新实现节点类型判断：

- 网络分类来自 `NodeProfile.network_labels`。
- 类型分类来自 `NodeProfile.risk_labels`。
- 显示别名来自 `module_profile.DISPLAY_LABELS`。

当前别名包括：

```text
residential -> 家宽
likely_residential -> 疑似家宽
mobile -> 移动网络
business -> 商宽
datacenter -> 机房
hosting -> 托管机房
clean -> Clean
vpn -> VPN
proxy -> Proxy
tor -> Tor
abuser -> 滥用
unknown -> 未知
```

默认模板：

```text
compact:
{flag} {geo} | {network} | {type} | 风险 {risk} | {ttfb}ms

detailed:
{flag} {geo} | {network} | {type} | 风险 {risk} | {ping}ms/{ttfb}ms | {speed}Mbps | {asn} | {original_name}
```

字段为空时会自动降级，避免输出空分隔符。重复节点名会追加 `#2`、`#3` 等后缀。

## 后端 API

启动本地 API 服务：

```powershell
python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

使用 `python -m uvicorn` 是为了避免 Windows 上 `uvicorn.exe` 不在 `PATH` 中的问题。

API 文档地址：

```text
http://127.0.0.1:8000/docs
```

第一版 API 默认只绑定 `127.0.0.1`，不做鉴权。

### 添加订阅

```http
POST /subscriptions
```

请求体：

```json
{
  "url": "https://example.com/sub",
  "name": "my-sub"
}
```

添加订阅后会立即创建后台检测任务。

响应示例：

```json
{
  "subscription_id": "sub_xxx",
  "job_id": "job_xxx",
  "status": "queued"
}
```

PowerShell 示例：

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/subscriptions `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"url":"https://example.com/sub","name":"my-sub"}'
```

### 获取订阅列表

```http
GET /subscriptions
```

响应示例：

```json
[
  {
    "id": "sub_xxx",
    "name": "my-sub",
    "url": "https://example.com/sub",
    "last_status": "completed",
    "node_count": 20,
    "valid_count": 12,
    "updated_at": 1710000000
  }
]
```

### 获取增强订阅

```http
GET /subscriptions/{subscription_id}/enhanced
```

Query 参数：

```text
mode=compact|detailed
format=base64|plain
valid_only=true|false
```

默认值：

```text
mode=compact
format=base64
valid_only=true
```

示例：

```text
http://127.0.0.1:8000/subscriptions/sub_xxx/enhanced
http://127.0.0.1:8000/subscriptions/sub_xxx/enhanced?format=plain&mode=detailed
```

增强订阅从 JSON 中保存的最新检测结果实时生成，不依赖 `result/subscriptions/*.txt` 文件。若订阅还没有完成的检测结果，会返回 `409 Conflict`。

### 获取详细检测结果

```http
GET /subscriptions/{subscription_id}/results
```

响应包含该订阅最近一次完成检测的所有节点详情：

```json
{
  "subscription_id": "sub_xxx",
  "status": "completed",
  "node_count": 20,
  "valid_count": 12,
  "updated_at": 1710000000,
  "nodes": [
    {
      "fingerprint": "...",
      "original_name": "JP",
      "enhanced_name_compact": "🇯🇵 JP | 机房 | Clean | 风险 10 | 210ms",
      "enhanced_name_detailed": "🇯🇵 JP | 机房 | Clean | 风险 10 | 80ms/210ms | 12.34Mbps | Example ASN | JP",
      "raw_uri": "vless://...",
      "is_valid": true,
      "reject_reason": "",
      "risk_score": 35.0,
      "download_speed_mbps": 12.34,
      "probe": {
        "tcp_ping_ms": 80.0,
        "ttfb_ms": 210.0,
        "actual_ip": "203.0.113.10",
        "actual_geo": "JP",
        "asn_org": "Example ASN",
        "profile": {
          "risk_score": 35.0,
          "network_labels": [{"label": "datacenter", "confidence": 0.9}],
          "risk_labels": [{"label": "clean", "confidence": 0.55}],
          "confidence": "high"
        },
        "is_detour": null,
        "is_backbone": null,
        "backbone_info": "",
        "route_target": "",
        "route_status": "not_measured",
        "trace_path": "",
        "evidence": ["ipwho.is: hosting=true"]
      }
    }
  ]
}
```

若订阅还没有完成的检测结果，会返回 `409 Conflict`。

### 手动刷新检测

```http
POST /subscriptions/{subscription_id}/refresh
```

请求体：

```json
{
  "speedtest_limit": 0,
  "force_probe": false
}
```

参数说明：

- `speedtest_limit`: 每区域测速数量；默认 `0`，普通刷新不测速。
- `force_probe`: 是否跳过探测缓存重新检测；完成后仍会写入缓存。

同一个订阅同时只允许一个 `queued` 或 `running` 的刷新任务。重复刷新请求会返回当前已有任务，避免重复启动隧道和测速。

### 获取任务状态

```http
GET /jobs/{job_id}
```

响应示例：

```json
{
  "job_id": "job_xxx",
  "subscription_id": "sub_xxx",
  "status": "running",
  "phase": "filter",
  "processed_nodes": 8,
  "total_nodes": 20,
  "error": null,
  "created_at": 1710000000,
  "started_at": 1710000001,
  "finished_at": null
}
```

常见状态：

```text
queued
running
completed
failed
```

常见阶段：

```text
queued
fetch
filter
speedtest
completed
failed
```

## Docker 与 SSH 部署

先在 `frontend/` 运行 `npm ci`、`npm run build`，再在项目根目录运行：

```sh
docker compose up -d --build --wait
```

Compose 仅映射 `127.0.0.1:8000`，数据继续保存在 `/mnt/cache/appdata/node-checker`。
远程访问请通过 SSH 转发：`ssh -L 8000:127.0.0.1:8000 用户@服务器`，然后打开 `http://127.0.0.1:8000`。
构建时 `.dockerignore` 排除订阅、报告、缓存、Git 历史和本地环境，保留前端构建产物。

`deploy.py` 需要本地安装 `paramiko`，远端安装 Docker Compose v2（支持 `--wait`）和 `unzip`。
运行前设置 `DEPLOY_HOST`、`DEPLOY_USER`，可选 `DEPLOY_PORT`；默认使用 SSH 密钥或代理，也可通过 `DEPLOY_PASSWORD` 传入密码。
远端用户须有 `/root/node-checker`、数据目录和 Docker 的访问权限；服务器主机密钥须预先核实并加入本机 `known_hosts`。
脚本先构建再替换容器，任何远程命令失败都会终止；容器通过健康检查后才报告成功。
旧版脚本内的密码已移除，但 Git 历史仍可能包含该凭据，必须在服务器上轮换，并清理含旧凭据的分发镜像或归档。

## 本地存储

API 服务使用 `DATA_DIR`（默认 `data/`）中的 JSON 保存订阅、任务和最新检测结果：

```text
data/config.json
data/results/{subscription_id}.json
data/jobs/{job_id}.json
```

探测结果缓存保存在：

```text
data/probe-cache/{cache_key}.json
```

第一版只保存每个订阅的最新详细检测结果，不保存完整历史。
配置文件损坏或不可读时会报错并保留原文件；只有文件不存在时才生成默认配置。

## 后续路线

适合优先推进的方向：

- 可配置命名模板，让用户决定哪些字段进入 compact 或 detailed 节点名。
- 增强订阅过滤参数，例如 `max_risk`、`geo`、`network`、`exclude_type`、`max_ttfb`、`limit`。
- 保存历史检测结果，用于观察节点 IP、风险标签和路线变化。
- 多订阅合并、去重、统一排序和策略化导出。
- 前端展示每个 API 的原始判断差异，帮助识别 API 冲突和低置信度结果。
- 为公网或共享部署增加访问 token、日志脱敏、限流、后台定时刷新和部署配置。

当前项目默认是本机工具。如果要暴露到公网，必须先补鉴权和隐私保护，因为原始订阅 URL、节点 UUID、出口 IP 和检测结果都属于敏感信息。

## 测试

运行全部测试：

```powershell
python -m unittest discover -s tests
```

测试覆盖：

- 节点画像和 Markdown 报告。
- 增强订阅 URI 重命名、排序、过滤、去重、截断和 base64 输出。
- API 创建订阅、刷新任务、任务状态、增强订阅和详细结果查询。

## 运行注意事项

- 检测会启动 `sing-box` 子进程，并在完成后清理。
- 刷新先查询缓存（强制探测绕过缓存），未命中时启动代理内核，先通过代理访问 `TTFB_TARGET_URL` 验活；收到 2xx/3xx 响应并读到首字节或响应结束即成功，失败最多尝试两次。失败节点跳过其余采集和测速。TTFB 记录首次成功的耗时，不再取三次平均；此结果只代表该检测目标的可达性。
- 验活成功后并行采集 TCP Ping、IPv6、IP 情报和入口路径；启用测速时仍按“有效节点粗测 → 每区域 Top-N 精测”执行。
- 入口路径使用 Windows 自带 `tracert` 或 Linux `traceroute`（Docker 镜像已安装），系统命令最多运行 20 秒、最多 30 跳，超时保留已返回的路径；同一次刷新内相同采样入口共用探测，最多并发两个路由命令。
- 逐跳公网 IP 通过 RIPEstat `network-info` 查询 ASN（每请求默认 3 秒，最多并发四个，同次刷新复用）；只发送已观测到的公网路由 IP，不发送订阅或节点凭据。已知 ASN 规则覆盖电信 163/CN2、联通 169/9929/国际、移动/CMI/CMIN2、NTT、Cogent。没有 ASN 时，对 APNIC 登记为 CN2-BB 的 `59.43.0.0/16` 补充 IP 段依据，不推造 ASN。命中中间跳时 `is_backbone=true`，否则为 `null`（未知）；不区分 CN2 GIA/GT 等商业产品。绕路字段仍为 `null`。
- 路径仅代表服务运行主机到单个采样入口 IP 的系统路由观测（Windows ICMP、Linux UDP）；不代表中转链路、出口或回程。域名可能解析到多个 IP，代理内核也可能选用不同 IP/协议路径；ICMP/UDP 被过滤或 ASN 服务不可达时保留未知，不据此判节点失效。
- 出口 IP 查询失败时保留未知，情报缺失不视为 Clean；情报异常不会覆盖已测得的 TTFB。旧版情报结果需重新刷新后更新。
- 过滤与测速并发限制由同一后端进程的所有刷新任务共享。
- 默认普通刷新不测速；测速刷新由用户输入每区域数量，并可选择强制探测。
- 测速刷新先用现有 `SPEEDTEST_URL` 下载包粗筛全部有效节点（受 `SPEEDTEST_MAX_M` 和 `SPEEDTEST_TIMEOUT` 限制，默认最多统计 10 MiB；文件较小时下载完成即结束），再按粗测速为每区域选出指定数量，使用 Cloudflare `https://speed.cloudflare.com/__down?bytes=100000000` 精测，最多统计 100 MB（十进制）。粗筛失败的节点不进入精测；未入围节点不显示粗测速作为最终速度。
- 两轮测速均从收到响应头后开始计时，在下载停止时结束，排除建连、TLS、首字节等待和连接清理耗时；速度单位为十进制 Mbps。下载阶段最多持续 `SPEEDTEST_TIMEOUT` 秒（默认 10 秒），到达时间或字节上限即停止。两轮共享现有测速并发限制；提高并发可能因共享本机带宽而低估单节点速度。
- 当前 API 设计用于本机使用；Docker 默认只映射本机端口，公网或共享部署仍须另行加入鉴权。
