/**
 * Auth utilities — shared between App.jsx and child components.
 * Token is managed here to avoid circular imports.
 */

let _authToken = localStorage.getItem('falcon_eye_token')
let _onAuthFailure = null

export function getAuthToken() { return _authToken }
export function setAuthToken(token) { _authToken = token }
export function setOnAuthFailure(fn) { _onAuthFailure = fn }

export function authFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (_authToken) {
    headers['Authorization'] = `Bearer ${_authToken}`
  }
  return fetch(url, { ...options, headers }).then(res => {
    if (res.status === 401 && _onAuthFailure) {
      _onAuthFailure()
    }
    return res
  })
}

/** Append token to URL for <img src>, <video src> etc. */
export function authUrl(url) {
  if (!_authToken || !url) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(_authToken)}`
}
