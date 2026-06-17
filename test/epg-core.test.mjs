import test from 'node:test'
import assert from 'node:assert/strict'
import { gzipSync } from 'node:zlib'

import {
  buildFilteredXmltv,
  collectPlaylistGuideKeys,
  decodeXmltvPayload,
} from '../scripts/lib/epg-core.mjs'

test('collectPlaylistGuideKeys includes ids, base ids, names, and display names', () => {
  const keys = collectPlaylistGuideKeys([
    {
      attributes: {
        'tvg-id': 'CCTV1.cn@HD',
        'tvg-name': 'CCTV-1',
      },
      displayName: 'CCTV-1 综合',
      name: 'CCTV-1 (1080p)',
    },
  ])

  assert(keys.ids.has('CCTV1.cn@HD'))
  assert(keys.ids.has('CCTV1.cn'))
  assert(keys.names.has('cctv1'))
  assert(keys.names.has('cctv1综合'))
  assert.equal(keys.outputIdById.get('CCTV1.cn@HD'), 'CCTV-1')
  assert.equal(keys.outputIdByName.get('cctv1'), 'CCTV-1')
})

test('buildFilteredXmltv keeps matching programs and rewrites channel ids to playlist ids', () => {
  const entries = [
    {
      attributes: {
        'tvg-id': 'CCTV1.cn@HD',
        'tvg-name': 'CCTV-1',
      },
      displayName: 'CCTV-1',
      name: 'CCTV-1 (1080p)',
    },
    {
      attributes: {
        'tvg-name': 'BBC News',
      },
      displayName: 'BBC News',
      name: 'BBC News (1080p)',
    },
  ]
  const chinaXml = `<?xml version="1.0" encoding="UTF-8"?>
<tv source-info-name="sample-cn">
  <channel id="494985"><display-name>CCTV-1 综合</display-name></channel>
  <channel id="Random.cn"><display-name>Random</display-name></channel>
  <programme start="20260617120000 +0800" stop="20260617123000 +0800" channel="494985">
    <title lang="zh">新闻三十分</title>
  </programme>
  <programme start="20260617120000 +0800" stop="20260617123000 +0800" channel="Random.cn">
    <title>Random Show</title>
  </programme>
</tv>`
  const ukXml = `<tv>
  <channel id="BBCNews.uk"><display-name>BBC News</display-name></channel>
  <programme start="20260617120000 +0000" stop="20260617123000 +0000" channel="BBCNews.uk">
    <title>World News</title>
  </programme>
</tv>`

  const result = buildFilteredXmltv({
    documents: [
      { id: 'cn', xml: chinaXml },
      { id: 'gb', xml: ukXml },
    ],
    entries,
    generatedAt: '2026-06-17T12:00:00.000Z',
  })

  assert.equal(result.channelCount, 2)
  assert.equal(result.programCount, 2)
  assert.match(result.xml, /generator-info-name="Smart IPTV Sources"/)
  assert.match(result.xml, /channel id="CCTV-1"/)
  assert.match(result.xml, /channel="CCTV-1"/)
  assert.match(result.xml, /channel id="BBC News"/)
  assert.match(result.xml, /channel="BBC News"/)
  assert.doesNotMatch(result.xml, /494985/)
  assert.doesNotMatch(result.xml, /BBCNews.uk/)
  assert.doesNotMatch(result.xml, /Random.cn/)
  assert.match(result.xml, /新闻三十分/)
  assert.match(result.xml, /World News/)
})

test('decodeXmltvPayload decompresses gzip payloads even when the URL has no gz extension', () => {
  const xml = '<tv><channel id="CCTV1.cn"/></tv>'
  const decoded = decodeXmltvPayload(gzipSync(Buffer.from(xml)), 'https://example.test/guide')

  assert.equal(decoded, xml)
})
