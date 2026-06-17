# Smart IPTV Sources

Curated IPTV playlist and EPG publishing repository for Smart IPTV.

This repository generates and publishes static files that can be hosted by
Cloudflare Pages, Vercel, or an object storage bucket.

## Layout

```text
public/
  index.json
  health.json
  version.json
  playlists/
    stable-cn.m3u
  epg/
    .gitkeep

sources/
  curation-rules.json
  upstreams.json
  channel-overrides.json
  epg-sources.json

scripts/
  generate.mjs
  lib/playlist-core.mjs
  validate.mjs
```

## Generate

```bash
npm run generate
```

The generator reads enabled sources from `sources/upstreams.json`, applies
`sources/curation-rules.json` and `sources/channel-overrides.json`, then writes:

- `public/playlists/stable-cn.m3u`
- `public/health.json`
- `public/index.json`
- `public/version.json`

By default, stream URLs are listed as `unchecked` in `public/health.json`.
Run the deeper probe when you want to test each stream URL:

```bash
npm run generate:check-streams
```

The deeper probe can be slow because it touches every generated stream URL. For
playlists with `publishOnlyHealthy: true` in `sources/curation-rules.json`, this
mode publishes only streams whose HLS playlist and first media segment can be
reached. `public/health.json` still keeps the full candidate list and marks
which streams were published.

## Static Output

The Android app should consume `public/index.json` first, then follow the
playlist and EPG URLs listed there.

Current production endpoint:

- Index: `https://smart-iptv-sources.pages.dev/index.json`
- Stable CN playlist: `https://smart-iptv-sources.pages.dev/playlists/stable-cn.m3u`

## Test And Validate

```bash
npm test
npm run validate
```

`npm run validate` checks the static output shape, playlist files, health file
references, upstream source definitions, and curation rule references.

## GitHub Actions

- `Validate Sources` runs tests, generates static output without stream probes,
  and validates the repository on pushes and pull requests.
- `Refresh Curated Sources` runs every 12 hours or manually from
  `workflow_dispatch`. It runs `npm run generate:check-streams`, validates the
  output, and commits refreshed files under `public/` when they change.

## Cloudflare Pages

Create a Pages project from this repository with:

- Build command: `npm run validate`
- Build output directory: `public`

The generated `public/_headers` file enables cross-origin reads and short cache
windows for playlist metadata. The scheduled GitHub Action refreshes `public/`
and pushes a commit, which can trigger a new Cloudflare Pages deployment.

## Notes

This project does not host or retransmit video content. Playlists only reference
publicly available live stream URLs.
