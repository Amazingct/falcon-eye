import { authFetch } from '../App'
import React, { useState, useEffect } from 'react'
import { Bot, Plus, Trash2, Play, Square, Edit, RefreshCw, Loader2, Save, X, AlertCircle, CheckCircle, Settings } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || window.API_URL || '/api'

export default function AgentsPage({ onSelectAgent }) {
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingAgent, setEditingAgent] = useState(null)
  const [error, setError] = useState(null)

  const fetchAgents = async () => {
    try {
      const res = await authFetch(`${API_URL}/agents/`)
      if (!res.ok) throw new Error('Failed to fetch agents')
      const data = await res.json()
      setAgents(data.agents || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAgents()
    const interval = setInterval(fetchAgents, 8000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 8000)
      return () => clearTimeout(timer)
    }
  }, [error])

  const deleteAgent = async (id) => {
    if (!confirm('Delete this agent and all its data?')) return
    try {
      await authFetch(`${API_URL}/agents/${id}`, { method: 'DELETE' })
      fetchAgents()
    } catch (err) {
      setError(err.message)
    }
  }

  const startAgent = async (id) => {
    try {
      await authFetch(`${API_URL}/agents/${id}/start`, { method: 'POST' })
      fetchAgents()
    } catch (err) {
      setError(err.message)
    }
  }

  const stopAgent = async (id) => {
    try {
      await authFetch(`${API_URL}/agents/${id}/stop`, { method: 'POST' })
      fetchAgents()
    } catch (err) {
      setError(err.message)
    }
  }

  const statusBadge = (status) => {
    const styles = {
      running: 'bg-green-500/20 text-green-400',
      stopped: 'bg-gray-500/20 text-gray-400',
      error: 'bg-red-500/20 text-red-400',
      creating: 'bg-blue-500/20 text-blue-400',
    }
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium flex items-center space-x-1 ${styles[status] || styles.stopped}`}>
        {status === 'creating' && <Loader2 className="h-3 w-3 animate-spin" />}
        <span>{status?.toUpperCase() || 'STOPPED'}</span>
      </span>
    )
  }

  // Sort: main first
  const sorted = [...agents].sort((a, b) => {
    if (a.slug === 'main') return -1
    if (b.slug === 'main') return 1
    return 0
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Agents</h2>
          <p className="text-sm text-gray-400">{agents.length} agent{agents.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center space-x-3">
          <button onClick={fetchAgents} className="p-2 hover:bg-gray-700 rounded-lg transition" title="Refresh">
            <RefreshCw className="h-5 w-5" />
          </button>
          <button onClick={() => setShowCreateModal(true)} className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition">
            <Plus className="h-5 w-5" />
            <span>New Agent</span>
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
      ) : agents.length === 0 ? (
        <div className="text-center py-16">
          <Bot className="h-16 w-16 mx-auto text-gray-600 mb-4" />
          <h2 className="text-xl font-semibold text-gray-400 mb-2">No agents yet</h2>
          <p className="text-gray-500 mb-4">Create your first AI agent to get started</p>
          <button onClick={() => setShowCreateModal(true)} className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg transition">
            Create Agent
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {sorted.map(agent => (
            <div key={agent.id} className="bg-gray-800 rounded-lg border border-gray-700 p-4 flex items-center justify-between hover:border-gray-600 transition-colors cursor-pointer group" onClick={() => onSelectAgent?.(agent.id)}>
              <div className="flex items-center space-x-4 min-w-0">
                <div className={`p-2 rounded-lg ${agent.status === 'running' ? 'bg-green-500/20' : 'bg-gray-700'}`}>
                  <Bot className={`h-5 w-5 ${agent.status === 'running' ? 'text-green-400' : 'text-gray-400'}`} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center space-x-2">
                    <h3 className="font-semibold truncate group-hover:text-blue-400 transition-colors">{agent.name}</h3>
                    {agent.slug === 'main' && (
                      <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded">Main</span>
                    )}
                    {statusBadge(agent.status)}
                  </div>
                  <div className="flex items-center space-x-3 text-sm text-gray-400 mt-1">
                    <span>{agent.provider}/{agent.model}</span>
                    {agent.channel_type && <span className="bg-gray-700 px-2 py-0.5 rounded text-xs">{agent.channel_type}</span>}
                    <span>{(agent.tools || []).length} tools</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center space-x-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
                {agent.status === 'running' ? (
                  <button onClick={() => stopAgent(agent.id)} className="p-2 rounded bg-red-500/20 hover:bg-red-500/30 text-red-400 transition" title="Stop" disabled={agent.slug === 'main'}>
                    <Square className="h-4 w-4" />
                  </button>
                ) : (
                  <button onClick={() => startAgent(agent.id)} className="p-2 rounded bg-green-500/20 hover:bg-green-500/30 text-green-400 transition" title="Start">
                    <Play className="h-4 w-4" />
                  </button>
                )}
                <button onClick={() => setEditingAgent(agent)} className="p-2 rounded bg-gray-700 hover:bg-gray-600 text-blue-400 transition" title="Edit">
                  <Edit className="h-4 w-4" />
                </button>
                {agent.slug !== 'main' && (
                  <button onClick={() => deleteAgent(agent.id)} className="p-2 rounded bg-gray-700 hover:bg-gray-600 text-red-400 transition" title="Delete">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <AgentModal
          onClose={() => setShowCreateModal(false)}
          onSave={() => { setShowCreateModal(false); fetchAgents() }}
        />
      )}
      {editingAgent && (
        <AgentModal
          agent={editingAgent}
          onClose={() => setEditingAgent(null)}
          onSave={() => { setEditingAgent(null); fetchAgents() }}
        />
      )}
    </div>
  )
}


function AgentModal({ agent, onClose, onSave }) {
  const isEdit = !!agent
  const [form, setForm] = useState({
    name: agent?.name || '',
    slug: agent?.slug || '',
    type: agent?.type || 'pod',
    provider: agent?.provider || 'anthropic',
    model: agent?.model || 'claude-sonnet-4-20250514',
    api_key_ref: agent?.api_key_ref || '',
    system_prompt: agent?.system_prompt || '',
    temperature: agent?.temperature ?? 0.7,
    max_tokens: agent?.max_tokens || 4096,
    channel_type: agent?.channel_type || '',
    bot_token: agent?.channel_config?.bot_token || '',
    tools: agent?.tools || [],
    cpu_limit: agent?.cpu_limit || '500m',
    memory_limit: agent?.memory_limit || '512Mi',
  })
  const [allTools, setAllTools] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    authFetch(`${API_URL}/tools/`).then(r => r.json()).then(d => setAllTools(d.tools || {})).catch(() => {})
  }, [])

  const autoSlug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    const payload = {
      name: form.name,
      provider: form.provider,
      model: form.model,
      api_key_ref: form.api_key_ref || null,
      system_prompt: form.system_prompt || null,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
      channel_type: form.channel_type || null,
      channel_config: form.channel_type === 'telegram' ? { bot_token: form.bot_token } : {},
      tools: form.tools,
      cpu_limit: form.cpu_limit,
      memory_limit: form.memory_limit,
    }

    try {
      if (isEdit) {
        const res = await authFetch(`${API_URL}/agents/${agent.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          const data = await res.json()
          throw new Error(data.detail || 'Failed to update agent')
        }
      } else {
        payload.slug = form.slug || autoSlug(form.name)
        const res = await authFetch(`${API_URL}/agents/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          const data = await res.json()
          throw new Error(data.detail || 'Failed to create agent')
        }
      }
      onSave()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const toggleTool = (toolId) => {
    setForm(f => ({
      ...f,
      tools: f.tools.includes(toolId)
        ? f.tools.filter(t => t !== toolId)
        : [...f.tools, toolId],
    }))
  }

  const allToolIds = Object.values(allTools).flat().map(t => t.id)
  const allSelected = allToolIds.length > 0 && allToolIds.every(id => form.tools.includes(id))

  const toggleAll = () => {
    setForm(f => ({ ...f, tools: allSelected ? [] : [...allToolIds] }))
  }

  const toggleCategory = (categoryTools) => {
    const ids = categoryTools.map(t => t.id)
    const allIn = ids.every(id => form.tools.includes(id))
    setForm(f => ({
      ...f,
      tools: allIn
        ? f.tools.filter(id => !ids.includes(id))
        : [...new Set([...f.tools, ...ids])],
    }))
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 overflow-y-auto py-8">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg mx-4 border border-gray-700 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700 sticky top-0 bg-gray-800 z-10">
          <h2 className="text-lg font-semibold">{isEdit ? 'Edit Agent' : 'Create Agent'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500 text-red-500 px-3 py-2 rounded text-sm">{error}</div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
            <input type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value, slug: isEdit ? form.slug : autoSlug(e.target.value) })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" required />
          </div>

          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Slug</label>
              <input type="text" value={form.slug} onChange={e => setForm({ ...form, slug: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono text-sm" required />
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Provider</label>
              <select value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500">
                <option value="anthropic">Anthropic</option>
                <option value="openai">OpenAI</option>
                <option value="ollama">Ollama</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Model</label>
              <input type="text" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" required />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">API Key <span className="text-gray-500 font-normal">(optional)</span></label>
            <input type="password" value={form.api_key_ref} onChange={e => setForm({ ...form, api_key_ref: e.target.value })} placeholder="Leave blank to use global key" className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono text-sm" />
            <p className="text-xs text-gray-500 mt-1">Uses the global API key from install unless overridden here</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">System Prompt</label>
            <textarea value={form.system_prompt} onChange={e => setForm({ ...form, system_prompt: e.target.value })} rows={3} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 text-sm" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Temperature ({form.temperature})</label>
              <input type="range" min="0" max="2" step="0.1" value={form.temperature} onChange={e => setForm({ ...form, temperature: parseFloat(e.target.value) })} className="w-full" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Max Tokens</label>
              <input type="number" value={form.max_tokens} onChange={e => setForm({ ...form, max_tokens: parseInt(e.target.value) })} min="1" className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500" />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Channel Type</label>
            <select value={form.channel_type} onChange={e => setForm({ ...form, channel_type: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500">
              <option value="">None</option>
              <option value="telegram">Telegram</option>
              <option value="webhook">Webhook</option>
            </select>
          </div>

          {form.channel_type === 'telegram' && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Telegram Bot Token</label>
              <input type="password" value={form.bot_token} onChange={e => setForm({ ...form, bot_token: e.target.value })} className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono text-sm" placeholder="123456:ABC-DEF..." />
            </div>
          )}

          {/* Tools */}
          {Object.keys(allTools).length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-300">Tools</label>
                <label className="flex items-center space-x-2 cursor-pointer text-xs text-gray-400 hover:text-gray-200">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} className="rounded bg-gray-600 border-gray-500 text-blue-500" />
                  <span>Select all ({form.tools.length}/{allToolIds.length})</span>
                </label>
              </div>
              <div className="bg-gray-700/50 rounded-lg p-3 max-h-48 overflow-y-auto space-y-3">
                {Object.entries(allTools).map(([category, tools]) => {
                  const categoryAllSelected = tools.every(t => form.tools.includes(t.id))
                  const categorySomeSelected = !categoryAllSelected && tools.some(t => form.tools.includes(t.id))
                  return (
                    <div key={category}>
                      <label className="flex items-center space-x-2 cursor-pointer mb-1 hover:bg-gray-700 rounded px-1 py-0.5">
                        <input
                          type="checkbox"
                          checked={categoryAllSelected}
                          ref={el => { if (el) el.indeterminate = categorySomeSelected }}
                          onChange={() => toggleCategory(tools)}
                          className="rounded bg-gray-600 border-gray-500 text-blue-500"
                        />
                        <span className="text-xs font-semibold text-gray-400 uppercase">{category}</span>
                      </label>
                      <div className="space-y-1 ml-4">
                        {tools.map(tool => (
                          <label key={tool.id} className="flex items-center space-x-2 cursor-pointer hover:bg-gray-700 rounded px-2 py-1">
                            <input type="checkbox" checked={form.tools.includes(tool.id)} onChange={() => toggleTool(tool.id)} className="rounded bg-gray-600 border-gray-500 text-blue-500" />
                            <span className="text-sm">{tool.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex items-center justify-end space-x-3 pt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-400 hover:text-white transition">Cancel</button>
            <button type="submit" disabled={submitting} className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 px-4 py-2 rounded-lg transition flex items-center space-x-2">
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{submitting ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Agent'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
