import React, { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowLeft, Bot, Send, Plus, Loader2, MessageCircle, Clock, RefreshCw, Hash } from 'lucide-react'
import ChatMarkdown from './ChatMarkdown'

const API_URL = import.meta.env.VITE_API_URL || window.API_URL || '/api'

const SOURCE_STYLES = {
  dashboard: 'bg-blue-500/20 text-blue-400',
  telegram: 'bg-purple-500/20 text-purple-400',
  cron: 'bg-orange-500/20 text-orange-400',
  api: 'bg-gray-500/20 text-gray-400',
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now - d
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDays = Math.floor(diffHr / 24)
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatTimestamp(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export default function AgentDetailPage({ agentId, onBack }) {
  const [agent, setAgent] = useState(null)
  const [sessions, setSessions] = useState([])
  const [selectedSession, setSelectedSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [, setTick] = useState(0)
  const messagesEndRef = useRef(null)
  const pollRef = useRef(null)
  const messageCountRef = useRef(0)

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 30000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetch(`${API_URL}/agents/${agentId}`)
      .then(r => r.json())
      .then(setAgent)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [agentId])

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/chat/${agentId}/sessions`)
      const data = await res.json()
      setSessions(data.sessions || [])
    } catch {}
  }, [agentId])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  const fetchMessages = useCallback(async (sessionId, opts = {}) => {
    if (!sessionId) return
    if (!opts.silent) setLoadingMessages(true)
    try {
      const res = await fetch(`${API_URL}/chat/${agentId}/history?session_id=${sessionId}&limit=200`)
      const data = await res.json()
      const msgs = data.messages || []
      if (opts.silent && msgs.length === messageCountRef.current) return
      messageCountRef.current = msgs.length
      setMessages(msgs)
    } catch {}
    finally { if (!opts.silent) setLoadingMessages(false) }
  }, [agentId])

  useEffect(() => {
    if (!selectedSession) { setMessages([]); messageCountRef.current = 0; return }
    fetchMessages(selectedSession)
  }, [selectedSession, fetchMessages])

  // Poll for new messages every 3s
  useEffect(() => {
    if (!selectedSession) return
    pollRef.current = setInterval(() => {
      fetchMessages(selectedSession, { silent: true })
    }, 3000)
    return () => clearInterval(pollRef.current)
  }, [selectedSession, fetchMessages])

  // Also refresh sessions list periodically
  useEffect(() => {
    const interval = setInterval(fetchSessions, 10000)
    return () => clearInterval(interval)
  }, [fetchSessions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const createNewSession = async () => {
    try {
      const res = await fetch(`${API_URL}/chat/${agentId}/sessions/new`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setSelectedSession(data.session_id)
        setMessages([])
        messageCountRef.current = 0
        setSessions(prev => [{
          session_id: data.session_id,
          message_count: 0,
          started_at: new Date().toISOString(),
          last_message_at: new Date().toISOString(),
        }, ...prev])
      }
    } catch {}
  }

  const sendMessage = async () => {
    if (!input.trim() || sending) return

    let sessionId = selectedSession
    if (!sessionId) {
      try {
        const res = await fetch(`${API_URL}/chat/${agentId}/sessions/new`, { method: 'POST' })
        if (res.ok) {
          const data = await res.json()
          sessionId = data.session_id
          setSelectedSession(sessionId)
          setSessions(prev => [{
            session_id: sessionId,
            message_count: 0,
            started_at: new Date().toISOString(),
            last_message_at: new Date().toISOString(),
          }, ...prev])
        }
      } catch { return }
    }

    const userMsg = { role: 'user', content: input.trim(), source: 'dashboard', created_at: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])
    messageCountRef.current += 1
    setInput('')
    setSending(true)

    try {
      const res = await fetch(`${API_URL}/chat/${agentId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg.content, session_id: sessionId, source: 'dashboard' }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: data.response,
          source: 'dashboard',
          created_at: data.timestamp,
          prompt_tokens: data.prompt_tokens,
          completion_tokens: data.completion_tokens,
        }])
        messageCountRef.current += 1
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Error: failed to get response', created_at: new Date().toISOString() }])
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e.message}`, created_at: new Date().toISOString() }])
    } finally {
      setSending(false)
      fetchSessions()
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <p>Agent not found</p>
        <button onClick={onBack} className="mt-4 text-blue-400 hover:text-blue-300 text-sm">Go back</button>
      </div>
    )
  }

  const statusColor = agent.status === 'running' ? 'text-green-400' : agent.status === 'error' ? 'text-red-400' : 'text-gray-400'

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800/50 flex-shrink-0">
        <div className="flex items-center space-x-3 min-w-0">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition flex-shrink-0">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className={`p-2 rounded-lg flex-shrink-0 ${agent.status === 'running' ? 'bg-green-500/20' : 'bg-gray-700'}`}>
            <Bot className={`h-5 w-5 ${statusColor}`} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center space-x-2">
              <h2 className="font-semibold truncate">{agent.name}</h2>
              <span className={`text-xs px-2 py-0.5 rounded ${agent.status === 'running' ? 'bg-green-500/20 text-green-400' : 'bg-gray-600 text-gray-400'}`}>
                {agent.status?.toUpperCase()}
              </span>
              {agent.slug === 'main' && <span className="text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded">Built-in</span>}
            </div>
            <p className="text-xs text-gray-500">{agent.provider}/{agent.model}</p>
          </div>
        </div>
        <div className="flex items-center space-x-2 text-xs text-gray-500 flex-shrink-0">
          {agent.tools && <span>{agent.tools.length} tools</span>}
          {agent.channel_type && <span className="bg-gray-700 px-2 py-0.5 rounded">{agent.channel_type}</span>}
        </div>
      </div>

      {/* Main content: sessions sidebar + chat */}
      <div className="flex flex-1 min-h-0">
        {/* Sessions sidebar */}
        <div className="w-64 border-r border-gray-700 flex flex-col flex-shrink-0 bg-gray-800/30">
          <div className="p-3 border-b border-gray-700">
            <button
              onClick={createNewSession}
              className="w-full flex items-center justify-center space-x-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm transition font-medium"
            >
              <Plus className="h-4 w-4" />
              <span>New Session</span>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="text-center py-8 px-4">
                <MessageCircle className="h-8 w-8 mx-auto text-gray-600 mb-2" />
                <p className="text-xs text-gray-500">No sessions yet</p>
                <p className="text-xs text-gray-600 mt-1">Start a conversation or wait for incoming messages</p>
              </div>
            ) : sessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => setSelectedSession(s.session_id)}
                className={`w-full text-left px-3 py-3 border-b border-gray-700/50 transition ${
                  selectedSession === s.session_id
                    ? 'bg-blue-600/20 border-l-2 border-l-blue-500'
                    : 'hover:bg-gray-700/50'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-300 flex items-center space-x-1">
                    <Hash className="h-3 w-3 text-gray-500" />
                    <span>{s.session_id.slice(0, 8)}</span>
                  </span>
                  <span className="text-[10px] text-gray-500">{s.message_count} msg{s.message_count !== 1 ? 's' : ''}</span>
                </div>
                <p className="text-xs text-gray-500 flex items-center space-x-1">
                  <Clock className="h-3 w-3" />
                  <span>{formatTime(s.last_message_at || s.started_at)}</span>
                </p>
              </button>
            ))}
          </div>

          <div className="p-3 border-t border-gray-700 flex-shrink-0">
            <button onClick={fetchSessions} className="w-full flex items-center justify-center space-x-1.5 text-xs text-gray-500 hover:text-gray-300 transition">
              <RefreshCw className="h-3 w-3" />
              <span>Refresh sessions</span>
            </button>
          </div>
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {!selectedSession ? (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-500 px-4">
              <Bot className="h-12 w-12 mb-3 opacity-30" />
              <p className="text-sm font-medium mb-1">Select a session or start a new one</p>
              <p className="text-xs text-gray-600 text-center">
                Messages from cron jobs, Telegram, and other sources appear here in real time
              </p>
            </div>
          ) : (
            <>
              {/* Session header */}
              <div className="px-4 py-2 border-b border-gray-700/50 flex items-center justify-between flex-shrink-0 bg-gray-800/20">
                <div className="flex items-center space-x-2 text-sm">
                  <Hash className="h-3.5 w-3.5 text-gray-500" />
                  <span className="text-gray-400 font-mono text-xs">{selectedSession}</span>
                </div>
                <div className="flex items-center space-x-1.5 text-[10px] text-gray-500">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                  <span>Live</span>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {loadingMessages ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="text-center py-12 text-gray-500">
                    <MessageCircle className="h-10 w-10 mx-auto mb-3 opacity-30" />
                    <p className="text-sm">No messages in this session yet</p>
                  </div>
                ) : (
                  messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[75%] rounded-xl px-4 py-2.5 ${
                        msg.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-700/80 text-gray-100'
                      }`}>
                        <div className="flex items-center space-x-2 mb-1">
                          {msg.source && (
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${SOURCE_STYLES[msg.source] || SOURCE_STYLES.api}`}>
                              {msg.source}
                            </span>
                          )}
                          {msg.source_user && <span className="text-[10px] text-gray-400">@{msg.source_user}</span>}
                          <span className="text-[10px] text-gray-500">{formatTimestamp(msg.created_at)}</span>
                        </div>
                        <ChatMarkdown content={msg.content} isUser={msg.role === 'user'} />
                        {msg.prompt_tokens && (
                          <p className="text-[10px] text-gray-500 mt-1">
                            {msg.prompt_tokens + (msg.completion_tokens || 0)} tokens
                          </p>
                        )}
                      </div>
                    </div>
                  ))
                )}
                {sending && (
                  <div className="flex justify-start">
                    <div className="bg-gray-700/80 rounded-xl px-4 py-3">
                      <div className="flex items-center space-x-2">
                        <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                        <span className="text-xs text-gray-400">Thinking...</span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="p-3 border-t border-gray-700 flex-shrink-0 bg-gray-800/30">
                <div className="flex items-center space-x-2">
                  <input
                    type="text"
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                    placeholder="Type a message..."
                    disabled={sending}
                    className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50 placeholder-gray-500"
                  />
                  <button
                    onClick={sendMessage}
                    disabled={!input.trim() || sending}
                    className="p-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg transition flex-shrink-0"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
