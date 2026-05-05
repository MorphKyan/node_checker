# Vless Node Checker

Vless Node Checker 是一个本地 VLESS 节点检测与订阅增强工具。它可以解析订阅链接或本地订阅文件，启动 `sing-box` 隧道检测节点连通性，查询 IP 情报 API，生成节点画像和评分，并输出 Markdown 报告、增强订阅文件和本地 FastAPI 后端服务。

增强订阅只重写 VLESS URI 的 `#remark` 节点名，不修改 UUID、地址、端口、传输层、安全参数、SNI、path、host 等连接参数。

## 项目定位

这个项目适合作为一个本地优先的「订阅链接中转 + 节点画像增强 + 节点质量看板」服务。

很多订阅源里的节点名只包含国家或简单序号，不方便判断节点到底是机房、托管、VPN、Proxy、Tor、滥用风险，还是疑似家庭宽带。Vless Node Checker 的目标是把原始订阅转换为一个更可读、更可筛选的新订阅链接，并保留完整检测结果供 Web 面板或 API 查询。

推荐使用方式：

```text
原始订阅 URL
  -> Vless Node Checker 拉取和检测
  -> 生成节点画像、评分和增强节点名
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
🇯🇵 JP | 机房 | VPN | 78分 | 210ms
🇺🇸 US | 疑似家宽 | Clean | 92分 | 180ms
🇸🇬 SG | 托管机房 | Proxy | 63分 | 420ms
```

## 功能概览

- 解析 VLESS 订阅，支持明文 URI 列表和 base64 订阅内容。
- 检测 TCP Ping、TTFB、出口 IP、实际地区、ASN、绕路和骨干网信息。
- 查询 IP 情报并生成节点画像，包括网络分类、类型分类、风险分和证据。
- 根据延迟、风险和地区匹配结果计算节点总分。
- 对有效节点执行 Top-N 测速，默认 Top 3。
- 导出 Markdown 总览报告和每个节点的详细报告。
- 导出 compact/detailed 两种增强订阅，并同时提供 plain/base64 文件。
- 提供本地 FastAPI 后端，支持添加订阅、刷新检测、返回增强订阅和查询详细结果。
- 提供 React 控制台，用于订阅管理、任务监控、节点筛选、结果查看和增强订阅预览。

## 典型使用场景

### 1. 自用订阅增强器

把原始订阅 URL 添加到本地 API 服务后，项目会在后台检测节点，并输出一个新的增强订阅 URL。代理客户端只需要订阅增强 URL，就能看到包含地区、网络类型、风险类型、评分和延迟的节点名。

### 2. 节点质量筛选

当前增强订阅会按总分、TTFB 和测速结果排序，并默认只导出有效节点。后续可以继续扩展为策略化导出，例如只保留：

- 高于指定分数的节点。
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
  -> 解析 VLESS URI
  -> 为每个节点启动临时 sing-box 隧道
  -> 检测 TCP Ping、TTFB、出口 IP、地区、ASN、路由
  -> 查询 ipwho.is、ipapi.is、Scamalytics、proxycheck.io、Abstract API、IP2Location.io
  -> 聚合 NodeProfile 网络标签、类型标签、风险分和置信度
  -> 计算总分并筛选有效节点
  -> 对 Top-N 有效节点测速
  -> 保存最新结果到 SQLite
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

项目会使用本地 `sing-box.exe` 启动临时代理隧道。如果文件不存在，现有 setup 流程会尝试准备运行环境。

## 可选 API 配置

默认会查询 `ipwho.is`、免 key 的 `proxycheck.io` 和 keyless `IP2Location.io`。需要启用更多 IP 情报源时，通过环境变量配置，不要把密钥写入仓库：

```powershell
$env:IPAPI_KEY="your-ipapi-key"
$env:SCAMALYTICS_API="https://api13.scamalytics.com/v3/<account>/?key=<key>&ip={ip}"
$env:ABSTRACT_API_KEY="your-abstract-api-key"
$env:IP2LOCATION_KEY="your-ip2location-key"
$env:PROXYCHECK_KEY="your-proxycheck-key"
```

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
- `enhanced_compact.txt` 是紧凑命名的明文 VLESS URI 列表。
- `enhanced_compact_base64.txt` 是紧凑命名的 base64 订阅。
- `enhanced_detailed.txt` 是详细命名的明文 VLESS URI 列表。
- `enhanced_detailed_base64.txt` 是详细命名的 base64 订阅。

## 增强订阅命名

增强订阅复用当前评分和画像规则，不重新实现节点类型判断：

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
{flag} {geo} | {network} | {type} | {score}分 | {ttfb}ms

detailed:
{flag} {geo} | {network} | {type} | {score}分 | {ping}ms/{ttfb}ms | {speed}Mbps | {asn} | {original_name}
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

增强订阅从 SQLite 中保存的最新检测结果实时生成，不依赖 `result/subscriptions/*.txt` 文件。若订阅还没有完成的检测结果，会返回 `409 Conflict`。

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
      "enhanced_name_compact": "🇯🇵 JP | 机房 | Clean | 92分 | 210ms",
      "enhanced_name_detailed": "🇯🇵 JP | 机房 | Clean | 92分 | 80ms/210ms | 12.34Mbps | Example ASN | JP",
      "raw_uri": "vless://...",
      "is_valid": true,
      "reject_reason": "",
      "total_score": 92.0,
      "download_speed_mbps": 12.34,
      "probe": {
        "tcp_ping_ms": 80.0,
        "ttfb_ms": 210.0,
        "actual_ip": "203.0.113.10",
        "actual_geo": "JP",
        "asn_org": "Example ASN",
        "risk_score": 35.0,
        "network_labels": ["机房"],
        "type_labels": ["Clean"],
        "confidence": "high",
        "is_detour": false,
        "is_backbone": true,
        "backbone_info": "CN2",
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
  "speedtest_limit": 3,
  "force_probe": false
}
```

参数说明：

- `speedtest_limit`: 测速节点数量，默认 `3`；传 `0` 表示不测速。
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

## 本地存储

API 服务使用 SQLite 保存订阅、任务和最新检测结果：

```text
data/api.sqlite3
```

探测结果缓存保存在：

```text
cache/probe_cache.sqlite3
```

第一版只保存每个订阅的最新详细检测结果，不保存完整历史。

## 后续路线

适合优先推进的方向：

- 可配置命名模板，让用户决定哪些字段进入 compact 或 detailed 节点名。
- 增强订阅过滤参数，例如 `min_score`、`geo`、`network`、`exclude_type`、`max_ttfb`、`limit`。
- 保存历史检测结果，用于观察节点 IP、风险标签、评分和路线变化。
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
- 刷新检测会访问订阅 URL、IP 情报 API、测速 URL 和路由查询服务。
- 默认测速 Top 3 有效节点，用于控制检测时间和流量消耗。
- 当前 API 设计用于本机使用，不包含公网部署、鉴权、Docker 或反向代理配置。
