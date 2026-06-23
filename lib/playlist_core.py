from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urljoin

import httpx


DECORATIVE_RESOLUTION_PATTERN = re.compile(r"\s*[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]", re.I)
RESOLUTION_PATTERN = re.compile(
    r"[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]|\s([0-9]{3,4}[pi])(?:\s|$)|(?:^|\s)(4K)(?:\s|$)",
    re.I,
)
NOT_24X7_PATTERN = re.compile(r"\[\s*not\s*24\s*/\s*7\s*\]", re.I)
DEFAULT_BLOCKED_KEYWORDS = ["adult", "xxx", "porn", "博彩", "成人"]

USER_AGENT = "SmartIPTVSourceBuilder/0.1"
M3U_ACCEPT = "application/x-mpegURL, application/vnd.apple.mpegurl, text/plain, */*"


def parse_m3u(content: str, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    lines = content.replace("\r", "").split("\n")
    entries = []
    pending_extinf = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            pending_extinf = line
            continue
        if line.startswith("#") or not pending_extinf:
            continue

        attributes = _parse_extinf_attributes(pending_extinf)
        name = _parse_extinf_name(pending_extinf)
        group_title = attributes.get("group-title", "")
        normalized_name = normalize_channel_name(name)
        entries.append(
            {
                "attributes": attributes,
                "groupTitle": group_title,
                "isNot24x7": bool(NOT_24X7_PATTERN.search(name)),
                "name": name,
                "normalizedName": normalized_name,
                "rawExtinf": pending_extinf,
                "resolution": parse_resolution(name),
                "sourceId": source.get("id"),
                "sourceName": source.get("name"),
                "sourcePriority": source.get("priority", 0),
                "sourceRegion": source.get("region", ""),
                "url": line,
            }
        )
        pending_extinf = None

    return entries


# ── 拼音→中文归一化映射 ──
_PINYIN_MAP: Dict[str, str] = {}

def _build_pinyin_map() -> Dict[str, str]:
    """构建拼音→中文映射表（只构建一次）"""
    if _PINYIN_MAP:
        return _PINYIN_MAP
    # 省份/直辖市/自治区
    regions = {
        "beijing": "北京", "shanghai": "上海", "tianjin": "天津", "chongqing": "重庆",
        "guangdong": "广东", "zhejiang": "浙江", "jiangsu": "江苏", "shandong": "山东",
        "sichuan": "四川", "fujian": "福建", "henan": "河南", "hubei": "湖北",
        "hebei": "河北", "liaoning": "辽宁", "jilin": "吉林", "heilongjiang": "黑龙江",
        "hunan": "湖南", "anhui": "安徽", "jiangxi": "江西", "guangxi": "广西", "guizhou": "贵州",
        "yunnan": "云南", "hainan": "海南", "gansu": "甘肃", "shaaxi": "陕西",
        "shaanxi": "陕西", "shanxi": "山西", "xinjiang": "新疆", "xizang": "西藏",
        "ningxia": "宁夏", "qinghai": "青海", "neimenggu": "内蒙古", "nei menggu": "内蒙古",
    }
    # 城市
    cities = {
        "shenzhen": "深圳", "guangzhou": "广州", "nanjing": "南京", "hangzhou": "杭州",
        "wuhan": "武汉", "chengdu": "成都", "xian": "西安", "haerbin": "哈尔滨",
        "changchun": "长春", "shenyang": "沈阳", "dalian": "大连", "qingdao": "青岛",
        "xiamen": "厦门", "ningbo": "宁波", "changsha": "长沙", "suzhou": "苏州",
        "wuxi": "无锡", "dongguan": "东莞", "yantai": "烟台", "shaoxing": "绍兴",
        "jiaxing": "嘉兴", "huzhou": "湖州", "foshan": "佛山", "wenzhou": "温州",
    }
    # 频道类型后缀 + 英文→中文映射
    types = {
        "news": "新闻", "xinwen": "新闻",
        "sports": "体育", "tiyu": "体育",
        "children": "少儿", "shaoer": "少儿", "kids": "少儿", "junior": "少儿",
        "economy": "经济", "jingji": "经济",
        "entertainment": "综艺", "yule": "娱乐",
        "movie": "影视", "dianying": "电影", "film": "影视",
        "public": "公共", "gonggong": "公共",
        "life": "生活", "shenghuo": "生活",
        "education": "教育", "jiaoyu": "教育",
        "science": "科教", "kejiao": "科教",
        "satellite": "卫视", "weishi": "卫视",
        "comprehensive": "综合", "zonghe": "综合",
        "agriculture": "农业", "nongye": "农业",
        "rural": "乡村", "xiangcun": "乡村",
        "culture": "文化", "wenhua": "文化",
        "travel": "旅游", "lvyou": "旅游",
        "drama": "戏曲", "opera": "戏曲",
        "variety": "综艺",
        # CCTV 子频道英文名
        "health": "卫生健康", "billiards": "台球", "golf": "高尔夫",
        "tennis": "网球", "nostalgia": "怀旧", "theater": "剧场",
        "storm": "风云", "football": "足球", "weapon": "兵器",
        "technology": "科技", "women": "女性", "fashion": "时尚",
        "world": "世界", "geography": "地理",
        # 纪录片/科教频道
        "national": "国家", "geographic": "地理", "discovery": "探索",
        "animal": "动物", "planet": "星球", "earth": "地球",
        "history": "历史", "smithsonian": "史密森尼",
        "nature": "自然", "wild": "野生", "love": "爱",
        # 方向/语言
        "hd": "高清", "east": "东", "west": "西", "north": "北", "south": "南",
        "china": "中国", "america": "美洲", "asia": "亚洲", "europe": "欧洲",
        "international": "国际", "business": "商业", "global": "环球",
        "english": "英语", "francais": "法语", "french": "法语",
        "espanol": "西语", "spanish": "西语",
        "biz": "财经",
        # 品牌
        "disney": "迪士尼", "bloomberg": "彭博", "fox": "福克斯",
        "weather": "天气", "nick": "尼克", "nickelodeon": "尼克",
        "channel": "", "tv": "", "television": "",
    }
    _PINYIN_MAP.update(regions)
    _PINYIN_MAP.update(cities)
    _PINYIN_MAP.update(types)
    # CCTV 变体
    _PINYIN_MAP["cctv"] = "CCTV"
    return _PINYIN_MAP


def _normalize_pinyin_name(name: str) -> str:
    """将拼音频道名归一化为中文，方便后续白名单匹配"""
    pinyin_map = _build_pinyin_map()
    # 分词（按空白/数字/分隔符切分，不保留分隔符）
    tokens = [t for t in re.split(r"[\s\-/]+", name) if t]
    result: List[str] = []
    for token in tokens:
        token_lower = token.lower().strip()
        # 保留已有的中文字符
        if re.search(r"[\u4e00-\u9fff]", token):
            result.append(token)
            continue
        # 查拼音映射
        if token_lower in pinyin_map:
            mapped = pinyin_map[token_lower]
            if mapped:
                result.append(mapped)
        else:
            result.append(token)
    # 用空格连接（保留英文分词边界）
    normalized = " ".join(result)
    return normalized.strip() or name


def _bilingual_name(original: str, normalized: str) -> str:
    """生成双语展示名。只对含英文且翻译后有中文的国外频道做双语。"""
    if not original or original == normalized:
        return normalized
    # 检查：原始名含英文（至少3个连续字母）
    has_ascii = bool(re.search(r"[A-Za-z]{3,}", original))
    if not has_ascii:
        return normalized
    # 检查：归一化后含中文
    has_cn = bool(re.search(r"[\u4e00-\u9fff]", normalized))
    if not has_cn:
        return normalized
    # 去掉分隔符后比较（CCTV-1 vs CCTV1 不应出双语）
    original_compact = re.sub(r"[\s\-]+", "", original).lower()
    norm_compact = re.sub(r"[\s\-]+", "", normalized).lower()
    if original_compact == norm_compact:
        return normalized
    # 生成双语：中文部分去空格，英文部分保留
    cn = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    cn = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z])", "", cn)
    cn = re.sub(r"(?<=[A-Za-z])\s+(?=[\u4e00-\u9fff])", "", cn)
    return f"{original} ({cn})"


def curate_entries(
    entries: Iterable[Mapping[str, Any]],
    overrides: Optional[Mapping[str, Any]] = None,
    options: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    overrides = overrides or {}
    options = options or {}
    settings = {
        "blockedKeywords": DEFAULT_BLOCKED_KEYWORDS,
        "includeNot24x7": False,
        "keepUnknownResolution": True,
        "maxSourcesPerChannel": 3,
        "minResolution": 720,
    }
    settings.update(options)

    blacklist_names = set(overrides.get("blacklistNames") or [])
    blacklist_urls = {_normalize_url(url) for url in overrides.get("blacklistUrls") or []}
    aliases = overrides.get("aliases") or {}
    preferred_urls = overrides.get("preferredUrls") or {}
    rejected = {
        "blacklistedName": 0,
        "blacklistedUrl": 0,
        "blockedKeyword": 0,
        "channelLimit": 0,
        "duplicateUrl": 0,
        "invalidUrl": 0,
        "lowResolution": 0,
        "notSelectedRegion": 0,
        "not24x7": 0,
    }
    seen_urls = set()
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for original in entries:
        entry = dict(original)
        url_key = _normalize_url(entry.get("url", ""))
        normalized_name = aliases.get(entry.get("normalizedName"), entry.get("normalizedName"))
        raw_name = str(normalized_name or "").strip()
        # 拼音→中文归一化（用于分类）
        display_name = _normalize_pinyin_name(raw_name)
        # 双语展示名：英文原名 + 中文翻译
        display_label = _bilingual_name(raw_name, display_name)

        if not _is_http_url(entry.get("url", "")):
            rejected["invalidUrl"] += 1
            continue
        if url_key in blacklist_urls:
            rejected["blacklistedUrl"] += 1
            continue
        if entry.get("normalizedName") in blacklist_names or display_name in blacklist_names:
            rejected["blacklistedName"] += 1
            continue
        if not settings["includeNot24x7"] and entry.get("isNot24x7"):
            rejected["not24x7"] += 1
            continue
        if entry.get("resolution") is not None and entry["resolution"] < settings["minResolution"]:
            rejected["lowResolution"] += 1
            continue
        if entry.get("resolution") is None and not settings["keepUnknownResolution"]:
            rejected["lowResolution"] += 1
            continue
        if _contains_blocked_keyword(
            "%s %s" % (entry.get("name", ""), entry.get("groupTitle", "")),
            settings["blockedKeywords"],
        ):
            rejected["blockedKeyword"] += 1
            continue
        if url_key in seen_urls:
            rejected["duplicateUrl"] += 1
            continue
        seen_urls.add(url_key)

        group_info = _classify_channel(display_name, entry, settings.get("channelGroups"))
        if not group_info:
            rejected["notSelectedRegion"] += 1
            continue
        metadata = _channel_metadata_for(display_name, entry, settings.get("channelMetadata"))

        enriched = dict(entry)
        enriched.update(
            {
                "displayName": display_label,
                "displayGroup": group_info["name"],
                "groupRank": group_info["rank"],
                "score": _score_entry(entry, preferred_urls),
                "sortKey": group_info["sortKey"],
                "smartDescription": metadata.get("description") if metadata else None,
                "smartTags": metadata.get("tags") if metadata else None,
            }
        )
        grouped.setdefault(display_name, []).append(enriched)

    accepted = []
    # 记录每个分组首次出现时的双语标签
    group_labels: Dict[str, str] = {}
    for channel_name, channel_entries in grouped.items():
        sorted_entries = sorted(channel_entries, key=_entry_sort_key)
        kept = sorted_entries[: settings["maxSourcesPerChannel"]]
        rejected["channelLimit"] += max(0, len(sorted_entries) - len(kept))
        # 用该组首个条目的双语标签
        label = group_labels.get(channel_name) or kept[0].get("displayName", channel_name)
        group_labels[channel_name] = label
        for entry in kept:
            item = dict(entry)
            item["displayName"] = label
            accepted.append(item)

    return {"entries": sorted(accepted, key=_output_sort_key), "rejected": rejected}


async def fetch_text(url: str, timeout_ms: int = 15000, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    close_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True, trust_env=True)
    try:
        response = await client.get(
            url,
            headers={"Accept": M3U_ACCEPT, "User-Agent": USER_AGENT},
            timeout=timeout_ms / 1000,
        )
        return {"httpStatus": response.status_code, "ok": 200 <= response.status_code < 300, "text": response.text}
    finally:
        if close_client:
            await client.aclose()


async def probe_stream(url: str, timeout_ms: int = 8000, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    checked_at = _iso_now()
    close_client = client is None
    timeout = httpx.Timeout(timeout_ms / 1000)
    client = client or httpx.AsyncClient(follow_redirects=True, trust_env=False, timeout=timeout)
    try:
        response = await _probe_stream_url(url, client, depth=0)
        result = {"checkedAt": checked_at}
        result.update(response)
        return result
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return {"checkedAt": checked_at, "error": "timeout", "status": "timeout"}
    except Exception as error:
        return {"checkedAt": checked_at, "error": str(error), "status": "network-error"}
    finally:
        if close_client:
            await client.aclose()


async def probe_streams(entries: Iterable[Mapping[str, Any]], timeout_ms: int = 8000, concurrency: int = 8) -> Dict[str, Dict[str, Any]]:
    checks: Dict[str, Dict[str, Any]] = {}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    timeout = httpx.Timeout(timeout_ms / 1000)

    async with httpx.AsyncClient(follow_redirects=True, trust_env=False, timeout=timeout) as client:
        async def worker(entry: Mapping[str, Any]) -> None:
            async with semaphore:
                checks[entry["url"]] = await probe_stream(entry["url"], timeout_ms=timeout_ms, client=client)

        await asyncio.gather(*(worker(entry) for entry in entries))
    return checks


def select_published_entries(
    entries: Iterable[Mapping[str, Any]],
    stream_checks: Mapping[str, Mapping[str, Any]],
    options: Optional[Mapping[str, Any]] = None,
) -> List[Mapping[str, Any]]:
    options = options or {}
    if not options.get("publishOnlyHealthy", False):
        return list(entries)
    return [entry for entry in entries if (stream_checks.get(entry["url"]) or {}).get("status") == "ok"]


def format_m3u(entries: Iterable[Mapping[str, Any]]) -> str:
    lines = ["#EXTM3U"]
    for entry in entries:
        attributes = dict(entry.get("attributes") or {})
        attributes["tvg-name"] = attributes.get("tvg-name") or entry.get("displayName")
        attributes["group-title"] = (
            entry.get("displayGroup")
            or entry.get("groupTitle")
            or attributes.get("group-title")
            or "未分组"
        )
        attributes["x-smart-source"] = entry.get("sourceId")
        if entry.get("smartDescription"):
            attributes["x-smart-description"] = entry.get("smartDescription")
        if isinstance(entry.get("smartTags"), list) and entry.get("smartTags"):
            attributes["x-smart-tags"] = ",".join(str(tag) for tag in entry["smartTags"])
        if entry.get("resolution") is not None:
            attributes["x-smart-resolution"] = str(entry["resolution"])
        lines.append('#EXTINF:-1 %s,%s' % (_format_attributes(attributes), entry.get("displayName", "")))
        lines.append(str(entry.get("url", "")))
    return "\n".join(lines) + "\n"


def build_health_report(data: Mapping[str, Any]) -> Dict[str, Any]:
    generated_at = data["generatedAt"]
    stream_checks = data.get("streamChecks") or {}
    curated_entries = data["curatedEntries"]
    published_entries = data.get("publishedEntries") or curated_entries
    upstream_results = data["upstreamResults"]
    published_urls = {entry["url"] for entry in published_entries}

    streams = []
    for entry in curated_entries:
        result = stream_checks.get(entry["url"]) or {"status": "unchecked", "checkedAt": generated_at}
        streams.append(
            {
                "channelName": entry.get("displayName"),
                "groupTitle": entry.get("displayGroup") or entry.get("groupTitle") or "未分组",
                "httpStatus": result.get("httpStatus"),
                "published": entry["url"] in published_urls,
                "resolution": entry.get("resolution"),
                "sourceId": entry.get("sourceId"),
                "status": result.get("status"),
                "url": entry.get("url"),
                "checkedAt": result.get("checkedAt") or generated_at,
                "error": result.get("error"),
            }
        )

    return {
        "schemaVersion": 1,
        "updatedAt": generated_at,
        "summary": {
            "channels": len({entry.get("displayName") for entry in curated_entries}),
            "publishedChannels": len({entry.get("displayName") for entry in published_entries}),
            "publishedStreams": len(published_entries),
            "streams": _count_statuses(streams),
            "upstreams": _count_statuses(upstream_results),
        },
        "upstreams": [
            {
                "id": result.get("id"),
                "name": result.get("name"),
                "status": result.get("status"),
                "httpStatus": result.get("httpStatus"),
                "channelCount": result.get("channelCount", 0),
                "acceptedCount": result.get("acceptedCount", 0),
                "error": result.get("error"),
            }
            for result in upstream_results
        ],
        "streams": streams,
    }


def normalize_channel_name(name: str) -> str:
    value = NOT_24X7_PATTERN.sub("", name)
    value = DECORATIVE_RESOLUTION_PATTERN.sub("", value)
    value = re.sub(r"\s+([0-9]{3,4}[pi])$", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([：:])", r"\1", value)
    return value.strip()


def parse_resolution(name: str) -> Optional[int]:
    best = None
    for match in RESOLUTION_PATTERN.finditer(name):
        token = next((group for group in match.groups() if group), "").upper()
        value = 2160 if token == "4K" else int(re.sub(r"[PI]", "", token))
        best = max(best or 0, value)
    return best


async def _probe_stream_url(url: str, client: httpx.AsyncClient, depth: int) -> Dict[str, Any]:
    is_playlist = _is_hls_url(url)
    headers = {"User-Agent": USER_AGENT}
    if is_playlist:
        headers["Accept"] = M3U_ACCEPT
    else:
        headers["Range"] = "bytes=0-2047"

    response = await _request_probe(client, url, headers, force_get=is_playlist)
    if not 200 <= response.status_code < 300:
        return {"httpStatus": response.status_code, "status": "http-error"}
    if not is_playlist or depth >= 2:
        return {"httpStatus": response.status_code, "status": "ok"}

    first_media_url = _find_first_media_url(response.text, url)
    if not first_media_url:
        return {"httpStatus": response.status_code, "status": "ok"}
    return await _probe_stream_url(first_media_url, client, depth + 1)


async def _request_probe(client: httpx.AsyncClient, url: str, headers: Mapping[str, str], force_get: bool = False) -> httpx.Response:
    if not force_get:
        try:
            response = await client.head(url, headers=headers)
            if response.status_code not in (405, 501):
                return response
        except httpx.HTTPError:
            pass
    return await client.get(url, headers=headers)


def _parse_extinf_attributes(extinf: str) -> Dict[str, str]:
    end = extinf.rfind(",")
    attribute_part = extinf if end == -1 else extinf[:end]
    return {match.group(1): match.group(2) for match in re.finditer(r'([\w-]+)="([^"]*)"', attribute_part)}


def _parse_extinf_name(extinf: str) -> str:
    comma_index = extinf.rfind(",")
    return "" if comma_index == -1 else extinf[comma_index + 1 :].strip()


def _normalize_url(url: str) -> str:
    return str(url).strip()


def _is_hls_url(url: str) -> bool:
    return bool(re.search(r"\.m3u8(?:[?#].*)?$", url, re.I))


def _find_first_media_url(playlist_text: str, playlist_url: str) -> Optional[str]:
    for raw_line in playlist_text.replace("\r", "").split("\n"):
        line = raw_line.strip()
        if line and not line.startswith("#"):
            return urljoin(playlist_url, line)
    return None


def _is_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", str(url).strip(), re.I))


def _contains_blocked_keyword(value: str, keywords: Iterable[str]) -> bool:
    normalized = value.lower()
    return any(str(keyword).lower() in normalized for keyword in keywords)


def _score_entry(entry: Mapping[str, Any], preferred_urls: Mapping[str, Any]) -> int:
    preferred = preferred_urls.get(entry.get("url"), 0)
    resolution_score = entry.get("resolution") or 800
    return preferred * 10000 + resolution_score + (entry.get("sourcePriority") or 0)


def _entry_sort_key(entry: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (-(entry.get("score") or 0), -(entry.get("resolution") or 0), entry.get("url") or "")


def _output_sort_key(entry: Mapping[str, Any]) -> Tuple[Any, ...]:
    group_rank = entry.get("groupRank")
    if group_rank is None:
        group_rank = _output_group_rank(entry.get("groupTitle"))
    sort_key = entry.get("sortKey")
    normalized_sort = tuple(sort_key) if sort_key else (999999,)
    return (
        group_rank,
        normalized_sort,
        entry.get("displayName") or "",
        _entry_sort_key(entry),
    )


def _classify_channel(display_name: str, entry: Mapping[str, Any], channel_groups: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not channel_groups:
        return {
            "name": entry.get("groupTitle") or "未分组",
            "rank": _output_group_rank(entry.get("groupTitle")),
            "sortKey": None,
        }

    for rule in channel_groups.get("rules") or []:
        if _matches_channel_rule(rule, display_name, entry):
            return {
                "name": rule.get("name"),
                "rank": _group_rank(rule.get("name"), channel_groups),
                "sortKey": _sort_key_for_rule(rule, display_name),
            }

    if entry.get("sourceRegion") in (channel_groups.get("restrictedSourceRegions") or []):
        return None

    if channel_groups.get("rejectUnmatched"):
        return None

    fallback_group = channel_groups.get("defaultGroup") or entry.get("groupTitle") or "未分组"
    return {"name": fallback_group, "rank": _group_rank(fallback_group, channel_groups), "sortKey": None}


def _channel_metadata_for(display_name: str, entry: Mapping[str, Any], channel_metadata: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    channels = (channel_metadata or {}).get("channels")
    if not isinstance(channels, dict):
        return None
    candidates = [
        display_name,
        entry.get("normalizedName"),
        entry.get("name"),
        (entry.get("attributes") or {}).get("tvg-name"),
    ]
    for candidate in filter(None, candidates):
        metadata = channels.get(candidate) or channels.get(_metadata_key(candidate))
        if metadata:
            return _normalize_channel_metadata(metadata)
    normalized_channels = {_metadata_key(key): metadata for key, metadata in channels.items()}
    for candidate in filter(None, candidates):
        metadata = normalized_channels.get(_metadata_key(candidate))
        if metadata:
            return _normalize_channel_metadata(metadata)
    return None


def _normalize_channel_metadata(metadata: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(metadata, dict):
        return None
    description = metadata.get("description").strip() if isinstance(metadata.get("description"), str) else ""
    tags = [str(tag).strip() for tag in metadata.get("tags", []) if str(tag).strip()] if isinstance(metadata.get("tags"), list) else []
    if not description and not tags:
        return None
    return {"description": description or None, "tags": tags}


def _metadata_key(value: Any) -> str:
    key = str(value).lower().replace("＋", "+").replace("plus", "+")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff+]", "", key)


def _matches_channel_rule(rule: Mapping[str, Any], display_name: str, entry: Mapping[str, Any]) -> bool:
    if rule.get("sourceRegions") and entry.get("sourceRegion") not in rule.get("sourceRegions"):
        return False
    fields = [display_name, entry.get("name"), (entry.get("attributes") or {}).get("tvg-name")]
    fields = [field for field in fields if field]
    haystack = " ".join(fields)
    for pattern in rule.get("patterns") or []:
        regex = re.compile(pattern, re.I | re.U)
        if any(regex.search(field) for field in fields) or regex.search(haystack):
            return True
    return False


def _group_rank(group_name: str, channel_groups: Mapping[str, Any]) -> int:
    group_order = channel_groups.get("groupOrder") or []
    return group_order.index(group_name) if group_name in group_order else 100


def _sort_key_for_rule(rule: Mapping[str, Any], display_name: str) -> Optional[List[Any]]:
    if rule.get("sort") == "cctv":
        return _cctv_sort_key(display_name)
    return None


def _cctv_sort_key(display_name: str) -> List[Any]:
    match = re.search(r"^CCTV[-\s]*(\d+)", display_name, re.I)
    if match:
        number = int(match.group(1))
        if re.search(r"4K", display_name, re.I):
            return [number, 0.1, display_name]
        if re.search(r"America", display_name, re.I):
            return [number, 0.2, display_name]
        if re.search(r"Europe", display_name, re.I):
            return [number, 0.3, display_name]
        return [number, 0, display_name]
    if re.search(r"^CGTN", display_name, re.I):
        return [100, 0, display_name]
    return [999, 0, display_name]


def _output_group_rank(group_title: Optional[str]) -> int:
    group = group_title or ""
    if re.search(r"央视|CCTV", group, re.I):
        return 0
    if re.search(r"卫视", group):
        return 1
    if re.search(r"新闻", group):
        return 2
    if re.search(r"体育", group):
        return 3
    if re.search(r"少儿|动漫", group):
        return 4
    if re.search(r"纪录", group):
        return 5
    if re.search(r"电影|电视剧|影视", group):
        return 6
    if re.search(r"音乐", group):
        return 7
    return 20


def _format_attributes(attributes: Mapping[str, Any]) -> str:
    parts = []
    for key, value in attributes.items():
        if value is not None and value != "":
            parts.append('%s="%s"' % (key, html.escape(str(value), quote=True)))
    return " ".join(parts)


def _count_statuses(items: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        key = _status_key(item.get("status"))
        counts[key] = counts.get(key, 0) + 1
    return {
        "ok": counts.get("ok", 0),
        "httpError": counts.get("httpError", 0),
        "networkError": counts.get("networkError", 0),
        "timeout": counts.get("timeout", 0),
        "unchecked": counts.get("unchecked", 0),
    }


def _status_key(status: Optional[str]) -> str:
    if status == "http-error":
        return "httpError"
    if status == "network-error":
        return "networkError"
    return status or "unchecked"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
