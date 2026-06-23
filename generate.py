from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

from lib.epg_core import build_filtered_xmltv, fetch_xmltv
from lib.playlist_core import (
    build_health_report,
    curate_entries,
    fetch_text,
    format_m3u,
    parse_m3u,
    probe_streams,
    select_published_entries,
)


ROOT = Path.cwd()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def write_json(relative_path: str, value: Any) -> None:
    write_file(relative_path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_file(relative_path: str, value: str | bytes) -> None:
    file_path = ROOT / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        file_path.write_bytes(value)
    else:
        file_path.write_text(value, encoding="utf-8")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def format_upstream_summary(result: Mapping[str, Any]) -> str:
    http_status = f"({result['httpStatus']})" if result.get("httpStatus") else ""
    return f"{result.get('id')}:{result.get('status')}{http_status}"


async def load_upstream(source: Mapping[str, Any], timeout_ms: int, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        result = await fetch_text(source["url"], timeout_ms=timeout_ms, client=client)
        if not result["ok"]:
            return [], {
                "id": source.get("id"),
                "name": source.get("name"),
                "status": "http-error",
                "httpStatus": result.get("httpStatus"),
                "channelCount": 0,
                "acceptedCount": 0,
            }

        entries = parse_m3u(result["text"], source)
        return entries, {
            "id": source.get("id"),
            "name": source.get("name"),
            "status": "ok",
            "httpStatus": result.get("httpStatus"),
            "channelCount": len(entries),
            "acceptedCount": 0,
        }
    except (httpx.TimeoutException, asyncio.TimeoutError) as error:
        return [], {
            "id": source.get("id"),
            "name": source.get("name"),
            "status": "timeout",
            "channelCount": 0,
            "acceptedCount": 0,
            "error": str(error),
        }
    except Exception as error:
        return [], {
            "id": source.get("id"),
            "name": source.get("name"),
            "status": "network-error",
            "channelCount": 0,
            "acceptedCount": 0,
            "error": str(error),
        }


async def generate_epg(entries: list[Mapping[str, Any]], sources: list[Mapping[str, Any]], generated_at: str, timeout_ms: int, use_proxy: bool = True) -> dict[str, Any]:
    if not sources:
        raise RuntimeError("sources/epg-sources.json must contain at least one enabled EPG source")

    documents: list[dict[str, str]] = []
    errors: list[str] = []
    async with _make_client(use_proxy=use_proxy) as client:
        for source in sources:
            try:
                result = await fetch_xmltv(source["url"], timeout_ms=timeout_ms, client=client)
                if not result["ok"]:
                    errors.append(f"{source.get('id')}: HTTP {result.get('httpStatus')}")
                    continue
                documents.append({"id": str(source.get("id")), "xml": result["text"]})
            except (httpx.TimeoutException, asyncio.TimeoutError):
                errors.append(f"{source.get('id')}: timeout")
            except Exception as error:
                errors.append(f"{source.get('id')}: {error}")

    if not documents:
        raise RuntimeError(f"No EPG sources could be loaded. {'; '.join(errors)}")

    epg = build_filtered_xmltv(documents=documents, entries=entries, generated_at=generated_at)
    if epg["programCount"] == 0:
        loaded = ", ".join(document["id"] for document in documents)
        raise RuntimeError(f"Generated EPG contains no programs. Loaded sources: {loaded}")

    return {**epg, "sourceCount": len(documents)}


# 上游源代理配置（国内服务器需代理访问 GitHub/RawGitHub 等）
UPSTREAM_PROXY = os.environ.get("IPTV_UPSTREAM_PROXY", "http://127.0.0.1:60397")


def _proxy_mount() -> dict[str, httpx.AsyncHTTPTransport] | None:
    """需要代理时返回带代理的 mounts，否则返回 None（直连）"""
    if UPSTREAM_PROXY:
        return {"all://": httpx.AsyncHTTPTransport(proxy=UPSTREAM_PROXY)}
    return None


def _make_client(use_proxy: bool = True, timeout: float | None = None) -> httpx.AsyncClient:
    """创建 HTTP 客户端。use_proxy=True 时走上游代理拉数据，False 时直连。"""
    kwargs: dict[str, Any] = {"follow_redirects": True}
    if use_proxy and UPSTREAM_PROXY:
        kwargs["proxy"] = UPSTREAM_PROXY
    if timeout is not None:
        kwargs["timeout"] = timeout
    return httpx.AsyncClient(**kwargs)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Smart IPTV public artifacts.")
    parser.add_argument("--check-streams", action="store_true", help="Probe streams and optionally publish only healthy streams.")
    parser.add_argument("--no-upstream-proxy", action="store_true", help="Disable proxy for upstream source fetching.")
    args = parser.parse_args()

    generated_at = iso_now()
    check_streams = args.check_streams or os.environ.get("CHECK_STREAMS") == "true"
    upstream_timeout_ms = env_int("UPSTREAM_TIMEOUT_MS", 15000)
    stream_timeout_ms = env_int("STREAM_TIMEOUT_MS", 8000)
    stream_check_concurrency = env_int("STREAM_CHECK_CONCURRENCY", 8)

    use_proxy = not args.no_upstream_proxy and bool(UPSTREAM_PROXY)

    upstreams = read_json("sources/upstreams.json")
    epg_sources = read_json("sources/epg-sources.json")
    overrides = read_json("sources/channel-overrides.json")
    channel_metadata = read_json("sources/channel-metadata.json")
    rules = read_json("sources/curation-rules.json")

    enabled_sources = [source for source in upstreams["sources"] if source.get("enabled") is not False]
    enabled_epg_sources = [
        source for source in epg_sources["sources"] if source.get("enabled") is not False and source.get("url")
    ]

    # ── 拉取上游源：走代理 ──
    all_entries: list[dict[str, Any]] = []
    upstream_results: list[dict[str, Any]] = []
    print(f"Fetching {len(enabled_sources)} upstream sources via {'proxy' if use_proxy else 'direct'}...", flush=True)
    async with _make_client(use_proxy=use_proxy) as client:
        results = await asyncio.gather(
            *(load_upstream(source, upstream_timeout_ms, client) for source in enabled_sources)
        )
    for entries, result in results:
        all_entries.extend(entries)
        upstream_results.append(result)

    print(f"Upstreams: {len(all_entries)} total entries from {len(upstream_results)} sources", flush=True)

    stable_cn = next((playlist for playlist in rules["playlists"] if playlist.get("id") == "stable-cn"), None)
    if not stable_cn:
        raise RuntimeError("sources/curation-rules.json must contain a stable-cn playlist rule")

    source_ids = set(stable_cn["upstreamSourceIds"])
    candidate_entries = [entry for entry in all_entries if entry.get("sourceId") in source_ids]
    print(f"Candidates: {len(candidate_entries)} entries for curation...", flush=True)
    curated = curate_entries(candidate_entries, overrides, {**stable_cn, "channelMetadata": channel_metadata})
    print(f"Curated: {len(curated['entries'])} accepted + {len(curated.get('rejected', []))} rejected", flush=True)
    max_streams = stable_cn.get("maxStreams", len(curated["entries"]))
    limited_entries = curated["entries"][:max_streams]
    if not limited_entries:
        upstream_summary = ", ".join(format_upstream_summary(result) for result in upstream_results)
        raise RuntimeError(f"Generated playlist is empty. Upstreams: {upstream_summary}")

    accepted_by_source: dict[str, int] = {}
    for entry in limited_entries:
        source_id = str(entry.get("sourceId"))
        accepted_by_source[source_id] = accepted_by_source.get(source_id, 0) + 1
    for result in upstream_results:
        result["acceptedCount"] = accepted_by_source.get(str(result.get("id")), 0)

    if check_streams:
        stream_checks = await probe_streams(
            limited_entries,
            timeout_ms=stream_timeout_ms,
            concurrency=stream_check_concurrency,
        )
    else:
        stream_checks = {
            entry["url"]: {
                "checkedAt": generated_at,
                "status": "unchecked",
            }
            for entry in limited_entries
        }

    published_entries = select_published_entries(
        limited_entries,
        stream_checks,
        {"publishOnlyHealthy": check_streams and stable_cn.get("publishOnlyHealthy") is True},
    )
    if not published_entries:
        raise RuntimeError("No publishable streams after health filtering.")

    epg = await generate_epg(list(published_entries), enabled_epg_sources, generated_at, upstream_timeout_ms, use_proxy=use_proxy)
    health = build_health_report(
        {
            "generatedAt": generated_at,
            "streamChecks": stream_checks,
            "curatedEntries": limited_entries,
            "publishedEntries": published_entries,
            "upstreamResults": upstream_results,
        }
    )

    write_file("public/playlists/stable-cn.m3u", format_m3u(published_entries))
    write_file("public/epg/stable-cn.xml.gz", gzip.compress(epg["xml"].encode("utf-8")))
    write_json("public/health.json", health)
    write_json(
        "public/index.json",
        {
            "schemaVersion": 1,
            "name": "Smart IPTV Sources",
            "updatedAt": generated_at,
            "playlists": [
                {
                    "id": stable_cn["id"],
                    "name": stable_cn["name"],
                    "description": stable_cn["description"],
                    "region": stable_cn["region"],
                    "quality": stable_cn["quality"],
                    "url": "/playlists/stable-cn.m3u",
                    "healthUrl": "/health.json",
                    "epgUrl": "/epg/stable-cn.xml.gz",
                    "epgChannelCount": epg["channelCount"],
                    "epgProgramCount": epg["programCount"],
                }
            ],
        },
    )
    write_json(
        "public/version.json",
        {
            "schemaVersion": 1,
            "version": generated_at.replace("-", "")
            .replace(":", "")
            .replace(".", "")
            .replace("T", "")
            .replace("Z", "")[:12],
            "updatedAt": generated_at,
            "playlists": {
                "stable-cn": {
                    "streamCount": len(published_entries),
                    "channelCount": len({entry.get("displayName") for entry in published_entries}),
                    "epgChannelCount": epg["channelCount"],
                    "epgProgramCount": epg["programCount"],
                    "epgUrl": "/epg/stable-cn.xml.gz",
                    "healthUrl": "/health.json",
                    "url": "/playlists/stable-cn.m3u",
                }
            },
        },
    )

    print(
        f"Generated stable-cn with {len(published_entries)} published streams "
        f"from {len(limited_entries)} candidates and {len(enabled_sources)} upstreams."
    )
    print(f"Generated EPG with {epg['channelCount']} channels and {epg['programCount']} programs from {epg['sourceCount']} sources.")
    print(f"Stream checks: {'enabled' if check_streams else 'unchecked'}.")


if __name__ == "__main__":
    asyncio.run(main())
