import React, { useState, useEffect } from 'react'
import { Camera, Plus, Trash2, RefreshCw, Settings, Grid, List, Play, Pause, AlertCircle, CheckCircle, Wifi, WifiOff, Edit, Search, Loader2, Save, RotateCcw, MessageCircle, Send, X, PanelRightOpen, PanelRightClose, Circle, Video, Square, Film, Clock, Download, ChevronDown, ChevronRight } from 'lucide-react'

const API_URL = window.API_URL || '/api'

function App() {
  const [cameras, setCameras] = useState([])
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState('grid') // grid or list
  const [currentPage, setCurrentPage] = useState('cameras') // cameras or recordings
  const [showAddModal, setShowAddModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(null) // camera to edit
  const [showScanModal, setShowScanModal] = useState(false)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [selectedCamera, setSelectedCamera] = useState(null)
  const [showChat, setShowChat] = useState(false)
  const [chatDocked, setChatDocked] = useState(true)
  const [chatWidth, setChatWidth] = useState(450)

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

    // Refresh every 5 seconds (faster when cameras are being created/deleted)
    const interval = setInterval(fetchCameras, 5000)
    return () => clearInterval(interval)
  }, [])

  // Auto-dismiss errors after 8 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 8000)
      return () => clearTimeout(timer)
    }
  }, [error])

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

  // Restart camera
  const restartCamera = async (camera) => {
    try {
      await fetch(`${API_URL}/cameras/${camera.id}/restart`, { method: 'POST' })
      fetchCameras()
    } catch (err) {
      setError(err.message)
    }
  }

  // Calculate margin for layout when chat is docked
  const chatMargin = showChat && chatDocked ? chatWidth : 0

  return (
    <div className="min-h-screen bg-gray-900 text-white flex">
      {/* Main content area - shrinks when chat is docked */}
      <div className="flex-1 flex flex-col min-w-0 transition-all duration-200" style={{ marginRight: chatMargin ? `${chatMargin}px` : 0 }}>
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Camera className="h-8 w-8 text-blue-500" />
              <h1 className="text-2xl font-bold">Falcon-Eye</h1>
              {/* Page Toggle */}
              <div className="flex bg-gray-700 rounded-lg p-1 ml-4">
                <button
                  onClick={() => setCurrentPage('cameras')}
                  className={`px-3 py-1 rounded flex items-center space-x-1 text-sm ${currentPage === 'cameras' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                >
                  <Camera className="h-4 w-4" />
                  <span>Cameras</span>
                </button>
                <button
                  onClick={() => setCurrentPage('recordings')}
                  className={`px-3 py-1 rounded flex items-center space-x-1 text-sm ${currentPage === 'recordings' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                >
                  <Film className="h-4 w-4" />
                  <span>Recordings</span>
                </button>
              </div>
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
              <button
                onClick={() => setShowSettingsModal(true)}
                className="p-2 hover:bg-gray-700 rounded-lg transition"
                title="Settings"
              >
                <Settings className="h-5 w-5" />
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
          <div className="bg-red-500/20 border border-red-500 text-red-400 px-4 py-3 rounded-lg mb-6 flex items-center justify-between animate-pulse">
            <div className="flex items-center space-x-2">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-red-300 hover:text-white ml-4">×</button>
          </div>
        )}

        {currentPage === 'cameras' ? (
          // Cameras View
          loading ? (
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
              onRestart={restartCamera}
              onError={setError}
            />
          ) : (
            <CameraList
              cameras={cameras}
              onDelete={deleteCamera}
              onToggle={toggleCamera}
              onEdit={setShowEditModal}
              onRestart={restartCamera}
              onError={setError}
            />
          )
        ) : (
          // Recordings View
          <RecordingsPage cameras={cameras} />
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
          onAdded={(count) => {
            setShowScanModal(false)
            fetchCameras()
          }}
        />
      )}

      {/* Settings Modal */}
      {showSettingsModal && (
        <SettingsModal
          onClose={() => setShowSettingsModal(false)}
          onClearAll={() => {
            setShowSettingsModal(false)
            fetchCameras()
          }}
        />
      )}
      </div>

      {/* Chat Widget - docked version is part of flex layout */}
      <ChatWidget 
        isOpen={showChat}
        onToggle={() => setShowChat(!showChat)}
        isDocked={chatDocked}
        onDockToggle={() => setChatDocked(!chatDocked)}
        panelWidth={chatWidth}
        onWidthChange={setChatWidth}
      />
    </div>
  )
}

// Camera Grid Component
function CameraGrid({ cameras, onDelete, onToggle, onSelect, onEdit, onRestart, onError }) {
  const [recordingStatus, setRecordingStatus] = useState({}) // camera_id -> { recording: bool }
  
  const isDeleting = (camera) => camera.status === 'deleting'
  const isCreating = (camera) => camera.status === 'creating' || camera.status === 'pending'
  const isBusy = (camera) => isDeleting(camera) || isCreating(camera)
  
  // Fetch recording status for running cameras
  useEffect(() => {
    const fetchRecordingStatus = async () => {
      const runningCameras = cameras.filter(c => c.status === 'running')
      for (const cam of runningCameras) {
        try {
          const res = await fetch(`${API_URL}/cameras/${cam.id}/recording/status`)
          if (res.ok) {
            const data = await res.json()
            setRecordingStatus(prev => ({ ...prev, [cam.id]: data }))
          }
        } catch (e) {
          // Ignore errors
        }
      }
    }
    fetchRecordingStatus()
    const interval = setInterval(fetchRecordingStatus, 10000) // Check every 10s
    return () => clearInterval(interval)
  }, [cameras])
  
  const startRecording = async (camera) => {
    try {
      const res = await fetch(`${API_URL}/cameras/${camera.id}/recording/start`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setRecordingStatus(prev => ({ ...prev, [camera.id]: data.recording || data }))
      } else {
        const errorMsg = data.detail || data.message || 'Failed to start recording'
        onError(errorMsg)
      }
    } catch (e) {
      onError(`Failed to start recording: ${e.message}`)
    }
  }
  
  const stopRecording = async (camera) => {
    try {
      const res = await fetch(`${API_URL}/cameras/${camera.id}/recording/stop`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setRecordingStatus(prev => ({ ...prev, [camera.id]: data.recording || data }))
      } else {
        const errorMsg = data.detail || data.message || 'Failed to stop recording'
        onError(errorMsg)
      }
    } catch (e) {
      onError(`Failed to stop recording: ${e.message}`)
    }
  }
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {cameras.map(camera => (
        <div
          key={camera.id}
          className={`bg-gray-800 rounded-lg overflow-hidden border border-gray-700 hover:border-gray-600 transition ${isBusy(camera) ? 'opacity-75' : ''}`}
        >
          {/* Stream Preview */}
          <div
            className="aspect-video bg-gray-900 relative cursor-pointer"
            onClick={() => !isBusy(camera) && onSelect(camera)}
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
            ) : isBusy(camera) ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <Loader2 className={`h-12 w-12 animate-spin ${isCreating(camera) ? 'text-blue-500' : 'text-yellow-500'}`} />
                <p className="text-sm text-gray-400 mt-2">
                  {isCreating(camera) ? 'Starting camera...' : 'Removing...'}
                </p>
              </div>
            ) : camera.status === 'stopped' ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
                <Settings className="h-12 w-12 text-gray-500 mb-2" />
                <p className="text-sm text-gray-400">Click Edit to configure</p>
                <p className="text-xs text-gray-500">then Start to begin streaming</p>
              </div>
            ) : camera.status === 'error' ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4 bg-red-900/20">
                <AlertCircle className="h-10 w-10 text-red-500 mb-2" />
                <p className="text-sm text-red-400 font-medium">Error</p>
                {camera.metadata?.error && (
                  <p className="text-xs text-red-300/80 mt-1 px-2 max-w-full break-words" title={camera.metadata.error}>
                    {camera.metadata.error.length > 80 
                      ? camera.metadata.error.substring(0, 80) + '...' 
                      : camera.metadata.error}
                  </p>
                )}
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <WifiOff className="h-12 w-12 text-gray-600" />
              </div>
            )}
            {/* Status Badge */}
            <div className={`absolute top-2 right-2 px-2 py-1 rounded text-xs font-medium flex items-center space-x-1 ${
              camera.status === 'running' 
                ? 'bg-green-500/20 text-green-400'
                : isCreating(camera)
                ? 'bg-blue-500/20 text-blue-400'
                : camera.status === 'deleting'
                ? 'bg-yellow-500/20 text-yellow-400'
                : camera.status === 'stopped'
                ? 'bg-gray-500/20 text-gray-400'
                : 'bg-red-500/20 text-red-400'
            }`}>
              {isBusy(camera) && <Loader2 className="h-3 w-3 animate-spin" />}
              <span>
                {camera.status === 'running' ? 'LIVE' : 
                 isCreating(camera) ? 'ADDING...' :
                 camera.status === 'deleting' ? 'DELETING...' :
                 camera.status === 'stopped' ? 'STOPPED' : 'ERROR'}
              </span>
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
                  disabled={isBusy(camera)}
                  className={`p-2 rounded transition ${
                    isBusy(camera) ? 'opacity-50 cursor-not-allowed bg-gray-700' :
                    camera.status === 'running'
                      ? 'bg-red-500/20 hover:bg-red-500/30 text-red-400'
                      : 'bg-green-500/20 hover:bg-green-500/30 text-green-400'
                  }`}
                  title={camera.status === 'running' ? 'Stop' : 'Start'}
                >
                  {camera.status === 'running' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </button>
                <button
                  onClick={() => onRestart(camera)}
                  disabled={isBusy(camera)}
                  className={`p-2 rounded bg-gray-700 hover:bg-gray-600 transition text-orange-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                  title="Restart"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
                <button
                  onClick={() => onEdit(camera)}
                  disabled={isBusy(camera)}
                  className={`p-2 rounded bg-gray-700 hover:bg-gray-600 transition text-blue-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                  title="Edit"
                >
                  <Edit className="h-4 w-4" />
                </button>
                {/* Recording buttons - only for running cameras */}
                {camera.status === 'running' && (
                  recordingStatus[camera.id]?.status === 'recording' ? (
                    <button
                      onClick={() => stopRecording(camera)}
                      className="p-2 rounded transition bg-red-500 hover:bg-red-600 text-white animate-pulse"
                      title="Stop Recording"
                    >
                      <Square className="h-4 w-4" />
                    </button>
                  ) : (
                    <button
                      onClick={() => startRecording(camera)}
                      className="p-2 rounded transition bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-red-400"
                      title="Start Recording"
                    >
                      <Circle className="h-4 w-4" />
                    </button>
                  )
                )}
              </div>
              <button
                onClick={() => onDelete(camera.id)}
                disabled={isBusy(camera)}
                className={`p-2 rounded bg-gray-700 hover:bg-gray-600 transition text-red-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                title="Delete"
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
function CameraList({ cameras, onDelete, onToggle, onEdit, onRestart, onError }) {
  const isDeleting = (camera) => camera.status === 'deleting'
  const isCreating = (camera) => camera.status === 'creating' || camera.status === 'pending'
  const isBusy = (camera) => isDeleting(camera) || isCreating(camera)
  
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
            <tr key={camera.id} className={`hover:bg-gray-700/30 ${isBusy(camera) ? 'opacity-60' : ''}`}>
              <td className="px-4 py-3 font-medium">{camera.name}</td>
              <td className="px-4 py-3">
                <span className="bg-gray-700 px-2 py-1 rounded text-sm uppercase">{camera.protocol}</span>
              </td>
              <td className="px-4 py-3 text-gray-400">{camera.node_name}</td>
              <td className="px-4 py-3">
                <div className="flex flex-col">
                  <span className={`inline-flex items-center space-x-1 ${
                    camera.status === 'running' ? 'text-green-400' : 
                    isCreating(camera) ? 'text-blue-400' :
                    camera.status === 'deleting' ? 'text-yellow-400' : 
                    camera.status === 'stopped' ? 'text-gray-400' : 'text-red-400'
                  }`}>
                    {camera.status === 'running' ? <CheckCircle className="h-4 w-4" /> : 
                     isBusy(camera) ? <Loader2 className="h-4 w-4 animate-spin" /> : 
                     camera.status === 'stopped' ? <Settings className="h-4 w-4" /> :
                     <AlertCircle className="h-4 w-4" />}
                    <span>{isCreating(camera) ? 'adding...' : camera.status}</span>
                  </span>
                  {camera.status === 'error' && camera.metadata?.error && (
                    <span className="text-xs text-red-300/70 truncate max-w-[200px]" title={camera.metadata.error}>
                      {camera.metadata.error}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => onToggle(camera)}
                    disabled={isBusy(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                    title={camera.status === 'running' ? 'Stop' : 'Start'}
                  >
                    {camera.status === 'running' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </button>
                  <button
                    onClick={() => onRestart(camera)}
                    disabled={isBusy(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition text-orange-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                    title="Restart"
                  >
                    <RefreshCw className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => onEdit(camera)}
                    disabled={isBusy(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition text-blue-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                    title="Edit"
                  >
                    <Edit className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => onDelete(camera.id)}
                    disabled={isBusy(camera)}
                    className={`p-1.5 rounded hover:bg-gray-600 transition text-red-400 ${isBusy(camera) ? 'opacity-50 cursor-not-allowed' : ''}`}
                    title="Delete"
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
  const isNetworkCamera = camera.protocol !== 'usb'
  const [form, setForm] = useState({
    name: camera.name,
    location: camera.location || '',
    resolution: camera.resolution || '640x480',
    framerate: camera.framerate || 15,
    source_url: camera.source_url || '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const payload = { ...form }
      // Only include source_url for network cameras
      if (!isNetworkCamera) {
        delete payload.source_url
      }
      
      const res = await fetch(`${API_URL}/cameras/${camera.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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

          {isNetworkCamera && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Stream URL</label>
              <input
                type="text"
                value={form.source_url}
                onChange={e => setForm({ ...form, source_url: e.target.value })}
                placeholder="rtsp://user:pass@192.168.1.1:554/stream"
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono text-sm"
              />
              <p className="text-xs text-gray-500 mt-1">Include credentials: rtsp://user:pass@ip:port/path</p>
            </div>
          )}

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

          <div className="text-sm text-gray-400 bg-gray-700/30 rounded p-2">
            <p><strong>Type:</strong> {camera.protocol.toUpperCase()}</p>
            <p><strong>Node:</strong> {camera.node_name || 'LAN'}</p>
            {!isNetworkCamera && <p><strong>Device:</strong> {camera.device_path}</p>}
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
function ScanCamerasModal({ nodes, onClose, onAdded }) {
  const [scanning, setScanning] = useState(false)
  const [cameras, setCameras] = useState([])
  const [networkCameras, setNetworkCameras] = useState([])
  const [scannedNodes, setScannedNodes] = useState([])
  const [errors, setErrors] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [adding, setAdding] = useState(false)

  const scanCameras = async () => {
    setScanning(true)
    setCameras([])
    setNetworkCameras([])
    setErrors([])
    setSelected(new Set())
    
    try {
      // Always scan network + USB
      const res = await fetch(`${API_URL}/nodes/scan/cameras?network=true`)
      if (!res.ok) throw new Error('Scan failed')
      const data = await res.json()
      setCameras(data.cameras || [])
      setNetworkCameras(data.network_cameras || [])
      setScannedNodes(data.scanned_nodes || [])
      setErrors(data.errors || [])
    } catch (err) {
      setErrors([err.message])
    } finally {
      setScanning(false)
    }
  }

  const toggleSelect = (key) => {
    const newSelected = new Set(selected)
    if (newSelected.has(key)) {
      newSelected.delete(key)
    } else {
      newSelected.add(key)
    }
    setSelected(newSelected)
  }

  const selectAll = () => {
    const allKeys = [
      ...cameras.map(c => `usb:${c.node_name}:${c.device_path}`),
      ...networkCameras.map(c => `net:${c.ip}:${c.port}`)
    ]
    setSelected(new Set(allKeys))
  }

  const addSelected = async () => {
    if (selected.size === 0) return
    setAdding(true)
    
    const toAdd = []
    for (const key of selected) {
      if (key.startsWith('usb:')) {
        const [, nodeName, devicePath] = key.split(':')
        const cam = cameras.find(c => c.node_name === nodeName && c.device_path === devicePath)
        if (cam) {
          toAdd.push({
            name: cam.device_name.replace(/[^a-zA-Z0-9\s]/g, '').trim() || `USB Camera ${nodeName}`,
            protocol: 'usb',
            node_name: cam.node_name,
            device_path: cam.device_path,
          })
        }
      } else if (key.startsWith('net:')) {
        const [, ip, port] = key.split(':')
        const cam = networkCameras.find(c => c.ip === ip && c.port === parseInt(port))
        if (cam) {
          toAdd.push({
            name: cam.name,
            protocol: cam.protocol,
            source_url: cam.url,
            node_name: cam.node_name || 'LAN',
          })
        }
      }
    }
    
    let successCount = 0
    const newErrors = []
    
    for (const camera of toAdd) {
      try {
        const res = await fetch(`${API_URL}/cameras/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(camera),
        })
        if (res.ok) {
          successCount++
        } else {
          const data = await res.json()
          newErrors.push(`${camera.name}: ${data.detail || 'Failed'}`)
        }
      } catch (err) {
        newErrors.push(`${camera.name}: ${err.message}`)
      }
    }
    
    setAdding(false)
    
    if (successCount > 0) {
      onAdded(successCount)
    }
    if (newErrors.length > 0) {
      setErrors(newErrors)
    }
  }

  useEffect(() => {
    scanCameras()
  }, [])

  const allCameras = [
    ...cameras.map(c => ({ ...c, key: `usb:${c.node_name}:${c.device_path}`, type: 'USB' })),
    ...networkCameras.map(c => ({ ...c, key: `net:${c.ip}:${c.port}`, type: c.protocol.toUpperCase(), device_name: c.name, node_name: c.node_name || 'LAN' }))
  ]
  const totalCameras = allCameras.length

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold">Scan for Cameras</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
        </div>
        
        <div className="p-6">
          {errors.length > 0 && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm mb-4 max-h-24 overflow-y-auto">
              {errors.map((e, i) => <p key={i}>{e}</p>)}
            </div>
          )}

          {scanning ? (
            <div className="text-center py-8">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500 mb-4" />
              <p className="text-gray-400">Scanning for cameras...</p>
              <p className="text-sm text-gray-500">This may take a moment</p>
            </div>
          ) : totalCameras === 0 ? (
            <div className="text-center py-8">
              <Camera className="h-12 w-12 mx-auto text-gray-600 mb-4" />
              <p className="text-gray-400 mb-2">No cameras found</p>
              <p className="text-sm text-gray-500 mb-4">Scanned: {scannedNodes.join(', ') || 'none'}</p>
              
              <button
                onClick={scanCameras}
                className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition"
              >
                Scan Again
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm text-gray-400">
                  Found {totalCameras} camera(s) • {selected.size} selected
                </p>
                <button
                  onClick={selectAll}
                  className="text-sm text-blue-400 hover:text-blue-300"
                >
                  Select All
                </button>
              </div>
              
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {allCameras.map((cam) => (
                  <label
                    key={cam.key}
                    className={`flex items-center space-x-3 bg-gray-700/50 rounded-lg p-3 cursor-pointer hover:bg-gray-700 transition ${
                      selected.has(cam.key) ? 'ring-2 ring-blue-500' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(cam.key)}
                      onChange={() => toggleSelect(cam.key)}
                      className="rounded bg-gray-600 border-gray-500 text-blue-500"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="font-medium truncate">{cam.device_name || cam.name}</p>
                      <p className="text-sm text-gray-400 truncate">
                        {cam.node_name} • {cam.device_path || cam.url}
                      </p>
                    </div>
                    <span className={`text-xs px-2 py-1 rounded ${
                      cam.type === 'USB' ? 'bg-green-500/20 text-green-400' :
                      cam.type === 'RTSP' ? 'bg-purple-500/20 text-purple-400' :
                      'bg-orange-500/20 text-orange-400'
                    }`}>
                      {cam.type}
                    </span>
                  </label>
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

        <div className="px-6 py-4 border-t border-gray-700 flex space-x-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-gray-400 hover:text-white transition bg-gray-700 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={addSelected}
            disabled={selected.size === 0 || adding}
            className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed px-4 py-2 rounded-lg transition flex items-center justify-center space-x-2"
          >
            {adding ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Plus className="h-4 w-4" />
                <span>Add {selected.size > 0 ? `(${selected.size})` : ''}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// Settings Modal
function SettingsModal({ onClose, onClearAll }) {
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch(`${API_URL}/settings/`)
        if (!res.ok) throw new Error('Failed to fetch settings')
        const data = await res.json()
        setSettings(data)
        setForm({
          default_resolution: data.default_resolution,
          default_framerate: data.default_framerate,
          cleanup_interval: data.cleanup_interval,
          creating_timeout_minutes: data.creating_timeout_minutes,
          chatbot_tools: data.chatbot?.enabled_tools || [],
          anthropic_api_key: '',
        })
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchSettings()
  }, [])

  const saveSettings = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/settings/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) throw new Error('Failed to save settings')
      setMessage(form.anthropic_api_key ? 'Settings saved! Click "Restart All" to apply API key.' : 'Settings saved!')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const restartAll = async () => {
    if (!confirm('Restart all Falcon-Eye deployments? This will briefly interrupt camera streams.')) return
    setRestarting(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/settings/restart-all`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to restart')
      const data = await res.json()
      setMessage(`${data.message}: ${data.restarted.join(', ')}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setRestarting(false)
    }
  }

  const clearAllCameras = async () => {
    if (!confirm('DELETE ALL CAMERAS? This will remove all cameras from the database and Kubernetes. This cannot be undone!')) return
    if (!confirm('Are you REALLY sure? Type "yes" mentally and click OK.')) return
    setClearing(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/settings/cameras/all`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to clear cameras')
      const data = await res.json()
      setMessage(data.message)
      setTimeout(() => onClearAll(), 1500)
    } catch (err) {
      setError(err.message)
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold flex items-center space-x-2">
            <Settings className="h-5 w-5" />
            <span>Settings</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
        </div>
        
        <div className="p-6 space-y-6">
          {loading ? (
            <div className="text-center py-8">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
            </div>
          ) : (
            <>
              {error && (
                <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm">
                  {error}
                </div>
              )}
              {message && (
                <div className="bg-green-500/10 border border-green-500 text-green-500 px-3 py-2 rounded text-sm">
                  {message}
                </div>
              )}

              {/* Camera Defaults */}
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-3">Camera Defaults</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Resolution</label>
                    <select
                      value={form.default_resolution}
                      onChange={e => setForm({ ...form, default_resolution: e.target.value })}
                      className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    >
                      <option value="320x240">320x240</option>
                      <option value="640x480">640x480</option>
                      <option value="800x600">800x600</option>
                      <option value="1280x720">1280x720 (HD)</option>
                      <option value="1920x1080">1920x1080 (FHD)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Framerate</label>
                    <input
                      type="number"
                      value={form.default_framerate}
                      onChange={e => setForm({ ...form, default_framerate: parseInt(e.target.value) })}
                      min="1"
                      max="60"
                      className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    />
                  </div>
                </div>
              </div>

              {/* System Settings */}
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-3">System Settings</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Cleanup Interval (cron)</label>
                    <input
                      type="text"
                      value={form.cleanup_interval}
                      onChange={e => setForm({ ...form, cleanup_interval: e.target.value })}
                      placeholder="*/10 * * * *"
                      className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono"
                    />
                    <p className="text-xs text-gray-500 mt-1">Cron expression for orphan pod cleanup (default: every 10 min)</p>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Creating Timeout (minutes)</label>
                    <input
                      type="number"
                      value={form.creating_timeout_minutes}
                      onChange={e => setForm({ ...form, creating_timeout_minutes: parseInt(e.target.value) })}
                      min="1"
                      max="30"
                      className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    />
                    <p className="text-xs text-gray-500 mt-1">Auto-stop cameras stuck in "creating" state</p>
                  </div>
                </div>
              </div>

              {/* Chatbot Settings */}
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center space-x-2">
                  <MessageCircle className="h-4 w-4" />
                  <span>Chatbot Settings</span>
                  {settings?.chatbot?.api_key_configured ? (
                    <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">Configured</span>
                  ) : (
                    <span className="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded">Not configured</span>
                  )}
                </h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Anthropic API Key</label>
                    <input
                      type="password"
                      value={form.anthropic_api_key || ''}
                      onChange={e => setForm({ ...form, anthropic_api_key: e.target.value })}
                      placeholder={settings?.chatbot?.api_key_configured ? "••••••••••••••••" : "sk-ant-..."}
                      className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono"
                    />
                    <p className="text-xs text-gray-500 mt-1">Required for AI assistant (stored securely)</p>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Enabled Tools</label>
                    <div className="space-y-1 max-h-32 overflow-y-auto bg-gray-700/50 rounded p-2">
                      {settings?.chatbot?.available_tools?.map(tool => (
                        <label key={tool} className="flex items-center space-x-2 text-sm cursor-pointer hover:bg-gray-600/50 rounded px-1">
                          <input
                            type="checkbox"
                            checked={(form.chatbot_tools || settings?.chatbot?.enabled_tools || []).includes(tool)}
                            onChange={(e) => {
                              const current = form.chatbot_tools || settings?.chatbot?.enabled_tools || []
                              if (e.target.checked) {
                                setForm({ ...form, chatbot_tools: [...current, tool] })
                              } else {
                                setForm({ ...form, chatbot_tools: current.filter(t => t !== tool) })
                              }
                            }}
                            className="rounded bg-gray-600 border-gray-500 text-blue-500"
                          />
                          <span className="text-gray-300">{tool.replace(/_/g, ' ')}</span>
                        </label>
                      ))}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">Tools the chatbot can use (read-only access)</p>
                  </div>
                </div>
              </div>

              {/* Info */}
              {settings && (
                <div className="bg-gray-700/30 rounded p-3 text-sm">
                  <p className="text-gray-400"><strong>Namespace:</strong> {settings.k8s_namespace}</p>
                  <p className="text-gray-400"><strong>Node IPs:</strong> {Object.keys(settings.node_ips || {}).length} configured</p>
                </div>
              )}

              {/* Actions */}
              <div className="flex space-x-3">
                <button
                  onClick={saveSettings}
                  disabled={saving}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-4 py-2 rounded-lg transition flex items-center justify-center space-x-2"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  <span>{saving ? 'Saving...' : 'Save'}</span>
                </button>
                <button
                  onClick={restartAll}
                  disabled={restarting}
                  className="flex-1 bg-orange-600 hover:bg-orange-700 disabled:bg-orange-600/50 px-4 py-2 rounded-lg transition flex items-center justify-center space-x-2"
                >
                  {restarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                  <span>{restarting ? 'Restarting...' : 'Restart All'}</span>
                </button>
              </div>

              {/* Danger Zone */}
              <div className="border-t border-gray-700 pt-4">
                <h3 className="text-sm font-medium text-red-400 mb-3">Danger Zone</h3>
                <button
                  onClick={clearAllCameras}
                  disabled={clearing}
                  className="w-full bg-red-600/20 hover:bg-red-600/30 border border-red-600 text-red-400 px-4 py-2 rounded-lg transition flex items-center justify-center space-x-2"
                >
                  {clearing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  <span>{clearing ? 'Clearing...' : 'Clear All Cameras'}</span>
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// Chat Widget Component
function ChatWidget({ isOpen, onToggle, isDocked, onDockToggle, panelWidth, onWidthChange }) {
  const [sessions, setSessions] = useState([])
  const [currentSession, setCurrentSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [chatStatus, setChatStatus] = useState(null)
  const [isResizing, setIsResizing] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [editingName, setEditingName] = useState(null)
  const [newName, setNewName] = useState('')
  const messagesEndRef = React.useRef(null)

  // Fetch sessions on mount
  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_URL}/chat/sessions`)
      if (res.ok) {
        const data = await res.json()
        setSessions(data.sessions || [])
      }
    } catch (err) {
      console.error('Failed to fetch sessions:', err)
    }
  }

  useEffect(() => {
    fetchSessions()
  }, [])

  // Handle resize drag
  useEffect(() => {
    if (!isResizing) return
    const handleMouseMove = (e) => {
      const newWidth = window.innerWidth - e.clientX
      onWidthChange?.(Math.min(800, Math.max(350, newWidth)))
    }
    const handleMouseUp = () => setIsResizing(false)
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  // Check chat health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(`${API_URL}/chat/health`)
        if (res.ok) setChatStatus(await res.json())
      } catch (err) {
        setChatStatus({ status: 'error', configured: false })
      }
    }
    checkHealth()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const createNewSession = async () => {
    try {
      const res = await fetch(`${API_URL}/chat/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      if (res.ok) {
        const session = await res.json()
        setSessions(prev => [session, ...prev])
        setCurrentSession(session)
        setMessages([])
        setShowSessions(false)
      }
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }

  const loadSession = async (session) => {
    try {
      const res = await fetch(`${API_URL}/chat/sessions/${session.id}`)
      if (res.ok) {
        const data = await res.json()
        setCurrentSession(data)
        setMessages(data.messages || [])
        setShowSessions(false)
      }
    } catch (err) {
      console.error('Failed to load session:', err)
    }
  }

  const deleteSession = async (sessionId) => {
    if (!confirm('Delete this chat?')) return
    try {
      await fetch(`${API_URL}/chat/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (currentSession?.id === sessionId) {
        setCurrentSession(null)
        setMessages([])
      }
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  const renameSession = async (sessionId) => {
    if (!newName.trim()) return
    try {
      const res = await fetch(`${API_URL}/chat/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() })
      })
      if (res.ok) {
        const updated = await res.json()
        setSessions(prev => prev.map(s => s.id === sessionId ? updated : s))
        if (currentSession?.id === sessionId) setCurrentSession(updated)
      }
    } catch (err) {
      console.error('Failed to rename session:', err)
    }
    setEditingName(null)
    setNewName('')
  }

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return
    
    // Create session if none
    let session = currentSession
    if (!session) {
      try {
        const res = await fetch(`${API_URL}/chat/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        if (res.ok) {
          session = await res.json()
          setSessions(prev => [session, ...prev])
          setCurrentSession(session)
        }
      } catch (err) {
        console.error('Failed to create session:', err)
        return
      }
    }

    const userMessage = { role: 'user', content: input.trim() }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const res = await fetch(`${API_URL}/chat/sessions/${session.id}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: userMessage.content, stream: true }),
      })
      if (!res.ok) throw new Error('Chat request failed')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      setMessages(prev => [...prev, { role: 'assistant', content: '', thinking: false }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')
        let currentEvent = 'message'
        for (const line of lines) {
          if (line.startsWith('event: ')) { currentEvent = line.slice(7).trim(); continue }
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (currentEvent === 'thinking') {
                setMessages(prev => { const u = [...prev]; u[u.length-1] = { role: 'assistant', content: assistantContent, thinking: true }; return u })
              } else if (currentEvent === 'message' && data.content) {
                const text = typeof data.content === 'string' ? data.content : ''
                if (text) {
                  assistantContent += text
                  setMessages(prev => { const u = [...prev]; u[u.length-1] = { role: 'assistant', content: assistantContent, thinking: false }; return u })
                }
              }
            } catch (e) {}
          }
        }
      }
      // Refresh sessions to get updated name
      fetchSessions()
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.message}` }])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  if (!isOpen) {
    return (
      <button onClick={onToggle} className="fixed bottom-6 right-6 w-14 h-14 bg-blue-600 hover:bg-blue-700 rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-110 z-50" title="Open Chat">
        <MessageCircle className="h-6 w-6 text-white" />
      </button>
    )
  }

  const panelClasses = isDocked
    ? "fixed top-0 right-0 h-full bg-gray-800 border-l border-gray-700 shadow-xl z-40 flex"
    : "fixed bottom-6 right-6 w-[450px] h-[550px] bg-gray-800 rounded-lg border border-gray-700 shadow-xl z-50 flex"

  return (
    <div className={panelClasses} style={isDocked ? { width: `${panelWidth}px` } : undefined}>
      {isDocked && (
        <div className="absolute left-0 top-0 bottom-0 w-1 cursor-ew-resize hover:bg-blue-500 transition-colors" onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }} />
      )}
      
      {/* Sessions sidebar */}
      {showSessions && (
        <div className="w-48 border-r border-gray-700 flex flex-col bg-gray-850">
          <div className="p-2 border-b border-gray-700">
            <button onClick={createNewSession} className="w-full flex items-center justify-center space-x-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm">
              <Plus className="h-4 w-4" /><span>New Chat</span>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sessions.map(s => (
              <div key={s.id} className={`group px-2 py-2 hover:bg-gray-700 cursor-pointer border-b border-gray-700/50 ${currentSession?.id === s.id ? 'bg-gray-700' : ''}`}>
                {editingName === s.id ? (
                  <input value={newName} onChange={e => setNewName(e.target.value)} onBlur={() => renameSession(s.id)} onKeyDown={e => e.key === 'Enter' && renameSession(s.id)} className="w-full bg-gray-600 px-2 py-1 text-xs rounded" autoFocus />
                ) : (
                  <div onClick={() => loadSession(s)} className="flex items-center justify-between">
                    <span className="text-sm truncate flex-1">{s.name || 'New Chat'}</span>
                    <div className="hidden group-hover:flex items-center space-x-1">
                      <button onClick={(e) => { e.stopPropagation(); setEditingName(s.id); setNewName(s.name || '') }} className="p-1 hover:bg-gray-600 rounded"><Edit className="h-3 w-3" /></button>
                      <button onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }} className="p-1 hover:bg-red-600 rounded"><Trash2 className="h-3 w-3" /></button>
                    </div>
                  </div>
                )}
                <div className="text-xs text-gray-500">{s.message_count || 0} messages</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 bg-gray-800/90">
          <div className="flex items-center space-x-2 min-w-0">
            <button onClick={() => setShowSessions(!showSessions)} className="p-1.5 hover:bg-gray-700 rounded" title="Chat History">
              <List className="h-4 w-4" />
            </button>
            <MessageCircle className="h-4 w-4 text-blue-500 flex-shrink-0" />
            <span className="font-medium text-sm truncate">{currentSession?.name || 'Falcon-Eye Assistant'}</span>
          </div>
          <div className="flex items-center space-x-1">
            <button onClick={createNewSession} className="p-1.5 hover:bg-gray-700 rounded" title="New Chat"><Plus className="h-4 w-4" /></button>
            <button onClick={onDockToggle} className="p-1.5 hover:bg-gray-700 rounded" title={isDocked ? "Undock" : "Dock"}>
              {isDocked ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            </button>
            <button onClick={onToggle} className="p-1.5 hover:bg-gray-700 rounded" title="Close"><X className="h-4 w-4" /></button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-gray-500 py-8">
              <MessageCircle className="h-10 w-10 mx-auto mb-3 opacity-50" />
              <p className="text-sm">Hi! I'm your Falcon-Eye Assistant.</p>
              <p className="text-xs mt-1">Ask me about your cameras!</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-lg px-3 py-2 ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-100'}`}>
                {msg.thinking ? (
                  <div className="flex items-center space-x-2 text-sm text-gray-400"><Loader2 className="h-4 w-4 animate-spin" /><span>Getting info...</span></div>
                ) : msg.content ? (
                  <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
                ) : msg.role === 'assistant' && isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-3 border-t border-gray-700">
          <div className="flex items-center space-x-2">
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)} onKeyPress={handleKeyPress} placeholder="Type a message..." disabled={isLoading || !chatStatus?.configured} className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50" />
            <button onClick={sendMessage} disabled={!input.trim() || isLoading || !chatStatus?.configured} className="p-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg transition">
              <Send className="h-4 w-4" />
            </button>
          </div>
          {chatStatus && !chatStatus.configured && <p className="text-xs text-yellow-500 mt-2">Set ANTHROPIC_API_KEY to enable chat</p>}
        </div>
      </div>
    </div>
  )
}

// Recordings Page Component
function RecordingsPage({ cameras }) {
  const [recordings, setRecordings] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedRecording, setSelectedRecording] = useState(null)
  const [expandedCameras, setExpandedCameras] = useState({})
  const [filter, setFilter] = useState('all') // all, recording, completed

  // Fetch all recordings
  useEffect(() => {
    const fetchRecordings = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${API_URL}/recordings/`)
        if (res.ok) {
          const data = await res.json()
          setRecordings(data.recordings || [])
        }
      } catch (err) {
        console.error('Failed to fetch recordings:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchRecordings()
    const interval = setInterval(fetchRecordings, 10000) // Refresh every 10s
    return () => clearInterval(interval)
  }, [])

  // Group recordings by camera (or by camera_name for orphaned recordings)
  const groupedRecordings = recordings.reduce((acc, rec) => {
    // Use camera_id if available, otherwise use camera_name as key
    const key = rec.camera_id || `deleted_${rec.camera_name || rec.id}`
    if (!acc[key]) {
      acc[key] = []
    }
    acc[key].push(rec)
    return acc
  }, {})

  // Get camera name by ID or from recording
  const getCameraInfo = (camId, recs) => {
    // Check if any recording in group is from a deleted camera
    const firstRec = recs[0]
    const isDeleted = firstRec?.camera_deleted || !firstRec?.camera_id
    
    if (isDeleted) {
      return {
        name: firstRec?.camera_name || 'Unknown Camera',
        deleted: true
      }
    }
    
    const cam = cameras.find(c => c.id === camId)
    return {
      name: cam?.name || firstRec?.camera_name || `Camera ${camId?.slice(0, 8) || 'unknown'}`,
      deleted: false
    }
  }

  // Toggle camera expansion
  const toggleCamera = (camId) => {
    setExpandedCameras(prev => ({ ...prev, [camId]: !prev[camId] }))
  }

  // Delete recording
  const deleteRecording = async (recordingId) => {
    if (!confirm('Delete this recording?')) return
    try {
      await fetch(`${API_URL}/recordings/${recordingId}`, { method: 'DELETE' })
      setRecordings(prev => prev.filter(r => r.id !== recordingId))
    } catch (err) {
      console.error('Failed to delete recording:', err)
    }
  }

  // Format duration
  const formatDuration = (seconds) => {
    if (!seconds) return '--:--'
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Format file size
  const formatSize = (bytes) => {
    if (!bytes) return '--'
    const mb = bytes / (1024 * 1024)
    return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`
  }

  // Format date
  const formatDate = (isoString) => {
    if (!isoString) return '--'
    const date = new Date(isoString)
    return date.toLocaleString()
  }

  // Filter recordings
  const filteredRecordings = filter === 'all' 
    ? recordings 
    : recordings.filter(r => r.status === filter)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Recordings</h2>
          <p className="text-sm text-gray-400">
            {recordings.length} recording{recordings.length !== 1 ? 's' : ''} • 
            {recordings.filter(r => r.status === 'recording').length} active
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm"
          >
            <option value="all">All</option>
            <option value="recording">Recording</option>
            <option value="completed">Completed</option>
            <option value="stopped">Stopped</option>
          </select>
        </div>
      </div>

      {recordings.length === 0 ? (
        <div className="text-center py-16">
          <Film className="h-16 w-16 mx-auto text-gray-600 mb-4" />
          <h2 className="text-xl font-semibold text-gray-400 mb-2">No recordings yet</h2>
          <p className="text-gray-500">Start recording from a camera to see recordings here</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(groupedRecordings).map(([camId, recs]) => {
            const cameraInfo = getCameraInfo(camId, recs)
            return (
            <div key={camId} className={`bg-gray-800 rounded-lg border overflow-hidden ${cameraInfo.deleted ? 'border-yellow-700/50' : 'border-gray-700'}`}>
              {/* Camera Header */}
              <button
                onClick={() => toggleCamera(camId)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-700/50 transition"
              >
                <div className="flex items-center space-x-3">
                  {expandedCameras[camId] ? 
                    <ChevronDown className="h-5 w-5 text-gray-400" /> : 
                    <ChevronRight className="h-5 w-5 text-gray-400" />
                  }
                  <Camera className={`h-5 w-5 ${cameraInfo.deleted ? 'text-yellow-500' : 'text-blue-500'}`} />
                  <span className="font-medium">{cameraInfo.name}</span>
                  {cameraInfo.deleted && (
                    <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-400">Camera Deleted</span>
                  )}
                  <span className="text-sm text-gray-400">({recs.length} recording{recs.length !== 1 ? 's' : ''})</span>
                </div>
                {recs.some(r => r.status === 'recording') && (
                  <span className="flex items-center space-x-1 text-red-500 text-sm">
                    <Circle className="h-3 w-3 fill-current animate-pulse" />
                    <span>Recording</span>
                  </span>
                )}
              </button>

              {/* Recordings List */}
              {expandedCameras[camId] && (
                <div className="border-t border-gray-700">
                  {recs
                    .filter(r => filter === 'all' || r.status === filter)
                    .sort((a, b) => new Date(b.start_time) - new Date(a.start_time))
                    .map((rec) => (
                    <div
                      key={rec.id}
                      className="px-4 py-3 flex items-center justify-between hover:bg-gray-700/30 border-b border-gray-700/50 last:border-0"
                    >
                      <div className="flex items-center space-x-4">
                        <div className={`p-2 rounded-lg ${
                          rec.status === 'recording' ? 'bg-red-500/20' :
                          rec.status === 'completed' ? 'bg-green-500/20' : 'bg-gray-500/20'
                        }`}>
                          {rec.status === 'recording' ? (
                            <Circle className="h-4 w-4 text-red-500 fill-current animate-pulse" />
                          ) : (
                            <Film className="h-4 w-4 text-gray-400" />
                          )}
                        </div>
                        <div>
                          <p className="text-sm font-medium">{rec.file_name || 'Recording'}</p>
                          <div className="flex items-center space-x-3 text-xs text-gray-400">
                            <span className="flex items-center space-x-1">
                              <Clock className="h-3 w-3" />
                              <span>{formatDate(rec.start_time)}</span>
                            </span>
                            {rec.duration_seconds && (
                              <span>{formatDuration(rec.duration_seconds)}</span>
                            )}
                            {rec.file_size_bytes && (
                              <span>{formatSize(rec.file_size_bytes)}</span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className={`px-2 py-1 text-xs rounded ${
                          rec.status === 'recording' ? 'bg-red-500/20 text-red-400' :
                          rec.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {rec.status}
                        </span>
                        {rec.status !== 'recording' && (
                          <>
                            <button
                              onClick={() => setSelectedRecording(rec)}
                              className="p-2 hover:bg-gray-600 rounded-lg transition text-blue-400"
                              title="Play"
                            >
                              <Play className="h-4 w-4" />
                            </button>
                            <a
                              href={`${API_URL}/recordings/${rec.id}/download`}
                              className="p-2 hover:bg-gray-600 rounded-lg transition text-green-400"
                              title="Download"
                            >
                              <Download className="h-4 w-4" />
                            </a>
                            <button
                              onClick={() => deleteRecording(rec.id)}
                              className="p-2 hover:bg-gray-600 rounded-lg transition text-red-400"
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )})}
        </div>
      )}

      {/* Video Player Modal */}
      {selectedRecording && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg max-w-4xl w-full mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
              <div>
                <h3 className="font-medium">{selectedRecording.file_name}</h3>
                <p className="text-sm text-gray-400">{formatDate(selectedRecording.start_time)}</p>
              </div>
              <button
                onClick={() => setSelectedRecording(null)}
                className="p-2 hover:bg-gray-700 rounded-lg transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="aspect-video bg-black">
              <video
                src={`${API_URL}/recordings/${selectedRecording.id}/download`}
                controls
                autoPlay
                className="w-full h-full"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
