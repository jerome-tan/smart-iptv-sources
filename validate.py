from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path.cwd()


def read_json(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def assert_valid(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def public_path(url_path: str) -> Path:
    return ROOT / "public" / url_path.lstrip("/")


def main() -> None:
    index = read_json("public/index.json")
    version = read_json("public/version.json")
    health = read_json("public/health.json")
    channel_metadata = read_json("sources/channel-metadata.json")
    epg_sources = read_json("sources/epg-sources.json")
    upstreams = read_json("sources/upstreams.json")
    rules = read_json("sources/curation-rules.json")

    assert_valid(index.get("schemaVersion") == 1, "public/index.json schemaVersion must be 1")
    assert_valid(isinstance(index.get("playlists"), list), "public/index.json playlists must be an array")
    assert_valid(len(index["playlists"]) > 0, "public/index.json must contain at least one playlist")
    assert_valid(version.get("schemaVersion") == 1, "public/version.json schemaVersion must be 1")
    assert_valid(health.get("schemaVersion") == 1, "public/health.json schemaVersion must be 1")
    assert_valid(isinstance(health.get("upstreams"), list), "public/health.json upstreams must be an array")
    assert_valid(isinstance(health.get("streams"), list), "public/health.json streams must be an array")
    assert_valid(len(health["streams"]) > 0, "public/health.json streams must contain at least one item")
    assert_valid(isinstance(upstreams.get("sources"), list), "sources/upstreams.json sources must be an array")
    assert_valid(epg_sources.get("schemaVersion") == 1, "sources/epg-sources.json schemaVersion must be 1")
    assert_valid(isinstance(epg_sources.get("sources"), list), "sources/epg-sources.json sources must be an array")
    assert_valid(channel_metadata.get("schemaVersion") == 1, "sources/channel-metadata.json schemaVersion must be 1")
    assert_valid(
        isinstance(channel_metadata.get("channels"), dict),
        "sources/channel-metadata.json channels must be an object",
    )
    assert_valid(rules.get("schemaVersion") == 1, "sources/curation-rules.json schemaVersion must be 1")
    assert_valid(isinstance(rules.get("playlists"), list), "sources/curation-rules.json playlists must be an array")

    for playlist in index["playlists"]:
        playlist_id = playlist.get("id")
        assert_valid(bool(playlist_id), "playlist id is required")
        assert_valid(bool(playlist.get("name")), f"playlist {playlist_id} name is required")
        assert_valid(bool(playlist.get("url")), f"playlist {playlist_id} url is required")
        assert_valid(
            playlist_id in (version.get("playlists") or {}),
            f"public/version.json missing playlist version info: {playlist_id}",
        )

        if playlist["url"].startswith("/"):
            playlist_file = public_path(playlist["url"])
            assert_valid(playlist_file.exists(), f"playlist file not found: {playlist['url']}")
            content = playlist_file.read_text(encoding="utf-8")
            assert_valid(content.startswith("#EXTM3U"), f"playlist must start with #EXTM3U: {playlist['url']}")
            stream_urls = [line for line in content.splitlines() if re.match(r"^https?://", line)]
            assert_valid(len(stream_urls) > 0, f"playlist must contain at least one stream URL: {playlist['url']}")

        health_url = playlist.get("healthUrl")
        if isinstance(health_url, str) and health_url.startswith("/"):
            health_file = public_path(health_url)
            assert_valid(health_file.exists(), f"health file not found: {health_url}")
            playlist_health = json.loads(health_file.read_text(encoding="utf-8"))
            assert_valid(playlist_health.get("schemaVersion") == 1, f"health schemaVersion must be 1: {health_url}")
            assert_valid(isinstance(playlist_health.get("upstreams"), list), f"health upstreams must be an array: {health_url}")
            assert_valid(isinstance(playlist_health.get("streams"), list), f"health streams must be an array: {health_url}")
            assert_valid(len(playlist_health["streams"]) > 0, f"health streams must contain at least one item: {health_url}")

        epg_url = playlist.get("epgUrl")
        if isinstance(epg_url, str) and epg_url.startswith("/"):
            epg_file = public_path(epg_url)
            assert_valid(epg_file.exists(), f"EPG file not found: {epg_url}")
            content = gzip.decompress(epg_file.read_bytes()).decode("utf-8")
            assert_valid("<tv" in content, f"EPG must be an XMLTV document: {epg_url}")
            assert_valid("<channel " in content, f"EPG must contain channel elements: {epg_url}")
            assert_valid("<programme " in content, f"EPG must contain programme elements: {epg_url}")

    for playlist_id, playlist_version in (version.get("playlists") or {}).items():
        assert_valid(playlist_version.get("streamCount", 0) > 0, f"version streamCount must be greater than 0: {playlist_id}")
        assert_valid(playlist_version.get("channelCount", 0) > 0, f"version channelCount must be greater than 0: {playlist_id}")

    for source in upstreams["sources"]:
        source_id = source.get("id")
        assert_valid(bool(source_id), "upstream source id is required")
        assert_valid(bool(source.get("name")), f"upstream source {source_id} name is required")
        assert_valid(bool(source.get("url")), f"upstream source {source_id} url is required")
        assert_valid(bool(re.match(r"^https?://", source["url"])), f"upstream source {source_id} must use http(s)")

    for source in epg_sources["sources"]:
        source_id = source.get("id")
        assert_valid(bool(source_id), "EPG source id is required")
        assert_valid(bool(source.get("name")), f"EPG source {source_id} name is required")
        if source.get("enabled") is not False:
            assert_valid(bool(source.get("url")), f"enabled EPG source {source_id} url is required")
            assert_valid(bool(re.match(r"^https?://", source["url"])), f"EPG source {source_id} must use http(s)")

    for channel_name, metadata in channel_metadata["channels"].items():
        assert_valid(bool(channel_name.strip()), "metadata channel name must not be blank")
        assert_valid(isinstance(metadata, dict), f"metadata for {channel_name} must be an object")
        description = metadata.get("description")
        assert_valid(
            isinstance(description, str) and len(description.strip()) >= 12,
            f"metadata {channel_name} description must be a useful string",
        )
        if metadata.get("tags") is not None:
            assert_valid(isinstance(metadata["tags"], list), f"metadata {channel_name} tags must be an array")
            for tag in metadata["tags"]:
                assert_valid(isinstance(tag, str) and bool(tag.strip()), f"metadata {channel_name} tags must be non-empty strings")

    upstream_ids = {source["id"] for source in upstreams["sources"]}
    for playlist in rules["playlists"]:
        playlist_id = playlist.get("id")
        assert_valid(bool(playlist_id), "curation playlist id is required")
        assert_valid(isinstance(playlist.get("upstreamSourceIds"), list), f"playlist {playlist_id} upstreamSourceIds must be an array")
        for source_id in playlist["upstreamSourceIds"]:
            assert_valid(source_id in upstream_ids, f"playlist {playlist_id} references unknown upstream source: {source_id}")

    print("Source repository validation passed.")


if __name__ == "__main__":
    main()
