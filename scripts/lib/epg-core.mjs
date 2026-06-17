import { gunzipSync } from 'node:zlib'

const XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
const GZIP_MAGIC_0 = 0x1f
const GZIP_MAGIC_1 = 0x8b

export function collectPlaylistGuideKeys(entries) {
  const ids = new Set()
  const names = new Set()
  const outputIdById = new Map()
  const outputIdByName = new Map()

  for (const entry of entries) {
    const outputId = preferredOutputId(entry)
    const tvgId = entry.attributes?.['tvg-id']
    if (tvgId) {
      for (const id of guideIdCandidates(tvgId)) {
        ids.add(id)
        remember(outputIdById, id, outputId)
      }
    }

    for (const name of [
      entry.attributes?.['tvg-name'],
      entry.displayName,
      entry.name,
      entry.normalizedName,
    ]) {
      for (const key of guideNameCandidates(name)) {
        names.add(key)
        remember(outputIdByName, key, outputId)
      }
    }
  }

  return { ids, names, outputIdById, outputIdByName }
}

export function buildFilteredXmltv({ documents, entries, generatedAt }) {
  const keys = collectPlaylistGuideKeys(entries)
  const outputChannelIds = new Set()
  const channelIdMap = new Map()
  const channels = []
  const programs = []

  for (const document of documents) {
    const channelBlocks = extractBlocks(document.xml, 'channel')
    for (const block of channelBlocks) {
      const channelId = xmlAttribute(block, 'id')
      if (!channelId) {
        continue
      }

      const outputId = resolveOutputId(block, keys)
      if (outputId) {
        channelIdMap.set(channelId, outputId)
        if (!outputChannelIds.has(outputId)) {
          outputChannelIds.add(outputId)
          channels.push(rewriteXmlAttribute(block.trim(), 'id', outputId))
        }
      }
    }
  }

  for (const document of documents) {
    const programBlocks = extractBlocks(document.xml, 'programme')
    for (const block of programBlocks) {
      const channelId = xmlAttribute(block, 'channel')
      const outputId = channelId ? channelIdMap.get(channelId) : null
      if (outputId) {
        programs.push(rewriteXmlAttribute(block.trim(), 'channel', outputId))
      }
    }
  }

  const body = [
    XML_DECLARATION,
    `<tv generator-info-name="Smart IPTV Sources" generator-info-url="https://smart-iptv-sources.pages.dev" source-info-name="Smart IPTV Sources" source-data-url="generated:${generatedAt}">`,
    ...channels.map((block) => indent(block)),
    ...programs.map((block) => indent(block)),
    '</tv>',
    '',
  ].join('\n')

  return {
    channelCount: outputChannelIds.size,
    programCount: programs.length,
    xml: body,
  }
}

export function decodeXmltvPayload(payload, url = '') {
  const buffer = Buffer.isBuffer(payload) ? payload : Buffer.from(payload)
  const isGzip = buffer.length >= 2 &&
    buffer[0] === GZIP_MAGIC_0 &&
    buffer[1] === GZIP_MAGIC_1

  if (isGzip || /\.gz(?:[?#].*)?$/i.test(url)) {
    return gunzipSync(buffer).toString('utf8')
  }
  return buffer.toString('utf8')
}

export async function fetchXmltv(url, { fetchImpl = globalThis.fetch, timeoutMs = 30000 } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(url, {
      headers: {
        'Accept': 'application/xml, text/xml, application/gzip, application/octet-stream, */*',
        'User-Agent': 'SmartIPTVSourceBuilder/0.1',
      },
      signal: controller.signal,
    })
    const bytes = Buffer.from(await response.arrayBuffer())
    return {
      httpStatus: response.status,
      ok: response.ok,
      text: response.ok ? decodeXmltvPayload(bytes, url) : bytes.toString('utf8'),
    }
  } finally {
    clearTimeout(timeout)
  }
}

function guideIdCandidates(value) {
  const trimmed = String(value).trim()
  if (!trimmed) {
    return []
  }
  const candidates = [trimmed]
  const withoutQualitySuffix = trimmed.replace(/@(UHD|FHD|HD|SD|LD)$/i, '')
  if (withoutQualitySuffix !== trimmed) {
    candidates.push(withoutQualitySuffix)
  }
  return candidates
}

function preferredOutputId(entry) {
  return [
    entry.displayName,
    entry.normalizedName,
    entry.attributes?.['tvg-name'],
    entry.name,
    entry.attributes?.['tvg-id'],
  ]
    .map((value) => String(value ?? '').trim())
    .find(Boolean)
}

function remember(map, key, outputId) {
  if (key && outputId && !map.has(key)) {
    map.set(key, outputId)
  }
}

function resolveOutputId(block, keys) {
  const channelId = xmlAttribute(block, 'id')
  if (channelId) {
    for (const id of guideIdCandidates(channelId)) {
      if (keys.outputIdById.has(id)) {
        return keys.outputIdById.get(id)
      }
    }
  }

  const displayNames = childTexts(block, 'display-name')
  for (const name of displayNames) {
    for (const key of guideNameCandidates(name)) {
      const outputId = keys.outputIdByName.get(key)
      if (outputId) {
        return outputId
      }
    }
  }

  return null
}

function guideNameCandidates(value) {
  const key = normalizeGuideName(value)
  if (!key) {
    return []
  }
  const aliases = [key]
  const cctvBaseKey = key.replace(
    /^(cctv\d+\+?)(综合|财经|综艺|中文国际|体育|体育赛事|电影|国防军事|电视剧|纪录|科教|戏曲|社会与法|新闻|少儿|音乐|奥林匹克|农业农村)$/u,
    '$1',
  )
  if (cctvBaseKey !== key) {
    aliases.push(cctvBaseKey)
  }
  return aliases
}

function normalizeGuideName(value) {
  return String(value ?? '')
    .replace(/\s*[\[(]\s*(4K|[0-9]{3,4}[pi])\s*[\])]/gi, '')
    .replace(/\s+([0-9]{3,4}[pi])$/i, '')
    .toLowerCase()
    .replace(/＋/g, '+')
    .replace(/plus/g, '+')
    .replace(/[^a-z0-9\u4e00-\u9fff+]/g, '')
}

function extractBlocks(xml, tagName) {
  const blocks = []
  const pattern = new RegExp(`<${tagName}\\b[^>]*(?:/>|>[\\s\\S]*?<\\/${tagName}>)`, 'gi')
  let match = pattern.exec(xml)
  while (match) {
    blocks.push(match[0])
    match = pattern.exec(xml)
  }
  return blocks
}

function xmlAttribute(block, attributeName) {
  const pattern = new RegExp(`\\b${escapeRegExp(attributeName)}\\s*=\\s*(['"])([\\s\\S]*?)\\1`, 'i')
  const match = block.match(pattern)
  return match?.[2] ? decodeXmlEntities(match[2].trim()) : null
}

function rewriteXmlAttribute(block, attributeName, value) {
  const pattern = new RegExp(`\\b${escapeRegExp(attributeName)}\\s*=\\s*(['"])([\\s\\S]*?)\\1`, 'i')
  return block.replace(pattern, `${attributeName}="${escapeXmlAttribute(value)}"`)
}

function childTexts(block, tagName) {
  const values = []
  const pattern = new RegExp(`<${tagName}\\b[^>]*>([\\s\\S]*?)<\\/${tagName}>`, 'gi')
  let match = pattern.exec(block)
  while (match) {
    values.push(decodeXmlEntities(stripTags(match[1]).trim()))
    match = pattern.exec(block)
  }
  return values.filter(Boolean)
}

function stripTags(value) {
  return value.replace(/<[^>]+>/g, '')
}

function decodeXmlEntities(value) {
  return value
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
}

function escapeXmlAttribute(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function indent(block) {
  return block
    .split('\n')
    .map((line) => `  ${line}`)
    .join('\n')
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
