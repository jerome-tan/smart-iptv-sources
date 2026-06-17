import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()

function readJson(relativePath) {
  const filePath = path.join(root, relativePath)
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const index = readJson('public/index.json')
const version = readJson('public/version.json')
const channelMetadata = readJson('sources/channel-metadata.json')
const upstreams = readJson('sources/upstreams.json')
const rules = readJson('sources/curation-rules.json')

assert(index.schemaVersion === 1, 'public/index.json schemaVersion must be 1')
assert(Array.isArray(index.playlists), 'public/index.json playlists must be an array')
assert(index.playlists.length > 0, 'public/index.json must contain at least one playlist')
assert(version.schemaVersion === 1, 'public/version.json schemaVersion must be 1')
assert(Array.isArray(upstreams.sources), 'sources/upstreams.json sources must be an array')
assert(channelMetadata.schemaVersion === 1, 'sources/channel-metadata.json schemaVersion must be 1')
assert(
  channelMetadata.channels && typeof channelMetadata.channels === 'object' && !Array.isArray(channelMetadata.channels),
  'sources/channel-metadata.json channels must be an object'
)
assert(rules.schemaVersion === 1, 'sources/curation-rules.json schemaVersion must be 1')
assert(Array.isArray(rules.playlists), 'sources/curation-rules.json playlists must be an array')

for (const playlist of index.playlists) {
  assert(playlist.id, 'playlist id is required')
  assert(playlist.name, `playlist ${playlist.id} name is required`)
  assert(playlist.url, `playlist ${playlist.id} url is required`)
  assert(version.playlists?.[playlist.id], `public/version.json missing playlist version info: ${playlist.id}`)

  if (playlist.url.startsWith('/')) {
    const playlistPath = path.join(root, 'public', playlist.url)
    assert(fs.existsSync(playlistPath), `playlist file not found: ${playlist.url}`)
    const content = fs.readFileSync(playlistPath, 'utf8')
    assert(content.startsWith('#EXTM3U'), `playlist must start with #EXTM3U: ${playlist.url}`)
    const streamUrls = content.split(/\r?\n/).filter((line) => /^https?:\/\//.test(line))
    assert(streamUrls.length > 0, `playlist must contain at least one stream URL: ${playlist.url}`)
  }

  if (playlist.healthUrl?.startsWith('/')) {
    const healthPath = path.join(root, 'public', playlist.healthUrl)
    assert(fs.existsSync(healthPath), `health file not found: ${playlist.healthUrl}`)
    const health = JSON.parse(fs.readFileSync(healthPath, 'utf8'))
    assert(health.schemaVersion === 1, `health schemaVersion must be 1: ${playlist.healthUrl}`)
    assert(Array.isArray(health.upstreams), `health upstreams must be an array: ${playlist.healthUrl}`)
    assert(Array.isArray(health.streams), `health streams must be an array: ${playlist.healthUrl}`)
    assert(health.streams.length > 0, `health streams must contain at least one item: ${playlist.healthUrl}`)
  }
}

for (const [playlistId, playlistVersion] of Object.entries(version.playlists ?? {})) {
  assert(playlistVersion.streamCount > 0, `version streamCount must be greater than 0: ${playlistId}`)
  assert(playlistVersion.channelCount > 0, `version channelCount must be greater than 0: ${playlistId}`)
}

for (const source of upstreams.sources) {
  assert(source.id, 'upstream source id is required')
  assert(source.name, `upstream source ${source.id} name is required`)
  assert(source.url, `upstream source ${source.id} url is required`)
  assert(/^https?:\/\//.test(source.url), `upstream source ${source.id} must use http(s)`)
}

for (const [channelName, metadata] of Object.entries(channelMetadata.channels)) {
  assert(channelName.trim(), 'metadata channel name must not be blank')
  assert(metadata && typeof metadata === 'object' && !Array.isArray(metadata), `metadata for ${channelName} must be an object`)
  assert(
    typeof metadata.description === 'string' && metadata.description.trim().length >= 12,
    `metadata ${channelName} description must be a useful string`
  )
  if (metadata.tags != null) {
    assert(Array.isArray(metadata.tags), `metadata ${channelName} tags must be an array`)
    for (const tag of metadata.tags) {
      assert(typeof tag === 'string' && tag.trim(), `metadata ${channelName} tags must be non-empty strings`)
    }
  }
}

const upstreamIds = new Set(upstreams.sources.map((source) => source.id))
for (const playlist of rules.playlists) {
  assert(playlist.id, 'curation playlist id is required')
  assert(Array.isArray(playlist.upstreamSourceIds), `playlist ${playlist.id} upstreamSourceIds must be an array`)
  for (const sourceId of playlist.upstreamSourceIds) {
    assert(upstreamIds.has(sourceId), `playlist ${playlist.id} references unknown upstream source: ${sourceId}`)
  }
}

console.log('Source repository validation passed.')
