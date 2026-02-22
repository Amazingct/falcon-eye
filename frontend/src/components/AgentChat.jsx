import { authFetch } from '../App'
import React, { useState, useEffect, useRef } from 'react'
import { MessageCircle, Send, Plus, RefreshCw, Loader2, Bot, ChevronDown } from 'lucide-react'
import ChatMarkdown from './ChatMarkdown'
import ChatMedia from './ChatMedia'

const API_URL = import.meta.env.VITE_API_URL || window.API_URL || '/api'

const isMediaMessage = (msg) => {
  if (!msg) return false
  if (msg.role === 'assistant_media' || msg.role === 'user_media') return true
  return typeof msg.content === 'object' && msg.content && Array.isArray(msg.content.media)
}

export default function AgentChat({ agentId: propAgentId, compact = false }) {
  const [agents, setAgents] = useState([])
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [sessions, setSessions] = useState([])
  const [selectedSession, setSelectedSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sendingMsg, setSendingMsg] = useState(false)
  const messagesEndRef = useRef(null)

  // Fetch agents (skip if agentId prop provided)
  useEffect(() => {
    if (propAgentId) {
      setSelectedAgent({ id: propAgentId })
      return
    }
    authFetch(`${API_URL}/agents/`).then(r => r.json()).then(d => {
      const agentList = d.agents || []
      setAgents(agentList)
      if (agentList.length > 0 && !selectedAgent) setSelectedAgent(agentList[0])
    }).catch(() => {})
  }, [propAgentId])

  // Fetch sessions when agent changes
  useEffect(() => {
    if (!selectedAgent) return
    authFetch(`${API_URL}/chat/${selectedAgent.id}/sessions`).then(r => r.json()).then(d => {
      const list = d.sessions || []
      setSessions(list)
      if (list.length > 0 && !selectedSession) setSelectedSession(list[0].session_id)
    }).catch(() => {})
  }, [selectedAgent])

  // Load messages when session changes
  useEffect(() => {
    if (!selectedAgent || !selectedSession) { setMessages([]); return }
    setLoading(true)
    authFetch(`${API_URL}/chat/${selectedAgent.id}/history?session_id=${selectedSession}&limit=100`)
      .then(r => r.json())
      .then(d => setMessages(d.messages || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selectedAgent, selectedSession])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const createNewSession = async () => {
    if (!selectedAgent) return
    try {
      const res = await authFetch(`${API_URL}/chat/${selectedAgent.id}/sessions/new`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setSelectedSession(data.session_id)
        setMessages([])
        setSessions(prev => [{ session_id: data.session_id, message_count: 0, started_at: new Date().toISOString() }, ...prev])
      }
    } catch (e) {}
  }

  const sendMessage = async () => {
    if (!input.trim() || !selectedAgent || sendingMsg) return

    let sessionId = selectedSession
    if (!sessionId) {
      try {
        const res = await authFetch(`${API_URL}/chat/${selectedAgent.id}/sessions/new`, { method: 'POST' })
        if (res.ok) {
          const data = await res.json()
          sessionId = data.session_id
          setSelectedSession(sessionId)
          setSessions(prev => [{ session_id: sessionId, message_count: 0, started_at: new Date().toISOString() }, ...prev])
        }
      } catch (e) { return }
    }

    const userMsg = { role: 'user', content: input.trim(), source: 'dashboard', created_at: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setSendingMsg(true)

    try {
      const res = await authFetch(`${API_URL}/chat/${selectedAgent.id}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg.content, session_id: sessionId, source: 'dashboard' }),
      })
      if (res.ok) {
        const data = await res.json()
        // Refresh history so tool-emitted media messages appear immediately
        try {
          const histRes = await authFetch(`${API_URL}/chat/${selectedAgent.id}/history?session_id=${sessionId}&limit=200`)
          const hist = await histRes.json()
          setMessages(hist.messages || [])
        } catch (e) {
          setMessages(prev => [...prev, { role: 'assistant', content: data.response, source: 'dashboard', created_at: data.timestamp }])
        }
      } else {
        const errData = await res.json().catch(() => null)
        const detail = errData?.detail || 'Error getting response'
        setMessages(prev => [...prev, { role: 'assistant', content: detail, created_at: new Date().toISOString() }])
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e.message}`, created_at: new Date().toISOString() }])
    } finally {
      setSendingMsg(false)
    }
  }

  const sourceBadge = (source) => {
    if (!source) return null
    const styles = {
      dashboard: 'bg-blue-500/20 text-blue-400',
      telegram: 'bg-purple-500/20 text-purple-400',
      cron: 'bg-orange-500/20 text-orange-400',
      api: 'bg-gray-500/20 text-gray-400',
    }
    return <span className={`text-[10px] px-1.5 py-0.5 rounded ${styles[source] || 'bg-gray-500/20 text-gray-400'}`}>{source}</span>
  }

  return (
    <div className={`flex ${compact ? 'h-full' : 'h-[calc(100vh-180px)] rounded-lg border border-gray-700'} bg-gray-800 overflow-hidden`}>
      {/* Left sidebar: agent + sessions (hidden in compact/propAgentId mode) */}
      {!compact && !propAgentId && (
      <div className="w-64 border-r border-gray-700 flex flex-col flex-shrink-0">
        {/* Agent selector */}
        <div className="p-3 border-b border-gray-700">
          <label className="block text-xs font-medium text-gray-400 mb-1">Agent</label>
          <select
            value={selectedAgent?.id || ''}
            onChange={e => {
              const a = agents.find(a => a.id === e.target.value)
              setSelectedAgent(a)
              setSelectedSession(null)
              setMessages([])
            }}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
          >
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>

        {/* Sessions */}
        <div className="p-2 border-b border-gray-700">
          <button onClick={createNewSession} className="w-full flex items-center justify-center space-x-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm transition">
            <Plus className="h-4 w-4" /><span>New Session</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.map(s => (
            <button
              key={s.session_id}
              onClick={() => setSelectedSession(s.session_id)}
              className={`w-full text-left px-3 py-2 border-b border-gray-700/50 hover:bg-gray-700 transition ${selectedSession === s.session_id ? 'bg-gray-700' : ''}`}
            >
              <p className="text-sm truncate">{s.session_id.slice(0, 8)}...</p>
              <p className="text-xs text-gray-500">{s.message_count} msgs • {s.started_at ? new Date(s.started_at).toLocaleDateString() : '--'}</p>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="text-center text-gray-500 text-sm py-6">No sessions yet</p>
          )}
        </div>
      </div>
      )}

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        {!compact && (
        <div className="px-4 py-3 border-b border-gray-700 flex items-center space-x-2">
          <Bot className="h-5 w-5 text-blue-500" />
          <span className="font-medium">{selectedAgent?.name || 'Select an agent'}</span>
          {selectedSession && <span className="text-xs text-gray-500">Session: {selectedSession.slice(0, 8)}</span>}
        </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center text-gray-500 py-12">
              <MessageCircle className="h-10 w-10 mx-auto mb-3 opacity-50" />
              <p className="text-sm">Start a conversation with your agent</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-lg px-3 py-2 ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-100'}`}>
                  <div className="flex items-center space-x-2 mb-1">
                    {sourceBadge(msg.source)}
                    {msg.source_user && <span className="text-[10px] text-gray-400">@{msg.source_user}</span>}
                  </div>
                  {isMediaMessage(msg) ? (
                    <ChatMedia content={msg.content} apiUrl={API_URL} />
                  ) : (
                    <ChatMarkdown content={typeof msg.content === 'string' ? msg.content : ''} isUser={msg.role === 'user'} />
                  )}
                </div>
              </div>
            ))
          )}
          {sendingMsg && (
            <div className="flex justify-start">
              <div className="bg-gray-700 rounded-lg px-4 py-3 flex items-center space-x-3">
                <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
                <span className="text-sm text-gray-300">Thinking...</span>
                <span className="flex space-x-1">
                  <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-3 border-t border-gray-700">
          <div className="flex items-center space-x-2">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyPress={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
              placeholder={selectedAgent ? 'Type a message...' : 'Select an agent first'}
              disabled={!selectedAgent || sendingMsg}
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || !selectedAgent || sendingMsg}
              className="p-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg transition"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
