import React, { useState, useEffect } from 'react'
import { Clock, Plus, Trash2, Play, Edit, RefreshCw, Loader2, AlertCircle, CheckCircle, X } from 'lucide-react'
import CronExpressionBuilder, { describeCron } from './CronExpressionBuilder'

const API_URL = import.meta.env.VITE_API_URL || window.API_URL || '/api'

export default function CronJobsPage() {
  const [cronJobs, setCronJobs] = useState([])
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingJob, setEditingJob] = useState(null)
  const [error, setError] = useState(null)

  const fetchCronJobs = async () => {
    try {
      const res = await fetch(`${API_URL}/cron/`)
      if (!res.ok) throw new Error('Failed to fetch cron jobs')
      const data = await res.json()
      setCronJobs(data.cron_jobs || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchAgents = async () => {
    try {
      const res = await fetch(`${API_URL}/agents/`)
      if (res.ok) {
        const data = await res.json()
        setAgents(data.agents || [])
      }
    } catch (err) {}
  }

  useEffect(() => {
    Promise.all([fetchCronJobs(), fetchAgents()])
    const interval = setInterval(fetchCronJobs, 10000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 8000)
      return () => clearTimeout(timer)
    }
  }, [error])

  const deleteCronJob = async (id) => {
    if (!confirm('Delete this cron job?')) return
    try {
      await fetch(`${API_URL}/cron/${id}`, { method: 'DELETE' })
      fetchCronJobs()
    } catch (err) {
      setError(err.message)
    }
  }

  const runNow = async (id) => {
    try {
      const res = await fetch(`${API_URL}/cron/${id}/run`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to trigger cron job')
      const data = await res.json()
      setError(null)
      alert(`Job triggered: ${data.job_name}`)
    } catch (err) {
      setError(err.message)
    }
  }

  const toggleEnabled = async (job) => {
    try {
      await fetch(`${API_URL}/cron/${job.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !job.enabled }),
      })
      fetchCronJobs()
    } catch (err) {
      setError(err.message)
    }
  }

  const getAgentName = (agentId) => {
    const agent = agents.find(a => a.id === agentId)
    return agent?.name || agentId?.slice(0, 8)
  }

  const statusBadge = (status) => {
    if (!status) return null
    const styles = {
      success: 'bg-green-500/20 text-green-400',
      failed: 'bg-red-500/20 text-red-400',
      error: 'bg-red-500/20 text-red-400',
      timeout: 'bg-yellow-500/20 text-yellow-400',
    }
    return <span className={`px-2 py-0.5 rounded text-xs ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>{status}</span>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Cron Jobs</h2>
          <p className="text-sm text-gray-400">{cronJobs.length} scheduled job{cronJobs.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center space-x-3">
          <button onClick={fetchCronJobs} className="p-2 hover:bg-gray-700 rounded-lg transition" title="Refresh">
            <RefreshCw className="h-5 w-5" />
          </button>
          <button onClick={() => { setEditingJob(null); setShowModal(true) }} className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition">
            <Plus className="h-5 w-5" />
            <span>New Cron Job</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/20 border border-red-500 text-red-400 px-4 py-3 rounded-lg flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertCircle className="h-5 w-5 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-red-300 hover:text-white ml-4">×</button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      ) : cronJobs.length === 0 ? (
        <div className="text-center py-16">
          <Clock className="h-16 w-16 mx-auto text-gray-600 mb-4" />
          <h2 className="text-xl font-semibold text-gray-400 mb-2">No cron jobs</h2>
          <p className="text-gray-500 mb-4">Schedule automated prompts for your agents</p>
          <button onClick={() => { setEditingJob(null); setShowModal(true) }} className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg transition">
            Create Cron Job
          </button>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-700/50">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Name</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Agent</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Schedule</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Enabled</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Last Status</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Last Run</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {cronJobs.map(job => (
                <tr key={job.id} className="hover:bg-gray-700/30">
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium">{job.name}</p>
                      <p className="text-xs text-gray-500 truncate max-w-[200px]">{job.prompt}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-sm">{getAgentName(job.agent_id)}</td>
                  <td className="px-4 py-3">
                    <div>
                      <span className="text-sm text-gray-200">{describeCron(job.cron_expr)}</span>
                      <code className="block text-xs text-gray-500 font-mono mt-0.5">{job.cron_expr}</code>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={() => toggleEnabled(job)} className="relative">
                      <div className={`w-10 h-6 rounded-full transition-colors ${job.enabled ? 'bg-blue-600' : 'bg-gray-600'}`} />
                      <div className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-transform ${job.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                    </button>
                  </td>
                  <td className="px-4 py-3">{statusBadge(job.last_status)}</td>
                  <td className="px-4 py-3 text-sm text-gray-400">
                    {job.last_run ? new Date(job.last_run).toLocaleString() : '--'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center space-x-2">
                      <button onClick={() => runNow(job.id)} className="p-1.5 rounded hover:bg-gray-600 transition text-green-400" title="Run Now">
                        <Play className="h-4 w-4" />
                      </button>
                      <button onClick={() => { setEditingJob(job); setShowModal(true) }} className="p-1.5 rounded hover:bg-gray-600 transition text-blue-400" title="Edit">
                        <Edit className="h-4 w-4" />
                      </button>
                      <button onClick={() => deleteCronJob(job.id)} className="p-1.5 rounded hover:bg-gray-600 transition text-red-400" title="Delete">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <CronJobModal
          job={editingJob}
          agents={agents}
          onClose={() => { setShowModal(false); setEditingJob(null) }}
          onSave={() => { setShowModal(false); setEditingJob(null); fetchCronJobs() }}
        />
      )}
    </div>
  )
}


function CronJobModal({ job, agents, onClose, onSave }) {
  const isEdit = !!job
  const [form, setForm] = useState({
    name: job?.name || '',
    agent_id: job?.agent_id || (agents[0]?.id || ''),
    cron_expr: job?.cron_expr || '0 * * * *',
    timezone: job?.timezone || 'UTC',
    prompt: job?.prompt || '',
    timeout_seconds: job?.timeout_seconds || 120,
    enabled: job?.enabled ?? true,
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const url = isEdit ? `${API_URL}/cron/${job.id}` : `${API_URL}/cron/`
      const method = isEdit ? 'PATCH' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to save cron job')
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
      <div className="bg-gray-800 rounded-lg w-full max-w-lg mx-4 border border-gray-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold">{isEdit ? 'Edit Cron Job' : 'Create Cron Job'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm">{error}</div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
            <input type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" required />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Agent</label>
            <select value={form.agent_id} onChange={e => setForm({ ...form, agent_id: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" required>
              {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>

          <CronExpressionBuilder
            value={form.cron_expr}
            onChange={cron_expr => setForm(f => ({ ...f, cron_expr }))}
          />

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Prompt</label>
            <textarea value={form.prompt} onChange={e => setForm({ ...form, prompt: e.target.value })} rows={3} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 text-sm" required />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Timezone</label>
              <input type="text" value={form.timezone} onChange={e => setForm({ ...form, timezone: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Timeout (s)</label>
              <input type="number" value={form.timeout_seconds} onChange={e => setForm({ ...form, timeout_seconds: parseInt(e.target.value) })} min="10" max="3600" className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" />
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} className="rounded bg-gray-600 border-gray-500 text-blue-500" />
              <span className="text-sm text-gray-300">Enabled</span>
            </label>
          </div>

          <div className="flex items-center justify-end space-x-3 pt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-400 hover:text-white transition">Cancel</button>
            <button type="submit" disabled={submitting} className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-4 py-2 rounded-lg transition flex items-center space-x-2">
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{submitting ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Cron Job'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
