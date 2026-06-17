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
const upstreams = readJson('sources/upstreams.json')

assert(index.schemaVersion === 1, 'public/index.json schemaVersion must be 1')
assert(Array.isArray(index.playlists), 'public/index.json playlists must be an array')
assert(index.playlists.length > 0, 'public/index.json must contain at least one playlist')
assert(version.schemaVersion === 1, 'public/version.json schemaVersion must be 1')
assert(Array.isArray(upstreams.sources), 'sources/upstreams.json sources must be an array')

for (const playlist of index.playlists) {
  assert(playlist.id, 'playlist id is required')
  assert(playlist.name, `playlist ${playlist.id} name is required`)
  assert(playlist.url, `playlist ${playlist.id} url is required`)

  if (playlist.url.startsWith('/')) {
    const playlistPath = path.join(root, 'public', playlist.url)
    assert(fs.existsSync(playlistPath), `playlist file not found: ${playlist.url}`)
    const content = fs.readFileSync(playlistPath, 'utf8')
    assert(content.startsWith('#EXTM3U'), `playlist must start with #EXTM3U: ${playlist.url}`)
  }
}

console.log('Source repository validation passed.')

