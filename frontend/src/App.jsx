import React, { useState, useEffect } from 'react'
import { Camera, Plus, Trash2, RefreshCw, Settings, Grid, List, Play, Pause, AlertCircle, CheckCircle, Wifi, WifiOff, Edit, Search, Loader2 } from 'lucide-react'

const API_URL = window.API_URL || '/api'

function App() {
  const [cameras, setCameras] = useState([])
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState('grid') // grid or list
  const [showAddModal, setShowAddModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(null) // camera to edit
  const [showScanModal, setShowScanModal] = useState(false)
  const [selectedCamera, setSelectedCamera] = useState(null)

  // Fetch cameras
  const fetchCameras = async () => {
    try {
      const res = await fetch(`${API_URL}/cameras/`)
      if (!res.ok) throw new Error('Failed to fetch cameras')
      const data = await res.json()
      setCameras(data.cameras || [])
    } catch (err) {
      setError(err.message)
    }
  }

  // Fetch nodes
  const fetchNodes = async () => {
    try {
      const res = await fetch(`${API_URL}/nodes/`)
      if (!res.ok) throw new Error('Failed to fetch nodes')
      const data = await res.json()
      setNodes(data)
    } catch (err) {
      console.error('Failed to fetch nodes:', err)
    }
  }

  useEffect(() => {
    const init = async () => {
      setLoading(true)
      await Promise.all([fetchCameras(), fetchNodes()])
      setLoading(false)
    }
    init()

    // Refresh every 10 seconds
    const interval = setInterval(fetchCameras, 10000)
    return () => clearInterval(interval)
  }, [])

  // Delete camera
  const deleteCamera = async (id) => {
    if (!confirm('Are you sure you want to delete this camera?')) return
    try {
      await fetch(`${API_URL}/cameras/${id}`, { method: 'DELETE' })
      fetchCameras()
    } catch (err) {
      setError(err.message)
    }
  }

  // Toggle camera status
  const toggleCamera = async (camera) => {
    try {
      const action = camera.status === 'running' ? 'stop' : 'start'
      await fetch(`${API_URL}/cameras/${camera.id}/${action}`, { method: 'POST' })
      fetchCameras()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Camera className="h-8 w-8 text-blue-500" />
              <h1 className="text-2xl font-bold">Falcon-Eye</h1>
              <span className="text-sm text-gray-400">Camera Dashboard</span>
            </div>
            <div className="flex items-center space-x-4">
              <button
                onClick={fetchCameras}
                className="p-2 hover:bg-gray-700 rounded-lg transition"
                title="Refresh"
              >
                <RefreshCw className="h-5 w-5" />
              </button>
              <div className="flex bg-gray-700 rounded-lg p-1">
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-2 rounded ${viewMode === 'grid' ? 'bg-gray-600' : ''}`}
                >
                  <Grid className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`p-2 rounded ${viewMode === 'list' ? 'bg-gray-600' : ''}`}
                >
                  <List className="h-4 w-4" />
                </button>
              </div>
              <button
                onClick={() => setShowScanModal(true)}
                className="flex items-center space-x-2 bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg transition"
              >
                <Search className="h-5 w-5" />
                <span>Scan</span>
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition"
              >
                <Plus className="h-5 w-5" />
                <span>Add Camera</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Stats Bar */}
      <div className="bg-gray-800/50 border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4 py-3">
          <div className="flex items-center space-x-8">
            <div className="flex items-center space-x-2">
              <Camera className="h-4 w-4 text-gray-400" />
              <span className="text-sm text-gray-400">Total:</span>
              <span className="font-semibold">{cameras.length}</span>
            </div>
            <div className="flex items-center space-x-2">
              <CheckCircle className="h-4 w-4 text-green-500" />
              <span className="text-sm text-gray-400">Online:</span>
              <span className="font-semibold text-green-500">
                {cameras.filter(c => c.status === 'running').length}
              </span>
            </div>
            <div className="flex items-center space-x-2">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <span className="text-sm text-gray-400">Offline:</span>
              <span className="font-semibold text-red-500">
                {cameras.filter(c => c.status !== 'running').length}
              </span>
            </div>
            <div className="flex items-center space-x-2">
              <Wifi className="h-4 w-4 text-blue-400" />
              <span className="text-sm text-gray-400">Nodes:</span>
              <span className="font-semibold">{nodes.length}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {error && (
          <div className="bg-red-500/10 border border-red-500 text-red-500 px-4 py-3 rounded-lg mb-6">
            {error}
            <button onClick={() => setError(null)} className="float-right">×</button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <RefreshCw className="h-8 w-8 animate-spin text-blue-500" />
          </div>
        ) : cameras.length === 0 ? (
          <div className="text-center py-16">
            <Camera className="h-16 w-16 mx-auto text-gray-600 mb-4" />
            <h2 className="text-xl font-semibold text-gray-400 mb-2">No cameras yet</h2>
            <p className="text-gray-500 mb-4">Add your first camera to get started</p>
            <button
              onClick={() => setShowAddModal(true)}
              className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg transition"
            >
              Add Camera
            </button>
          </div>
        ) : viewMode === 'grid' ? (
          <CameraGrid
            cameras={cameras}
            onDelete={deleteCamera}
            onToggle={toggleCamera}
            onSelect={setSelectedCamera}
            onEdit={setShowEditModal}
          />
        ) : (
          <CameraList
            cameras={cameras}
            onDelete={deleteCamera}
            onToggle={toggleCamera}
            onEdit={setShowEditModal}
          />
        )}
      </main>

      {/* Add Camera Modal */}
      {showAddModal && (
        <AddCameraModal
          nodes={nodes}
          onClose={() => setShowAddModal(false)}
          onAdd={() => {
            setShowAddModal(false)
            fetchCameras()
          }}
        />
      )}

      {/* Camera Preview Modal */}
      {selectedCamera && (
        <CameraPreviewModal
          camera={selectedCamera}
          onClose={() => setSelectedCamera(null)}
        />
      )}

      {/* Edit Camera Modal */}
      {showEditModal && (
        <EditCameraModal
          camera={showEditModal}
          onClose={() => setShowEditModal(null)}
          onSave={() => {
            setShowEditModal(null)
            fetchCameras()
          }}
        />
      )}

      {/* Scan Cameras Modal */}
      {showScanModal && (
        <ScanCamerasModal
          nodes={nodes}
          onClose={() => setShowScanModal(false)}
          onAdd={(camera) => {
            setShowScanModal(false)
            // Pre-fill add modal with scanned camera
            setShowAddModal(true)
          }}
        />
      )}
    </div>
  )
}

// Camera Grid Component
function CameraGrid({ cameras, onDelete, onToggle, onSelect, onEdit }) {
  const isDeleting = (camera) => camera.status === 'deleting'
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {cameras.map(camera => (
        <div
          key={camera.id}
          className={`bg-gray-800 rounded-lg overflow-hidden border border-gray-700 hover:border-gray-600 transition ${isDeleting(camera) ? 'opacity-50' : ''}`}
        >
          {/* Stream Preview */}
          <div
            className="aspect-video bg-gray-900 relative cursor-pointer"
            onClick={() => !isDeleting(camera) && onSelect(camera)}
          >
            {camera.status === 'running' ? (
              <img
                src={camera.stream_url}
                alt={camera.name}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.target.src = ''
                  e.target.className = 'hidden'
                }}
              />
            ) : isDeleting(camera) ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <Loader2 className="h-12 w-12 text-yellow-500 animate-spin" />
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <WifiOff className="h-12 w-12 text-gray-600" />
              </div>
            )}
            {/* Status Badge */}
            <div className={`absolute top-2 right-2 px-2 py-1 rounded text-xs font-medium ${
              camera.status === 'running' 
                ? 'bg-green-500/20 text-green-400'
                : camera.status === 'deleting'
                ? 'bg-yellow-500/20 text-yellow-400'
                : 'bg-red-500/20 text-red-400'
            }`}>
              {camera.status === 'running' ? 'LIVE' : camera.status === 'deleting' ? 'DELETING...' : 'OFFLINE'}
            </div>
          </div>
          
          {/* Camera Info */}
          <div className="p-3">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold truncate">{camera.name}</h3>
              <span className="text-xs text-gray-400 bg-gray-700 px-2 py-1 rounded uppercase">
                {camera.protocol}
              </span>
            </div>
            <p className="text-sm text-gray-400 truncate mb-3">{camera.node_name}</p>
            
            {/* Actions */}
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => onToggle(camera)}
                  disabled={isDeleting(camera)}
                  className={`p-2 rounded transition ${
                    isDeleting(camera) ? 'opacity-50 cursor-not-allowed' :
                    camera.status === 'running'
                      ? 'bg-red-500/20 hover:bg-red-500/30 text-red-400'
                      : 'bg-green-500/20 hover:bg-green-500/30 text-green-400'
                  }`}
                >
                  {camera.status === 'running' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </button>
                <button
                  onClick={() => onEdit(camera)}
                  disabled={isDeleting(camera)}
                  className={`p-2 rounded bg-gray-700 hover:bg-gray-600 transition text-blue-400 ${isDeleting(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <Edit className="h-4 w-4" />
                </button>
              </div>
              <button
                onClick={() => onDelete(camera.id)}
                disabled={isDeleting(camera)}
                className={`p-2 rounded bg-gray-700 hover:bg-gray-600 transition text-red-400 ${isDeleting(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// Camera List Component
function CameraList({ cameras, onDelete, onToggle, onEdit }) {
  const isDeleting = (camera) => camera.status === 'deleting'
  
  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-700/50">
          <tr>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Name</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Type</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Node</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Status</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700">
          {cameras.map(camera => (
            <tr key={camera.id} className={`hover:bg-gray-700/30 ${isDeleting(camera) ? 'opacity-50' : ''}`}>
              <td className="px-4 py-3 font-medium">{camera.name}</td>
              <td className="px-4 py-3">
                <span className="bg-gray-700 px-2 py-1 rounded text-sm uppercase">{camera.protocol}</span>
              </td>
              <td className="px-4 py-3 text-gray-400">{camera.node_name}</td>
              <td className="px-4 py-3">
                <span className={`inline-flex items-center space-x-1 ${
                  camera.status === 'running' ? 'text-green-400' : 
                  camera.status === 'deleting' ? 'text-yellow-400' : 'text-red-400'
                }`}>
                  {camera.status === 'running' ? <CheckCircle className="h-4 w-4" /> : 
                   camera.status === 'deleting' ? <Loader2 className="h-4 w-4 animate-spin" /> : 
                   <AlertCircle className="h-4 w-4" />}
                  <span>{camera.status}</span>
                </span>
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => onToggle(camera)}
                    disabled={isDeleting(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition ${isDeleting(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {camera.status === 'running' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </button>
                  <button
                    onClick={() => onEdit(camera)}
                    disabled={isDeleting(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition text-blue-400 ${isDeleting(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <Edit className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => onDelete(camera.id)}
                    disabled={isDeleting(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition text-red-400 ${isDeleting(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Add Camera Modal
function AddCameraModal({ nodes, onClose, onAdd }) {
  const [form, setForm] = useState({
    name: '',
    type: 'usb',
    node: nodes[0]?.name || '',
    source: '/dev/video0',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const typeOptions = {
    usb: { label: 'USB Camera', placeholder: '/dev/video0', help: 'Device path (e.g., /dev/video0)' },
    rtsp: { label: 'RTSP Stream', placeholder: 'rtsp://192.168.1.100:554/stream', help: 'RTSP URL with credentials if needed' },
    http: { label: 'HTTP/MJPEG', placeholder: 'http://192.168.1.100/mjpg/video.mjpg', help: 'HTTP stream URL' },
    onvif: { label: 'ONVIF Camera', placeholder: '192.168.1.100', help: 'Camera IP address' },
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      // Transform form data to API format
      const payload = {
        name: form.name,
        protocol: form.type,
      }

      // USB cameras require node_name and device_path
      if (form.type === 'usb') {
        payload.node_name = form.node
        payload.device_path = form.source || '/dev/video0'
      } else {
        // Network cameras: node is optional, source goes to source_url
        if (form.node) payload.node_name = form.node
        payload.source_url = form.source
      }

      const res = await fetch(`${API_URL}/cameras/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || data.error || 'Failed to add camera')
      }
      onAdd()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg w-full max-w-md mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold">Add Camera</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Camera Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="Living Room Camera"
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Camera Type</label>
            <select
              value={form.type}
              onChange={e => setForm({ ...form, type: e.target.value, source: '' })}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
            >
              {Object.entries(typeOptions).map(([key, { label }]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Target Node</label>
            <select
              value={form.node}
              onChange={e => setForm({ ...form, node: e.target.value })}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              required
            >
              {nodes.map(node => (
                <option key={node.name} value={node.name}>{node.name} ({node.ip})</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">Select the node where the camera is connected</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              {typeOptions[form.type].label} Source
            </label>
            <input
              type="text"
              value={form.source}
              onChange={e => setForm({ ...form, source: e.target.value })}
              placeholder={typeOptions[form.type].placeholder}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              required
            />
            <p className="text-xs text-gray-400 mt-1">{typeOptions[form.type].help}</p>
          </div>

          <div className="flex items-center justify-end space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-400 hover:text-white transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-4 py-2 rounded-lg transition flex items-center space-x-2"
            >
              {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
              <span>{submitting ? 'Adding...' : 'Add Camera'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Camera Preview Modal
function CameraPreviewModal({ camera, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50" onClick={onClose}>
      <div className="max-w-4xl w-full mx-4" onClick={e => e.stopPropagation()}>
        <div className="bg-gray-800 rounded-lg overflow-hidden border border-gray-700">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
            <div>
              <h3 className="font-semibold">{camera.name}</h3>
              <p className="text-sm text-gray-400">{camera.node_name}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl">×</button>
          </div>
          <div className="aspect-video bg-black">
            {camera.status === 'running' ? (
              <img
                src={camera.stream_url}
                alt={camera.name}
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <div className="text-center">
                  <WifiOff className="h-16 w-16 mx-auto text-gray-600 mb-4" />
                  <p className="text-gray-400">Camera is offline</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Edit Camera Modal
function EditCameraModal({ camera, onClose, onSave }) {
  const [form, setForm] = useState({
    name: camera.name,
    location: camera.location || '',
    resolution: camera.resolution || '640x480',
    framerate: camera.framerate || 15,
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const res = await fetch(`${API_URL}/cameras/${camera.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || data.error || 'Failed to update camera')
      }
      onSave()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg w-full max-w-md mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold">Edit Camera</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Camera Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Location</label>
            <input
              type="text"
              value={form.location}
              onChange={e => setForm({ ...form, location: e.target.value })}
              placeholder="e.g., Living Room, Office"
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Resolution</label>
              <select
                value={form.resolution}
                onChange={e => setForm({ ...form, resolution: e.target.value })}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="320x240">320x240</option>
                <option value="640x480">640x480</option>
                <option value="800x600">800x600</option>
                <option value="1280x720">1280x720 (HD)</option>
                <option value="1920x1080">1920x1080 (FHD)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Framerate</label>
              <input
                type="number"
                value={form.framerate}
                onChange={e => setForm({ ...form, framerate: parseInt(e.target.value) })}
                min="1"
                max="60"
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="text-sm text-gray-400">
            <p><strong>Type:</strong> {camera.protocol.toUpperCase()}</p>
            <p><strong>Node:</strong> {camera.node_name}</p>
            <p><strong>Device:</strong> {camera.device_path || camera.source_url}</p>
          </div>

          <div className="flex items-center justify-end space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-400 hover:text-white transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-4 py-2 rounded-lg transition flex items-center space-x-2"
            >
              {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
              <span>{submitting ? 'Saving...' : 'Save Changes'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Scan Cameras Modal
function ScanCamerasModal({ nodes, onClose, onAdd }) {
  const [scanning, setScanning] = useState(false)
  const [cameras, setCameras] = useState([])
  const [scannedNodes, setScannedNodes] = useState([])
  const [errors, setErrors] = useState([])
  const [adding, setAdding] = useState(null)

  const scanCameras = async () => {
    setScanning(true)
    setCameras([])
    setErrors([])
    
    try {
      const res = await fetch(`${API_URL}/nodes/scan/cameras`)
      if (!res.ok) throw new Error('Scan failed')
      const data = await res.json()
      setCameras(data.cameras || [])
      setScannedNodes(data.scanned_nodes || [])
      setErrors(data.errors || [])
    } catch (err) {
      setErrors([err.message])
    } finally {
      setScanning(false)
    }
  }

  const addCamera = async (cam) => {
    setAdding(cam.device_path)
    try {
      const res = await fetch(`${API_URL}/cameras/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: cam.device_name.replace(/[^a-zA-Z0-9\s]/g, '').trim() || 'USB Camera',
          protocol: 'usb',
          node_name: cam.node_name,
          device_path: cam.device_path,
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to add camera')
      }
      // Remove from list
      setCameras(cameras.filter(c => c.device_path !== cam.device_path || c.node_name !== cam.node_name))
      onAdd(cam)
    } catch (err) {
      setErrors([...errors, err.message])
    } finally {
      setAdding(null)
    }
  }

  useEffect(() => {
    scanCameras()
  }, [])

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold">Scan for USB Cameras</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
        </div>
        
        <div className="p-6">
          {errors.length > 0 && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm mb-4">
              {errors.map((e, i) => <p key={i}>{e}</p>)}
            </div>
          )}

          {scanning ? (
            <div className="text-center py-8">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500 mb-4" />
              <p className="text-gray-400">Scanning nodes for USB cameras...</p>
            </div>
          ) : cameras.length === 0 ? (
            <div className="text-center py-8">
              <Camera className="h-12 w-12 mx-auto text-gray-600 mb-4" />
              <p className="text-gray-400 mb-4">No USB cameras found</p>
              <p className="text-sm text-gray-500 mb-4">Scanned nodes: {scannedNodes.join(', ') || 'none'}</p>
              <button
                onClick={scanCameras}
                className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg transition"
              >
                Scan Again
              </button>
            </div>
          ) : (
            <>
              <p className="text-sm text-gray-400 mb-4">Found {cameras.length} camera(s) on {scannedNodes.length} node(s)</p>
              <div className="space-y-3 max-h-64 overflow-y-auto">
                {cameras.map((cam, i) => (
                  <div key={i} className="flex items-center justify-between bg-gray-700/50 rounded-lg p-3">
                    <div>
                      <p className="font-medium">{cam.device_name}</p>
                      <p className="text-sm text-gray-400">{cam.node_name} • {cam.device_path}</p>
                    </div>
                    <button
                      onClick={() => addCamera(cam)}
                      disabled={adding === cam.device_path}
                      className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-3 py-1.5 rounded-lg text-sm transition flex items-center space-x-1"
                    >
                      {adding === cam.device_path ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Plus className="h-4 w-4" />
                          <span>Add</span>
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
              <button
                onClick={scanCameras}
                className="w-full mt-4 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg transition flex items-center justify-center space-x-2"
              >
                <RefreshCw className="h-4 w-4" />
                <span>Rescan</span>
              </button>
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 text-gray-400 hover:text-white transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
