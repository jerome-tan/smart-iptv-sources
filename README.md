# Smart IPTV Sources

Curated IPTV playlist and EPG publishing for Smart IPTV.

**Python 重写版** — Generator, validator, and refresh pipeline in Python.

## Layout

```
public/
  index.json          # 播放列表索引
  health.json         # 流健康报告
  version.json        # 版本信息
  playlists/
    stable-cn.m3u     # 国内精选频道 M3U
  epg/
    stable-cn.xml.gz  # EPG 节目单（Gzip）

sources/
  curation-rules.json       # 筛选规则（频道分组、黑名单、每频道上限）
  upstreams.json            # 上游 M3U 源列表
  channel-overrides.json    # 频道名别称映射
  channel-metadata.json     # 频道中文描述和标签
  epg-sources.json          # EPG XMLTV 源列表

lib/
  playlist_core.py   # M3U 解析、频道筛选、流探测、健康报告
  epg_core.py        # XMLTV EPG 获取和过滤

scripts/
  refresh.py         # 每日自动刷新脚本
  generate.mjs       # (旧版 JS 生成器，保留备用)
  validate.mjs       # (旧版 JS 验证器，保留备用)
```

## Quick Start

```bash
# 生成（不走流探测，快）
python3 generate.py

# 生成 + 流探测（连通性测试）
python3 generate.py --check-streams

# 验证输出
python3 validate.py

# 完整刷新流程
python3 scripts/refresh.py
```

## 代理配置

上游源拉取默认通过代理 `http://127.0.0.1:60397`（国内服务器需要）。
流连通性探测**不走代理**（直连测试真实可达性）。

```bash
# 禁用代理拉源
python3 generate.py --no-upstream-proxy

# 自定义代理
IPTV_UPSTREAM_PROXY=http://your-proxy:port python3 generate.py
```

## npm Scripts

| 命令 | 说明 |
|------|------|
| `npm run generate` | Python 生成（`generate.py`） |
| `npm run generate:check-streams` | Python 生成 + 流探测 |
| `npm run validate` | Python 验证（`validate.py`） |
| `npm run refresh` | 完整刷新 + git 提交 |
| `npm run generate:node` | 旧版 Node.js 生成器（备用） |
| `npm run validate:node` | 旧版 Node.js 验证器（备用） |

## Cron 定时刷新

每天凌晨 3 点（北京时间）自动执行：

```
python3 scripts/refresh.py  →  拉源(代理) → 筛选 → 测流(直连) → 验证 → git push
```

由 Hermes cron 调度（job: `smart-iptv-refresh`）。

## Cloudflare Pages

部署地址: `https://smart-iptv-sources.pages.dev`

```bash
npx wrangler pages deploy public --project-name smart-iptv-sources --branch main
```

## Channel Coverage

| 分组 | 内容 |
|------|------|
| 央视频道 | CCTV-1~17, CGTN 系列 |
| 地方卫视 | 北京/上海/湖南/浙江/江苏等 |
| 地方台 | 省市本地新闻、都市、公共频道 |
| 国际新闻 | BBC News, Sky News, France 24, DW, NHK World, Al Jazeera 等 |
| 科教探索 | National Geographic, Discovery, BBC Earth, Animal Planet, History 等 |
| 香港 | RTHK, TVB, ViuTV, Phoenix 等 |
| 英国 | BBC One/Two, ITV, Channel 4/5, Sky News 等 |
| 美国 | ABC, CBS, NBC, PBS, Bloomberg, CNBC 等 |

## Notes

This project does not host or retransmit video content. Playlists only reference publicly available live stream URLs.
