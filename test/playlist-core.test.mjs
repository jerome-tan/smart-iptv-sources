import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildHealthReport,
  curateEntries,
  formatM3u,
  parseM3u,
  probeStream,
  selectPublishedEntries,
} from '../scripts/lib/playlist-core.mjs'

const source = {
  id: 'sample-cn',
  name: 'Sample China',
  region: 'CN',
  priority: 20,
}

test('parseM3u extracts attributes, names, urls, resolution, and source metadata', () => {
  const entries = parseM3u(`#EXTM3U
#EXTINF:-1 tvg-id="cctv1.cn" tvg-name="CCTV-1" group-title="央视",CCTV-1 (1080p)
https://example.test/cctv1.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 [Not 24/7] (720p)
https://example.test/jx.m3u8
#EXTINF:-1 group-title="央视",CCTV-4K (2160p)
https://example.test/cctv4k.m3u8
#EXTINF:-1 group-title="央视",CCTV-9 (576i)
https://example.test/cctv9.m3u8
`, source)

  assert.equal(entries.length, 4)
  assert.deepEqual(entries[0], {
    attributes: {
      'tvg-id': 'cctv1.cn',
      'tvg-name': 'CCTV-1',
      'group-title': '央视',
    },
    groupTitle: '央视',
    isNot24x7: false,
    name: 'CCTV-1 (1080p)',
    normalizedName: 'CCTV-1',
    rawExtinf: '#EXTINF:-1 tvg-id="cctv1.cn" tvg-name="CCTV-1" group-title="央视",CCTV-1 (1080p)',
    resolution: 1080,
    sourceId: 'sample-cn',
    sourceName: 'Sample China',
    sourcePriority: 20,
    sourceRegion: 'CN',
    url: 'https://example.test/cctv1.m3u8',
  })
  assert.equal(entries[1].isNot24x7, true)
  assert.equal(entries[1].normalizedName, '江西卫视')
  assert.equal(entries[2].normalizedName, 'CCTV-4K')
  assert.equal(entries[2].resolution, 2160)
  assert.equal(entries[3].normalizedName, 'CCTV-9')
  assert.equal(entries[3].resolution, 576)
})

test('curateEntries filters low quality streams, aliases names, deduplicates urls, and caps variants', () => {
  const entries = parseM3u(`#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-Storm Music (1080p)
https://example.test/storm-1080.m3u8
#EXTINF:-1 group-title="央视",CCTV-Storm Music (480p)
https://example.test/storm-480.m3u8
#EXTINF:-1 group-title="央视",CCTV-Storm Music (1080p)
https://example.test/storm-1080.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 [Not 24/7] (1080p)
https://example.test/jx.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 (720p)
https://example.test/jx-720.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 (1080p)
https://example.test/jx-1080.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 (4K)
https://example.test/jx-4k.m3u8
`, source)

  const result = curateEntries(entries, {
    aliases: {
      'CCTV-Storm Music': 'CCTV 风云音乐',
    },
    blacklistNames: [],
    blacklistUrls: [],
    preferredUrls: {
      'https://example.test/jx-1080.m3u8': 100,
    },
  }, {
    includeNot24x7: false,
    keepUnknownResolution: true,
    maxSourcesPerChannel: 2,
    minResolution: 720,
  })

  assert.deepEqual(result.entries.map((entry) => [entry.displayName, entry.url]), [
    ['CCTV 风云音乐', 'https://example.test/storm-1080.m3u8'],
    ['江西卫视', 'https://example.test/jx-1080.m3u8'],
    ['江西卫视', 'https://example.test/jx-4k.m3u8'],
  ])
  assert.equal(result.rejected.lowResolution, 1)
  assert.equal(result.rejected.duplicateUrl, 1)
  assert.equal(result.rejected.not24x7, 1)
  assert.equal(result.rejected.channelLimit, 1)
})

test('curateEntries applies curated regional groups and ordering', () => {
  const entries = [
    ...parseM3u(`#EXTM3U
#EXTINF:-1 group-title="General",CCTV-13 (1080p)
https://example.test/cctv13.m3u8
#EXTINF:-1 group-title="General",CCTV-1 (1080p)
https://example.test/cctv1.m3u8
#EXTINF:-1 group-title="General",CCTV-4K (1080p)
https://example.test/cctv4k.m3u8
#EXTINF:-1 group-title="General",CGTN (1080p)
https://example.test/cgtn.m3u8
#EXTINF:-1 group-title="General",BRTV 北京卫视 (1080p)
https://example.test/beijing.m3u8
#EXTINF:-1 group-title="General",Hunan TV (1080p)
https://example.test/hunan.m3u8
`, { ...source, id: 'cn', region: 'CN' }),
    ...parseM3u(`#EXTM3U
#EXTINF:-1 group-title="General",RTHK TV 31 (港台電視31) [Geo-blocked] (1080p)
https://example.test/rthk31.m3u8
#EXTINF:-1 group-title="General",Random Hong Kong Shopping (1080p)
https://example.test/hk-shopping.m3u8
`, { ...source, id: 'hk', region: 'HK' }),
    ...parseM3u(`#EXTM3U
#EXTINF:-1 group-title="General",TVBS Asia (1080p)
https://example.test/tvbs.m3u8
`, { ...source, id: 'hk', region: 'HK' }),
    ...parseM3u(`#EXTM3U
#EXTINF:-1 group-title="News",BBC News (1080p)
https://example.test/bbc-news.m3u8
#EXTINF:-1 group-title="General",Minor UK Local (1080p)
https://example.test/uk-local.m3u8
`, { ...source, id: 'uk', region: 'UK' }),
    ...parseM3u(`#EXTM3U
#EXTINF:-1 group-title="News",ABC News (1080p)
https://example.test/abc-news.m3u8
#EXTINF:-1 tvg-id="CCTV.us@SD" group-title="General",Charlotte County CC-TV (Charlotte County FA) (720p)
https://example.test/charlotte.m3u8
#EXTINF:-1 group-title="General",Random US Local (1080p)
https://example.test/us-local.m3u8
`, { ...source, id: 'us', region: 'US' }),
  ]

  const result = curateEntries(entries, {
    aliases: {
      'BRTV 北京卫视': '北京卫视',
      'Hunan TV': '湖南卫视',
    },
  }, {
    channelGroups: {
      defaultGroup: '其他精选',
      groupOrder: ['央视频道', '地方卫视', '香港', '英国', '美国', '其他精选'],
      restrictedSourceRegions: ['HK', 'UK', 'US'],
      rules: [
        {
          name: '央视频道',
          sort: 'cctv',
          patterns: ['^CCTV', '^CGTN'],
        },
        {
          name: '地方卫视',
          patterns: ['卫视$'],
        },
        {
          name: '香港',
          patterns: ['^RTHK', '^TVB', 'ViuTV', '^HOY'],
        },
        {
          name: '英国',
          sourceRegions: ['UK'],
          patterns: ['^BBC News$', '^BBC One$', '^BBC Two$', '^ITV', '^Channel 4$', '^Channel 5$', '^Sky News$'],
        },
        {
          name: '美国',
          sourceRegions: ['US'],
          patterns: ['^ABC News$', '^CBS News$', '^NBC News NOW$', '^PBS', '^Bloomberg', '^Fox Weather$'],
        },
      ],
    },
  })

  assert.deepEqual(
    result.entries.map((entry) => [entry.displayGroup, entry.displayName]),
    [
      ['央视频道', 'CCTV-1'],
      ['央视频道', 'CCTV-4K'],
      ['央视频道', 'CCTV-13'],
      ['央视频道', 'CGTN'],
      ['地方卫视', '北京卫视'],
      ['地方卫视', '湖南卫视'],
      ['香港', 'RTHK TV 31 (港台電視31) [Geo-blocked]'],
      ['香港', 'TVBS Asia'],
      ['英国', 'BBC News'],
      ['美国', 'ABC News'],
    ],
  )
  assert.equal(result.rejected.notSelectedRegion, 4)
})

test('formatM3u writes curated entries with stable attributes and source metadata', () => {
  const entries = curateEntries(parseM3u(`#EXTM3U
#EXTINF:-1 tvg-id="cctv1.cn" tvg-name="CCTV-1" group-title="央视",CCTV-1 (1080p)
https://example.test/cctv1.m3u8
`, source), {}, {
    channelMetadata: {
      channels: {
        'CCTV-1': {
          description: '央视综合频道，覆盖新闻、专题、文艺和生活服务节目。',
          tags: ['央视', '综合', '新闻'],
        },
      },
    },
  }).entries

  assert.equal(formatM3u(entries), `#EXTM3U
#EXTINF:-1 tvg-id="cctv1.cn" tvg-name="CCTV-1" group-title="央视" x-smart-source="sample-cn" x-smart-description="央视综合频道，覆盖新闻、专题、文艺和生活服务节目。" x-smart-tags="央视,综合,新闻" x-smart-resolution="1080",CCTV-1
https://example.test/cctv1.m3u8
`)
})

test('curateEntries matches channel metadata with normalized display names', () => {
  const entries = curateEntries(parseM3u(`#EXTM3U
#EXTINF:-1 group-title="央视",CCTV1 (1080p)
https://example.test/cctv1.m3u8
`, source), {}, {
    channelMetadata: {
      channels: {
        'CCTV-1': {
          description: '央视综合频道，覆盖新闻、专题、文艺和生活服务节目。',
          tags: ['央视', '综合'],
        },
      },
    },
  }).entries

  assert.equal(entries[0].smartDescription, '央视综合频道，覆盖新闻、专题、文艺和生活服务节目。')
  assert.deepEqual(entries[0].smartTags, ['央视', '综合'])
})

test('buildHealthReport summarizes upstream fetches and stream checks', () => {
  const now = '2026-06-17T00:00:00.000Z'
  const entries = curateEntries(parseM3u(`#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-1 (1080p)
https://example.test/cctv1.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 (720p)
https://example.test/jx.m3u8
`, source), {}, {}).entries

  const report = buildHealthReport({
    generatedAt: now,
    streamChecks: new Map([
      ['https://example.test/cctv1.m3u8', { status: 'ok', httpStatus: 200, checkedAt: now }],
      ['https://example.test/jx.m3u8', { status: 'http-error', httpStatus: 404, checkedAt: now }],
    ]),
    curatedEntries: entries,
    upstreamResults: [
      { id: 'sample-cn', name: 'Sample China', status: 'ok', httpStatus: 200, channelCount: 2, acceptedCount: 2 },
      { id: 'offline', name: 'Offline Source', status: 'http-error', httpStatus: 404, channelCount: 0, acceptedCount: 0 },
    ],
  })

  assert.equal(report.summary.upstreams.ok, 1)
  assert.equal(report.summary.upstreams.httpError, 1)
  assert.equal(report.summary.streams.ok, 1)
  assert.equal(report.summary.streams.httpError, 1)
  assert.deepEqual(report.streams.map((stream) => [stream.channelName, stream.status, stream.httpStatus]), [
    ['CCTV-1', 'ok', 200],
    ['江西卫视', 'http-error', 404],
  ])
})

test('probeStream checks the first media segment for HLS playlists', async () => {
  const calls = []
  const fetchImpl = async (url) => {
    calls.push(String(url))
    if (url === 'https://example.test/live/index.m3u8') {
      return new Response(`#EXTM3U
#EXT-X-TARGETDURATION:10
segment-001.ts
`, { status: 200 })
    }
    if (url === 'https://example.test/live/segment-001.ts') {
      return new Response('segment', { status: 206 })
    }
    return new Response('', { status: 404 })
  }

  const result = await probeStream('https://example.test/live/index.m3u8', {
    fetchImpl,
    timeoutMs: 1000,
  })

  assert.equal(result.status, 'ok')
  assert.equal(result.httpStatus, 206)
  assert.deepEqual(calls, [
    'https://example.test/live/index.m3u8',
    'https://example.test/live/segment-001.ts',
  ])
})

test('selectPublishedEntries keeps only healthy streams when requested', () => {
  const entries = curateEntries(parseM3u(`#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-1 (1080p)
https://example.test/cctv1.m3u8
#EXTINF:-1 group-title="卫视",江西卫视 (1080p)
https://example.test/jx.m3u8
`, source), {}, {}).entries
  const checks = new Map([
    ['https://example.test/cctv1.m3u8', { status: 'ok' }],
    ['https://example.test/jx.m3u8', { status: 'http-error' }],
  ])

  assert.deepEqual(
    selectPublishedEntries(entries, checks, { publishOnlyHealthy: true }).map((entry) => entry.displayName),
    ['CCTV-1'],
  )
  assert.deepEqual(
    selectPublishedEntries(entries, checks, { publishOnlyHealthy: false }).map((entry) => entry.displayName),
    ['CCTV-1', '江西卫视'],
  )
})
