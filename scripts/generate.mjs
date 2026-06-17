import fs from 'node:fs'
import path from 'node:path'
import { gzipSync } from 'node:zlib'

import {
  buildFilteredXmltv,
  fetchXmltv,
} from './lib/epg-core.mjs'
import {
  buildHealthReport,
  curateEntries,
  fetchText,
  formatM3u,
  parseM3u,
  probeStream,
  selectPublishedEntries,
} from './lib/playlist-core.mjs'

const root = process.cwd()

const generatedAt = new Date().toISOString()
const checkStreams = process.argv.includes('--check-streams') || process.env.CHECK_STREAMS === 'true'
const upstreamTimeoutMs = Number.parseInt(process.env.UPSTREAM_TIMEOUT_MS ?? '15000', 10)
const streamTimeoutMs = Number.parseInt(process.env.STREAM_TIMEOUT_MS ?? '8000', 10)

const upstreams = readJson('sources/upstreams.json')
const epgSources = readJson('sources/epg-sources.json')
const overrides = readJson('sources/channel-overrides.json')
const channelMetadata = readJson('sources/channel-metadata.json')
const rules = readJson('sources/curation-rules.json')
const enabledSources = upstreams.sources.filter((source) => source.enabled !== false)
const enabledEpgSources = epgSources.sources.filter((source) => source.enabled !== false && source.url)
const allEntries = []
const upstreamResults = []

for (const source of enabledSources) {
  try {
    const result = await fetchText(source.url, { timeoutMs: upstreamTimeoutMs })
    if (!result.ok) {
      upstreamResults.push({
        id: source.id,
        name: source.name,
        status: 'http-error',
        httpStatus: result.httpStatus,
        channelCount: 0,
        acceptedCount: 0,
      })
      continue
    }

    const entries = parseM3u(result.text, source)
    allEntries.push(...entries)
    upstreamResults.push({
      id: source.id,
      name: source.name,
      status: 'ok',
      httpStatus: result.httpStatus,
      channelCount: entries.length,
      acceptedCount: 0,
    })
  } catch (error) {
    upstreamResults.push({
      id: source.id,
      name: source.name,
      status: error.name === 'AbortError' ? 'timeout' : 'network-error',
      channelCount: 0,
      acceptedCount: 0,
      error: error.message,
    })
  }
}

const stableCn = rules.playlists.find((playlist) => playlist.id === 'stable-cn')
if (!stableCn) {
  throw new Error('sources/curation-rules.json must contain a stable-cn playlist rule')
}

const sourceIds = new Set(stableCn.upstreamSourceIds)
const candidateEntries = allEntries.filter((entry) => sourceIds.has(entry.sourceId))
const curated = curateEntries(candidateEntries, overrides, {
  ...stableCn,
  channelMetadata,
})
const limitedEntries = curated.entries.slice(0, stableCn.maxStreams ?? curated.entries.length)
if (limitedEntries.length === 0) {
  const upstreamSummary = upstreamResults
    .map((result) => `${result.id}:${result.status}${result.httpStatus ? `(${result.httpStatus})` : ''}`)
    .join(', ')
  throw new Error(`Generated playlist is empty. Upstreams: ${upstreamSummary}`)
}

const acceptedBySource = new Map()
for (const entry of limitedEntries) {
  acceptedBySource.set(entry.sourceId, (acceptedBySource.get(entry.sourceId) ?? 0) + 1)
}
for (const result of upstreamResults) {
  result.acceptedCount = acceptedBySource.get(result.id) ?? 0
}

const streamChecks = checkStreams
  ? await probeStreams(limitedEntries, { timeoutMs: streamTimeoutMs })
  : new Map(limitedEntries.map((entry) => [entry.url, {
    checkedAt: generatedAt,
    status: 'unchecked',
  }]))
const publishedEntries = selectPublishedEntries(limitedEntries, streamChecks, {
  publishOnlyHealthy: checkStreams && stableCn.publishOnlyHealthy === true,
})
if (publishedEntries.length === 0) {
  throw new Error('No publishable streams after health filtering.')
}

const epg = await generateEpg(publishedEntries, enabledEpgSources, {
  generatedAt,
  timeoutMs: upstreamTimeoutMs,
})
const health = buildHealthReport({
  generatedAt,
  streamChecks,
  curatedEntries: limitedEntries,
  publishedEntries,
  upstreamResults,
})

writeFile('public/playlists/stable-cn.m3u', formatM3u(publishedEntries))
writeFile('public/epg/stable-cn.xml.gz', gzipSync(Buffer.from(epg.xml, 'utf8')))
writeJson('public/health.json', health)
writeJson('public/index.json', {
  schemaVersion: 1,
  name: 'Smart IPTV Sources',
  updatedAt: generatedAt,
  playlists: [
    {
      id: stableCn.id,
      name: stableCn.name,
      description: stableCn.description,
      region: stableCn.region,
      quality: stableCn.quality,
      url: '/playlists/stable-cn.m3u',
      healthUrl: '/health.json',
      epgUrl: '/epg/stable-cn.xml.gz',
      epgChannelCount: epg.channelCount,
      epgProgramCount: epg.programCount,
    },
  ],
})
writeJson('public/version.json', {
  schemaVersion: 1,
  version: generatedAt.replace(/[-:.TZ]/g, '').slice(0, 12),
  updatedAt: generatedAt,
  playlists: {
    'stable-cn': {
      streamCount: publishedEntries.length,
      channelCount: new Set(publishedEntries.map((entry) => entry.displayName)).size,
      epgChannelCount: epg.channelCount,
      epgProgramCount: epg.programCount,
      epgUrl: '/epg/stable-cn.xml.gz',
      healthUrl: '/health.json',
      url: '/playlists/stable-cn.m3u',
    },
  },
})

console.log(`Generated stable-cn with ${publishedEntries.length} published streams from ${limitedEntries.length} candidates and ${enabledSources.length} upstreams.`)
console.log(`Generated EPG with ${epg.channelCount} channels and ${epg.programCount} programs from ${epg.sourceCount} sources.`)
console.log(`Stream checks: ${checkStreams ? 'enabled' : 'unchecked'}.`)

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), 'utf8'))
}

function writeJson(relativePath, value) {
  writeFile(relativePath, `${JSON.stringify(value, null, 2)}\n`)
}

function writeFile(relativePath, value) {
  const filePath = path.join(root, relativePath)
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, value)
}

async function probeStreams(entries, { timeoutMs }) {
  const checks = new Map()
  const concurrency = Number.parseInt(process.env.STREAM_CHECK_CONCURRENCY ?? '8', 10)
  let cursor = 0

  async function worker() {
    while (cursor < entries.length) {
      const entry = entries[cursor]
      cursor += 1
      checks.set(entry.url, await probeStream(entry.url, { timeoutMs }))
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, entries.length) }, worker)
  await Promise.all(workers)
  return checks
}

async function generateEpg(entries, sources, { generatedAt, timeoutMs }) {
  if (sources.length === 0) {
    throw new Error('sources/epg-sources.json must contain at least one enabled EPG source')
  }

  const documents = []
  const errors = []
  for (const source of sources) {
    try {
      const result = await fetchXmltv(source.url, { timeoutMs })
      if (!result.ok) {
        errors.push(`${source.id}: HTTP ${result.httpStatus}`)
        continue
      }
      documents.push({
        id: source.id,
        xml: result.text,
      })
    } catch (error) {
      errors.push(`${source.id}: ${error.name === 'AbortError' ? 'timeout' : error.message}`)
    }
  }

  if (documents.length === 0) {
    throw new Error(`No EPG sources could be loaded. ${errors.join('; ')}`)
  }

  const epg = buildFilteredXmltv({
    documents,
    entries,
    generatedAt,
  })
  if (epg.programCount === 0) {
    throw new Error(`Generated EPG contains no programs. Loaded sources: ${documents.map((doc) => doc.id).join(', ')}`)
  }

  return {
    ...epg,
    sourceCount: documents.length,
  }
}
