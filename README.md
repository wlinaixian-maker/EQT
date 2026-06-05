# EQT 智能制造过站报表

开发环境可直接运行 `python3 serve_dashboard.py`，或双击打包后的 `EQT-Dashboard`。

## 打包分发给同事（无需安装 Python）

在 **Mac 上打 Mac 包、Windows 上打 Windows 包**（需先安装 PyInstaller）：

```bash
pip3 install -r requirements-packaging.txt
python3 build_package.py
```

生成：

- `dist/EQT-Dashboard/` — 整个文件夹发给同事
- `release/EQT-Dashboard_mac_*.zip` — 压缩包

同事双击 `EQT-Dashboard`（Windows 为 `EQT-Dashboard.exe`），浏览器自动打开看板。

## 使用

1. **启动看板**：运行 `EQT-Dashboard` 或 `python3 serve_dashboard.py` → `http://localhost:8765`
2. **调整参数**：点「设置」→ 修改 REL 日目标、日期范围、各工站 PRB 固定目标 →「应用并刷新报表」
3. 设置会保存在本机浏览器（localStorage），下次打开仍生效

## 更新 Excel 数据后

导出文件放在 `exports/` 目录，然后执行：

```bash
cd /Users/forest.wangl/Desktop/EQT
python3 generate_index.py
```

会重新分析 Excel 并写入 `index.html` 内置数据。

## 报表结构

- **REL**：表头 `M03-M-L` `M03-M-R` `M03-E-L` `M03-E-R`，每行一个工站，右侧 **良率**
- **PRB**：同样 4 列 + 工站行 + 良率

## 分型规则

| 类型 | 规则 |
|------|------|
| REL | 工单含 REL，按 SN 末两位 BM/BL/BP/BN |
| PRB | 不含 REL，按 M03-L1-PRB 后 MAIN/MINI-(M\|E)-FATP-(L\|R) |

- REL 目标：日目标 × 周期天数（默认每天每型号 20）
- PRB 目标：各工站一次性固定数量（可在网页设置里改）

## 其他脚本（可选）

| 脚本 | 说明 |
|------|------|
| `generate_index.py` | 分析 exports 并更新 index.html（推荐） |
| `build_report_data.py` | 仅生成 report_data.json |
| `fetch_exports_from_har.py` | 从内网拉取 Excel 到 exports/（请求已内嵌在 `har_export_requests.py`） |
| `embed_har_exports.py` | 有新 HAR 时重新提取导出请求并更新 `har_export_requests.py` |
| `backfill_missing_stations.py` | 补拉归档中尚无数据的工站（完整日期范围） |
| `station_targets.json` | PRB 默认目标（generate_index 会读入网页内置默认） |

## 目录结构

| 目录/文件 | 内容 |
|-----------|------|
| `har/` | 18 个工站 HAR 文件（浏览器抓包原始记录） |
| `exports/` | 拉取/导出的 Excel（`.xlsx`） |
| `har_export_requests.py` | 从 HAR 提取的导出请求（供自动拉取使用） |

## 增量拉取（保留历史、缩短后续查询）

看板展示日期可以保持很长（如 `2026-01-05` ~ `2026-06-05`），但不必每次都拉全量。

**第一次（全量）**：设置好日期范围后正常刷新，会自动归档到 `data_archive/`：

```bash
python3 hourly_refresh.py
# 或显式归档：python3 hourly_refresh.py --freeze
```

**之后（增量）**：自动只拉最近 N 天（默认 7 天，可在 `dashboard_config.json` 的 `incremental.fetchDays` 修改），与归档合并后更新看板。

```json
"incremental": {
  "enabled": true,
  "frozenThrough": "2026-06-05",
  "fetchDays": 7
}
```

| 字段 | 含义 |
|------|------|
| `enabled` | 是否启用增量拉取 |
| `frozenThrough` | 已归档的最后日期，之后的数据才需要重新拉 |
| `fetchDays` | 每次自动刷新最多拉取的天数 |

## 更新 HAR 导出请求

日常自动拉取读 `har_export_requests.py`，不直接读 HAR。

若会话过期、拉取失败，把新 HAR 放到 `har/` 目录，然后：

```bash
python3 embed_har_exports.py
```

`har/` 中应有 18 个文件：

- `M03-EQT-CHECK-IN.har`
- `M03-EQT-Charge-Discharge.har`
- `M03-EQT-Basketball-Football.har`
- `M03-EQT-Coffee-Convenience Store.har`
- `M03-EQT-Commute.har`
- `M03-EQT-Gym.har`
- `M03-EQT-Home.har`
- `M03-EQT-Office.har`
- `M03-EQT-Quiet Room.har`
- `M03-EQT-Running Track.har`
- `M03-EQT-Stairs.har`
- `M03-EQT-Noise Room.har`
- `M03-EQT-Test.har`
- `M03-EQT-CHECK-OUT.har`
- `M03-CQA-Humdity test.har`
- `M03-EQT-Constant Temp Room.har`
- `M03-EQT-Beach.har`
- `M03-EQT-Other.har`
