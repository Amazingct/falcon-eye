import React from 'react'
import { authUrl } from '../App'
import { Download, Camera, Clock } from 'lucide-react'
import { authUrl } from '../App'

function encodePathPreserveSlashes(p) {
  return p.split('/').map(encodeURIComponent).join('/')
}

function resolveMediaUrl(apiUrl, path, cloudUrl, url) {
  let resolved = ''
  if (url) {
    // Explicit URL from the media item (e.g. /api/recordings/{id}/download)
    resolved = url.startsWith('http') ? url : url
  } else if (cloudUrl) {
    // Cloud URL (already a full https:// URL) — still needs auth if proxied through API
    resolved = cloudUrl
  } else if (!path) {
    return ''
  } else if (path.startsWith('http://') || path.startsWith('https://')) {
    resolved = path
  } else if (path.startsWith('/')) {
    resolved = path
  } else {
    // Treat as shared filesystem path
    const base = apiUrl || '/api'
    resolved = `${base}/files/read/${encodePathPreserveSlashes(path)}`
  }
  // Append auth token for API-served URLs (not external cloud URLs)
  if (resolved && !resolved.startsWith('https://') && !resolved.startsWith('http://')) {
    // Relative API path — needs auth
    return authUrl(resolved)
  }
  if (resolved && resolved.includes('/api/')) {
    // Absolute API URL — needs auth
    return authUrl(resolved)
  }
  return resolved
}

function extLower(item) {
  const t = (item?.type || '').toString().toLowerCase().replace(/^\./, '')
  if (t) return t
  const p = (item?.path || '').toString()
  const dot = p.lastIndexOf('.')
  return dot >= 0 ? p.slice(dot + 1).toLowerCase() : ''
}

function isImageExt(ext) {
  return ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext)
}
function isVideoExt(ext) {
  return ['mp4', 'webm', 'mov', 'mkv', 'avi', '3gp'].includes(ext)
}
function isAudioExt(ext) {
  return ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac'].includes(ext)
}

export default function ChatMedia({ content, apiUrl }) {
  const generalCaption = content?.general_caption ?? null
  // Support both structured format {general_caption, media: [...]} and legacy single object {path, url, ...}
  let items = Array.isArray(content?.media) ? content.media : []
  if (!items.length && content && (content.path || content.url) && !content.media) {
    // Legacy: content is a single media object — wrap it
    items = [content]
  }

  if (!items.length && !generalCaption) {
    return <div className="text-sm text-gray-300">(no media)</div>
  }

  return (
    <div className="space-y-2">
      {generalCaption && (
        <div className="text-sm text-gray-100 whitespace-pre-wrap">{generalCaption}</div>
      )}

      <div className="grid grid-cols-1 gap-2">
        {items.map((item, idx) => {
          const ext = extLower(item)
          const rawUrl = resolveMediaUrl(apiUrl, item?.path || '', item?.cloud_url, item?.url)
          const url = authUrl(rawUrl)
          const caption = item?.caption ?? null
          const name = item?.name ?? null
          const cam = item?.cam ?? null
          const timestamps = item?.timestamps ?? null

          return (
            <div key={idx} className="rounded-lg border border-gray-600/60 bg-gray-800/30 p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    {name && <span className="text-xs text-gray-300 truncate">{name}</span>}
                    {ext && <span className="text-[10px] uppercase tracking-wide text-gray-400">{ext}</span>}
                    {cam && (cam.name || cam.cam_id) && (
                      <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-300">
                        <Camera className="h-3 w-3" />
                        <span className="truncate">{cam.name || cam.cam_id}</span>
                      </span>
                    )}
                    {timestamps && (
                      <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-300">
                        <Clock className="h-3 w-3" />
                        <span className="truncate">{typeof timestamps === 'string' ? timestamps : JSON.stringify(timestamps)}</span>
                      </span>
                    )}
                  </div>
                </div>

                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-shrink-0 inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                    title="Download / open"
                  >
                    <Download className="h-4 w-4" />
                  </a>
                )}
              </div>

              {/* Media body */}
              {url ? (
                <>
                  {isImageExt(ext) ? (
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      <img
                        src={url}
                        alt={name || caption || 'image'}
                        className="mt-2 w-full max-h-72 object-cover rounded-md border border-gray-700"
                        loading="lazy"
                      />
                    </a>
                  ) : isVideoExt(ext) ? (
                    <video
                      className="mt-2 w-full max-h-80 rounded-md border border-gray-700"
                      controls
                      src={url}
                    />
                  ) : isAudioExt(ext) ? (
                    <audio className="mt-2 w-full" controls src={url} />
                  ) : (
                    <div className="mt-2 text-xs text-gray-300">
                      <a href={url} target="_blank" rel="noopener noreferrer" className="underline">
                        Open file
                      </a>
                      {item?.path && <span className="text-gray-500"> · {item.path}</span>}
                    </div>
                  )}
                </>
              ) : (
                <div className="mt-2 text-xs text-gray-400">(missing path)</div>
              )}

              {caption && (
                <div className="mt-2 text-xs text-gray-200 whitespace-pre-wrap">{caption}</div>
              )}
              {cam?.location && (
                <div className="mt-1 text-[10px] text-gray-500">Location: {cam.location}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

