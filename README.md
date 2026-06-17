# Smart IPTV Sources

Curated IPTV playlist and EPG publishing repository for Smart IPTV.

This repository generates and publishes static files that can be hosted by
Cloudflare Pages, Vercel, or an object storage bucket.

## Layout

```text
public/
  index.json
  version.json
  playlists/
    stable-cn.m3u
  epg/
    .gitkeep

sources/
  upstreams.json
  channel-overrides.json
  epg-sources.json

scripts/
  validate.mjs
```

## Static Output

The Android app should consume `public/index.json` first, then follow the
playlist and EPG URLs listed there.

## Validate

```bash
npm run validate
```

## Notes

This project does not host or retransmit video content. Playlists only reference
publicly available live stream URLs.

