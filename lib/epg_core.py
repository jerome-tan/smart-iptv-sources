from __future__ import annotations

import gzip
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import httpx
import xmltodict


XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
GZIP_MAGIC = b"\x1f\x8b"
USER_AGENT = "SmartIPTVSourceBuilder/0.1"


async def fetch_xmltv(url: str, timeout_ms: int = 30000, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    close_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True, trust_env=True)
    try:
        response = await client.get(
            url,
            headers={
                "Accept": "application/xml, text/xml, application/gzip, application/octet-stream, */*",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout_ms / 1000,
        )
        payload = response.content
        ok = 200 <= response.status_code < 300
        return {
            "httpStatus": response.status_code,
            "ok": ok,
            "text": decode_xmltv_payload(payload, url) if ok else payload.decode("utf-8", errors="replace"),
        }
    finally:
        if close_client:
            await client.aclose()


def build_filtered_xmltv(documents: Iterable[Mapping[str, str]], entries: Iterable[Mapping[str, Any]], generated_at: str) -> Dict[str, Any]:
    keys = collect_playlist_guide_keys(entries)
    output_channel_ids: Set[str] = set()
    channels: List[str] = []
    programs: List[str] = []
    document_list = list(documents)

    for document in document_list:
        # ── 每个文档独立处理，避免跨文档 channel_id 覆盖 ──
        doc_channel_map: Dict[str, str] = {}
        doc_channels: List[str] = []

        try:
            xmltodict.parse(document["xml"])
        except Exception:
            pass

        for block in _extract_blocks(document["xml"], "channel"):
            channel_id = _xml_attribute(block, "id")
            if not channel_id:
                continue
            output_id = _resolve_output_id(block, keys)
            if output_id:
                doc_channel_map[channel_id] = output_id
                if output_id not in output_channel_ids:
                    output_channel_ids.add(output_id)
                    doc_channels.append(_rewrite_xml_attribute(block.strip(), "id", output_id))

        channels.extend(doc_channels)

        # 用本文档的 channel map 处理本文档的 programme
        for block in _extract_blocks(document["xml"], "programme"):
            channel_id = _xml_attribute(block, "channel")
            output_id = doc_channel_map.get(channel_id) if channel_id else None
            if output_id:
                programs.append(_rewrite_xml_attribute(block.strip(), "channel", output_id))

    body = "\n".join(
        [
            XML_DECLARATION,
            '<tv generator-info-name="Smart IPTV Sources" generator-info-url="https://smart-iptv-sources.pages.dev" source-info-name="Smart IPTV Sources" source-data-url="generated:%s">'
            % generated_at,
            *[_indent(block) for block in channels],
            *[_indent(block) for block in programs],
            "</tv>",
            "",
        ]
    )
    return {"channelCount": len(output_channel_ids), "programCount": len(programs), "xml": body}


def collect_playlist_guide_keys(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    ids: Set[str] = set()
    names: Set[str] = set()
    output_id_by_id: Dict[str, str] = {}
    output_id_by_name: Dict[str, str] = {}

    for entry in entries:
        output_id = _preferred_output_id(entry)
        tvg_id = (entry.get("attributes") or {}).get("tvg-id")
        if tvg_id:
            for guide_id in _guide_id_candidates(tvg_id):
                ids.add(guide_id)
                _remember(output_id_by_id, guide_id, output_id)

        for name in [
            (entry.get("attributes") or {}).get("tvg-name"),
            entry.get("displayName"),
            entry.get("name"),
            entry.get("normalizedName"),
        ]:
            for key in _guide_name_candidates(name):
                names.add(key)
                _remember(output_id_by_name, key, output_id)

    return {
        "ids": ids,
        "names": names,
        "outputIdById": output_id_by_id,
        "outputIdByName": output_id_by_name,
    }


def decode_xmltv_payload(payload: bytes, url: str = "") -> str:
    data = bytes(payload)
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data).decode("utf-8")
    return data.decode("utf-8")


def _guide_id_candidates(value: Any) -> List[str]:
    trimmed = str(value).strip()
    if not trimmed:
        return []
    candidates = [trimmed]
    without_quality = re.sub(r"@(UHD|FHD|HD|SD|LD)$", "", trimmed, flags=re.I)
    if without_quality != trimmed:
        candidates.append(without_quality)
    return candidates


def _preferred_output_id(entry: Mapping[str, Any]) -> Optional[str]:
    for value in [
        entry.get("displayName"),
        entry.get("normalizedName"),
        (entry.get("attributes") or {}).get("tvg-name"),
        entry.get("name"),
        (entry.get("attributes") or {}).get("tvg-id"),
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _remember(target: Dict[str, str], key: Optional[str], output_id: Optional[str]) -> None:
    if key and output_id and key not in target:
        target[key] = output_id


def _resolve_output_id(block: str, keys: Mapping[str, Any]) -> Optional[str]:
    channel_id = _xml_attribute(block, "id")
    if channel_id:
        for guide_id in _guide_id_candidates(channel_id):
            if guide_id in keys["outputIdById"]:
                return keys["outputIdById"][guide_id]

    for name in _child_texts(block, "display-name"):
        for key in _guide_name_candidates(name):
            output_id = keys["outputIdByName"].get(key)
            if output_id:
                return output_id
    return None


def _guide_name_candidates(value: Any) -> List[str]:
    key = _normalize_guide_name(value)
    if not key:
        return []
    aliases = [key]
    cctv_base_key = re.sub(
        r"^(cctv\d+\+?)(综合|财经|综艺|中文国际|体育|体育赛事|电影|国防军事|电视剧|纪录|科教|戏曲|社会与法|新闻|少儿|音乐|奥林匹克|农业农村)$",
        r"\1",
        key,
    )
    if cctv_base_key != key:
        aliases.append(cctv_base_key)
    return aliases


def _normalize_guide_name(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s*[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]", "", text, flags=re.I)
    text = re.sub(r"\s+([0-9]{3,4}[pi])$", "", text, flags=re.I)
    text = text.lower().replace("＋", "+").replace("plus", "+")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff+]", "", text)


def _extract_blocks(xml: str, tag_name: str) -> List[str]:
    pattern = re.compile(r"<%s\b[^>]*(?:/>|>[\s\S]*?</%s>)" % (re.escape(tag_name), re.escape(tag_name)), re.I)
    return [match.group(0) for match in pattern.finditer(xml)]


def _xml_attribute(block: str, attribute_name: str) -> Optional[str]:
    pattern = re.compile(r"\b%s\s*=\s*(['\"])([\s\S]*?)\1" % re.escape(attribute_name), re.I)
    match = pattern.search(block)
    return _decode_xml_entities(match.group(2).strip()) if match and match.group(2) else None


def _rewrite_xml_attribute(block: str, attribute_name: str, value: str) -> str:
    pattern = re.compile(r"\b%s\s*=\s*(['\"])([\s\S]*?)\1" % re.escape(attribute_name), re.I)
    return pattern.sub('%s="%s"' % (attribute_name, _escape_xml_attribute(value)), block, count=1)


def _child_texts(block: str, tag_name: str) -> List[str]:
    pattern = re.compile(r"<%s\b[^>]*>([\s\S]*?)</%s>" % (re.escape(tag_name), re.escape(tag_name)), re.I)
    values = []
    for match in pattern.finditer(block):
        value = _decode_xml_entities(_strip_tags(match.group(1)).strip())
        if value:
            values.append(value)
    return values


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _decode_xml_entities(value: str) -> str:
    return (
        value.replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _escape_xml_attribute(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _indent(block: str) -> str:
    return "\n".join("  " + line for line in block.split("\n"))
