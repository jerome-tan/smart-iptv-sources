const DECORATIVE_RESOLUTION_PATTERN = /\s*[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]/gi
const RESOLUTION_PATTERN = /[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]|\s([0-9]{3,4}[pi])(?:\s|$)|(?:^|\s)(4K)(?:\s|$)/gi
const NOT_24X7_PATTERN = /\[\s*not\s*24\s*\/\s*7\s*\]/i
const DEFAULT_BLOCKED_KEYWORDS = [
  'adult',
  'xxx',
  'porn',
  '博彩',
  '成人',
]

export function parseM3u(content, source) {
  const lines = content.replace(/\r/g, '').split('\n')
  const entries = []
  let pendingExtinf = null

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#EXTM3U')) {
      continue
    }

    if (line.startsWith('#EXTINF')) {
      pendingExtinf = line
      continue
    }

    if (line.startsWith('#')) {
      continue
    }

    if (!pendingExtinf) {
      continue
    }

    const attributes = parseExtinfAttributes(pendingExtinf)
    const name = parseExtinfName(pendingExtinf)
    const groupTitle = attributes['group-title'] ?? ''
    const normalizedName = normalizeChannelName(name)

    entries.push({
      attributes,
      groupTitle,
      isNot24x7: NOT_24X7_PATTERN.test(name),
      name,
      normalizedName,
      rawExtinf: pendingExtinf,
      resolution: parseResolution(name),
      sourceId: source.id,
      sourceName: source.name,
      sourcePriority: source.priority ?? 0,
      sourceRegion: source.region ?? '',
      url: line,
    })
    pendingExtinf = null
  }

  return entries
}

export function curateEntries(entries, overrides = {}, options = {}) {
  const settings = {
    blockedKeywords: DEFAULT_BLOCKED_KEYWORDS,
    includeNot24x7: false,
    keepUnknownResolution: true,
    maxSourcesPerChannel: 3,
    minResolution: 720,
    ...options,
  }
  const blacklistNames = new Set(overrides.blacklistNames ?? [])
  const blacklistUrls = new Set((overrides.blacklistUrls ?? []).map(normalizeUrl))
  const aliases = overrides.aliases ?? {}
  const preferredUrls = overrides.preferredUrls ?? {}
  const rejected = {
    blacklistedName: 0,
    blacklistedUrl: 0,
    blockedKeyword: 0,
    channelLimit: 0,
    duplicateUrl: 0,
    invalidUrl: 0,
    lowResolution: 0,
    notSelectedRegion: 0,
    not24x7: 0,
  }
  const seenUrls = new Set()
  const grouped = new Map()

  for (const entry of entries) {
    const urlKey = normalizeUrl(entry.url)
    const normalizedName = aliases[entry.normalizedName] ?? entry.normalizedName
    const displayName = normalizedName.trim()

    if (!isHttpUrl(entry.url)) {
      rejected.invalidUrl += 1
      continue
    }

    if (blacklistUrls.has(urlKey)) {
      rejected.blacklistedUrl += 1
      continue
    }

    if (blacklistNames.has(entry.normalizedName) || blacklistNames.has(displayName)) {
      rejected.blacklistedName += 1
      continue
    }

    if (!settings.includeNot24x7 && entry.isNot24x7) {
      rejected.not24x7 += 1
      continue
    }

    if (entry.resolution != null && entry.resolution < settings.minResolution) {
      rejected.lowResolution += 1
      continue
    }

    if (entry.resolution == null && !settings.keepUnknownResolution) {
      rejected.lowResolution += 1
      continue
    }

    if (containsBlockedKeyword(`${entry.name} ${entry.groupTitle}`, settings.blockedKeywords)) {
      rejected.blockedKeyword += 1
      continue
    }

    if (seenUrls.has(urlKey)) {
      rejected.duplicateUrl += 1
      continue
    }
    seenUrls.add(urlKey)

    const groupInfo = classifyChannel(displayName, entry, settings.channelGroups)
    if (!groupInfo) {
      rejected.notSelectedRegion += 1
      continue
    }

    const enriched = {
      ...entry,
      displayName,
      displayGroup: groupInfo.name,
      groupRank: groupInfo.rank,
      score: scoreEntry(entry, preferredUrls),
      sortKey: groupInfo.sortKey,
    }
    const channelEntries = grouped.get(displayName) ?? []
    channelEntries.push(enriched)
    grouped.set(displayName, channelEntries)
  }

  const accepted = []
  for (const [channelName, channelEntries] of grouped.entries()) {
    const sorted = channelEntries.sort(compareEntries)
    const kept = sorted.slice(0, settings.maxSourcesPerChannel)
    rejected.channelLimit += Math.max(0, sorted.length - kept.length)
    accepted.push(...kept.map((entry) => ({ ...entry, displayName: channelName })))
  }

  return {
    entries: accepted.sort(compareOutputEntries),
    rejected,
  }
}

export function formatM3u(entries) {
  const lines = ['#EXTM3U']
  for (const entry of entries) {
    const attributes = {
      ...entry.attributes,
      'tvg-name': entry.attributes['tvg-name'] ?? entry.displayName,
      'group-title': entry.displayGroup || entry.groupTitle || entry.attributes['group-title'] || '未分组',
      'x-smart-source': entry.sourceId,
    }
    if (entry.resolution != null) {
      attributes['x-smart-resolution'] = String(entry.resolution)
    }

    lines.push(`#EXTINF:-1 ${formatAttributes(attributes)},${entry.displayName}`)
    lines.push(entry.url)
  }
  return `${lines.join('\n')}\n`
}

export function selectPublishedEntries(entries, streamChecks, { publishOnlyHealthy = false } = {}) {
  if (!publishOnlyHealthy) {
    return entries
  }

  return entries.filter((entry) => streamChecks.get(entry.url)?.status === 'ok')
}

export function buildHealthReport({
  generatedAt,
  streamChecks = new Map(),
  curatedEntries,
  publishedEntries = curatedEntries,
  upstreamResults,
}) {
  const publishedUrls = new Set(publishedEntries.map((entry) => entry.url))
  const streams = curatedEntries.map((entry) => {
    const result = streamChecks.get(entry.url) ?? {
      status: 'unchecked',
      checkedAt: generatedAt,
    }
    return {
      channelName: entry.displayName,
      groupTitle: entry.displayGroup || entry.groupTitle || '未分组',
      httpStatus: result.httpStatus ?? null,
      published: publishedUrls.has(entry.url),
      resolution: entry.resolution,
      sourceId: entry.sourceId,
      status: result.status,
      url: entry.url,
      checkedAt: result.checkedAt ?? generatedAt,
      error: result.error ?? null,
    }
  })

  return {
    schemaVersion: 1,
    updatedAt: generatedAt,
    summary: {
      channels: new Set(curatedEntries.map((entry) => entry.displayName)).size,
      publishedChannels: new Set(publishedEntries.map((entry) => entry.displayName)).size,
      publishedStreams: publishedEntries.length,
      streams: countStatuses(streams),
      upstreams: countStatuses(upstreamResults),
    },
    upstreams: upstreamResults.map((result) => ({
      id: result.id,
      name: result.name,
      status: result.status,
      httpStatus: result.httpStatus ?? null,
      channelCount: result.channelCount ?? 0,
      acceptedCount: result.acceptedCount ?? 0,
      error: result.error ?? null,
    })),
    streams,
  }
}

export async function fetchText(url, { fetchImpl = globalThis.fetch, timeoutMs = 15000 } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(url, {
      headers: {
        'Accept': 'application/x-mpegURL, application/vnd.apple.mpegurl, text/plain, */*',
        'User-Agent': 'SmartIPTVSourceBuilder/0.1',
      },
      signal: controller.signal,
    })
    const text = await response.text()
    return {
      httpStatus: response.status,
      ok: response.ok,
      text,
    }
  } finally {
    clearTimeout(timeout)
  }
}

export async function probeStream(url, { fetchImpl = globalThis.fetch, timeoutMs = 8000 } = {}) {
  const checkedAt = new Date().toISOString()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await probeStreamUrl(url, {
      depth: 0,
      fetchImpl,
      signal: controller.signal,
    })
    return {
      checkedAt,
      ...response,
    }
  } catch (error) {
    return {
      checkedAt,
      error: error.name === 'AbortError' ? 'timeout' : error.message,
      status: error.name === 'AbortError' ? 'timeout' : 'network-error',
    }
  } finally {
    clearTimeout(timeout)
  }
}

async function probeStreamUrl(url, { depth, fetchImpl, signal }) {
  const isPlaylist = isHlsUrl(url)
  const response = await fetchImpl(url, {
    headers: isPlaylist
      ? {
        'Accept': 'application/x-mpegURL, application/vnd.apple.mpegurl, text/plain, */*',
        'User-Agent': 'SmartIPTVSourceBuilder/0.1',
      }
      : {
        'Range': 'bytes=0-2047',
        'User-Agent': 'SmartIPTVSourceBuilder/0.1',
      },
    signal,
  })

  if (!response.ok) {
    return {
      httpStatus: response.status,
      status: 'http-error',
    }
  }

  if (!isPlaylist || depth >= 2) {
    return {
      httpStatus: response.status,
      status: 'ok',
    }
  }

  const playlistText = await response.text()
  const firstMediaUrl = findFirstMediaUrl(playlistText, url)
  if (!firstMediaUrl) {
    return {
      httpStatus: response.status,
      status: 'ok',
    }
  }

  return probeStreamUrl(firstMediaUrl, {
    depth: depth + 1,
    fetchImpl,
    signal,
  })
}

function parseExtinfAttributes(extinf) {
  const attributePart = extinf.slice(0, extinf.lastIndexOf(',') === -1 ? undefined : extinf.lastIndexOf(','))
  const attributes = {}
  const pattern = /([\w-]+)="([^"]*)"/g
  let match = pattern.exec(attributePart)
  while (match) {
    attributes[match[1]] = match[2]
    match = pattern.exec(attributePart)
  }
  return attributes
}

function parseExtinfName(extinf) {
  const commaIndex = extinf.lastIndexOf(',')
  if (commaIndex === -1) {
    return ''
  }
  return extinf.slice(commaIndex + 1).trim()
}

function normalizeChannelName(name) {
  return name
    .replace(NOT_24X7_PATTERN, '')
    .replace(DECORATIVE_RESOLUTION_PATTERN, '')
    .replace(/\s+([0-9]{3,4}[pi])$/i, '')
    .replace(/\s+/g, ' ')
    .replace(/\s+([：:])/g, '$1')
    .trim()
}

function parseResolution(name) {
  let best = null
  const matches = name.matchAll(RESOLUTION_PATTERN)
  for (const match of matches) {
    const token = (match[1] ?? match[2] ?? match[3] ?? '').toUpperCase()
    const value = token === '4K' ? 2160 : Number.parseInt(token.replace(/[PI]/, ''), 10)
    if (Number.isFinite(value)) {
      best = Math.max(best ?? 0, value)
    }
  }
  return best
}

function normalizeUrl(url) {
  return url.trim()
}

function isHlsUrl(url) {
  return /\.m3u8(?:[?#].*)?$/i.test(url)
}

function findFirstMediaUrl(playlistText, playlistUrl) {
  const lines = playlistText.replace(/\r/g, '').split('\n')
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) {
      continue
    }
    return new URL(line, playlistUrl).toString()
  }
  return null
}

function isHttpUrl(url) {
  return /^https?:\/\//i.test(url.trim())
}

function containsBlockedKeyword(value, keywords) {
  const normalized = value.toLowerCase()
  return keywords.some((keyword) => normalized.includes(keyword.toLowerCase()))
}

function scoreEntry(entry, preferredUrls) {
  const preferred = preferredUrls[entry.url] ?? 0
  const resolutionScore = entry.resolution ?? 800
  return preferred * 10000 + resolutionScore + entry.sourcePriority
}

function compareEntries(left, right) {
  if (right.score !== left.score) {
    return right.score - left.score
  }
  if ((right.resolution ?? 0) !== (left.resolution ?? 0)) {
    return (right.resolution ?? 0) - (left.resolution ?? 0)
  }
  return left.url.localeCompare(right.url)
}

function compareOutputEntries(left, right) {
  const groupCompare = (left.groupRank ?? outputGroupRank(left.groupTitle)) - (right.groupRank ?? outputGroupRank(right.groupTitle))
  if (groupCompare !== 0) {
    return groupCompare
  }
  const sortCompare = compareSortKeys(left.sortKey, right.sortKey)
  if (sortCompare !== 0) {
    return sortCompare
  }
  const nameCompare = left.displayName.localeCompare(right.displayName, 'zh-Hans-CN')
  if (nameCompare !== 0) {
    return nameCompare
  }
  return compareEntries(left, right)
}

function classifyChannel(displayName, entry, channelGroups) {
  if (!channelGroups) {
    return {
      name: entry.groupTitle || '未分组',
      rank: outputGroupRank(entry.groupTitle),
      sortKey: null,
    }
  }

  const matchedRule = (channelGroups.rules ?? []).find((rule) => matchesChannelRule(rule, displayName, entry))
  if (matchedRule) {
    return {
      name: matchedRule.name,
      rank: groupRank(matchedRule.name, channelGroups),
      sortKey: sortKeyForRule(matchedRule, displayName),
    }
  }

  if ((channelGroups.restrictedSourceRegions ?? []).includes(entry.sourceRegion)) {
    return null
  }

  const fallbackGroup = channelGroups.defaultGroup ?? entry.groupTitle ?? '未分组'
  return {
    name: fallbackGroup,
    rank: groupRank(fallbackGroup, channelGroups),
    sortKey: null,
  }
}

function matchesChannelRule(rule, displayName, entry) {
  if (rule.sourceRegions && !rule.sourceRegions.includes(entry.sourceRegion)) {
    return false
  }

  const fields = [
    displayName,
    entry.name,
    entry.attributes?.['tvg-name'],
  ].filter(Boolean)
  const haystack = fields.join(' ')

  return (rule.patterns ?? []).some((pattern) => {
    const regex = new RegExp(pattern, 'iu')
    return fields.some((field) => regex.test(field)) || regex.test(haystack)
  })
}

function groupRank(groupName, channelGroups) {
  const rank = (channelGroups.groupOrder ?? []).indexOf(groupName)
  return rank === -1 ? 100 : rank
}

function sortKeyForRule(rule, displayName) {
  if (rule.sort === 'cctv') {
    return cctvSortKey(displayName)
  }
  return null
}

function cctvSortKey(displayName) {
  const cctvNumber = displayName.match(/^CCTV[-\s]*(\d+)/i)?.[1]
  if (cctvNumber) {
    const number = Number.parseInt(cctvNumber, 10)
    if (/4K/i.test(displayName)) {
      return [number, 0.1, displayName]
    }
    if (/America/i.test(displayName)) {
      return [number, 0.2, displayName]
    }
    if (/Europe/i.test(displayName)) {
      return [number, 0.3, displayName]
    }
    return [number, 0, displayName]
  }

  if (/^CGTN/i.test(displayName)) {
    return [100, 0, displayName]
  }

  return [999, 0, displayName]
}

function compareSortKeys(left, right) {
  if (!left && !right) return 0
  if (!left) return 1
  if (!right) return -1

  const length = Math.max(left.length, right.length)
  for (let index = 0; index < length; index += 1) {
    const leftValue = left[index]
    const rightValue = right[index]
    if (leftValue === rightValue) {
      continue
    }
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return leftValue - rightValue
    }
    return String(leftValue ?? '').localeCompare(String(rightValue ?? ''), 'zh-Hans-CN')
  }
  return 0
}

function outputGroupRank(groupTitle) {
  const group = groupTitle ?? ''
  if (/央视|CCTV/i.test(group)) return 0
  if (/卫视/.test(group)) return 1
  if (/新闻/.test(group)) return 2
  if (/体育/.test(group)) return 3
  if (/少儿|动漫/.test(group)) return 4
  if (/纪录/.test(group)) return 5
  if (/电影|电视剧|影视/.test(group)) return 6
  if (/音乐/.test(group)) return 7
  return 20
}

function formatAttributes(attributes) {
  return Object.entries(attributes)
    .filter(([, value]) => value != null && value !== '')
    .map(([key, value]) => `${key}="${escapeAttribute(value)}"`)
    .join(' ')
}

function escapeAttribute(value) {
  return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

function countStatuses(items) {
  const counts = {}
  for (const item of items) {
    const key = statusKey(item.status)
    counts[key] = (counts[key] ?? 0) + 1
  }
  return {
    ok: counts.ok ?? 0,
    httpError: counts.httpError ?? 0,
    networkError: counts.networkError ?? 0,
    timeout: counts.timeout ?? 0,
    unchecked: counts.unchecked ?? 0,
  }
}

function statusKey(status) {
  switch (status) {
    case 'http-error':
      return 'httpError'
    case 'network-error':
      return 'networkError'
    default:
      return status
  }
}
