import React, { useState } from 'react'
import { Clock } from 'lucide-react'

const QUICK_PRESETS = [
  { label: 'Every minute', cron: '* * * * *' },
  { label: 'Every 5 min', cron: '*/5 * * * *' },
  { label: 'Every 10 min', cron: '*/10 * * * *' },
  { label: 'Every 15 min', cron: '*/15 * * * *' },
  { label: 'Every 30 min', cron: '*/30 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
]

const DAYS_OF_WEEK = [
  { label: 'Mon', value: 1 },
  { label: 'Tue', value: 2 },
  { label: 'Wed', value: 3 },
  { label: 'Thu', value: 4 },
  { label: 'Fri', value: 5 },
  { label: 'Sat', value: 6 },
  { label: 'Sun', value: 0 },
]

function formatTime(hour, minute) {
  const h = parseInt(hour)
  const m = parseInt(minute)
  const period = h >= 12 ? 'PM' : 'AM'
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
  return `${h12}:${String(m).padStart(2, '0')} ${period}`
}

function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

export function describeCron(cron) {
  if (!cron) return 'No schedule set'
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return 'Invalid expression'

  const [min, hour, dom, month, dow] = parts

  if (cron.trim() === '* * * * *') return 'Every minute'
  if (min.startsWith('*/') && hour === '*' && dom === '*' && month === '*' && dow === '*') {
    return `Every ${min.slice(2)} minutes`
  }
  if (min === '0' && hour === '*' && dom === '*' && month === '*' && dow === '*') return 'Every hour, on the hour'
  if (min === '0' && hour.startsWith('*/') && dom === '*' && month === '*' && dow === '*') {
    return `Every ${hour.slice(2)} hours`
  }

  const isSimpleTime = !min.includes('/') && !min.includes(',') && !hour.includes('/') && !hour.includes(',')
  if (!isSimpleTime) return cron

  const timeStr = formatTime(hour, min)

  if (dom === '*' && month === '*' && dow === '*') {
    return `Daily at ${timeStr}`
  }

  if (dom === '*' && month === '*' && dow !== '*') {
    const dayNames = { '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat' }
    const days = dow.split(',').map(d => dayNames[d] || d).join(', ')
    return `${days} at ${timeStr}`
  }

  if (dom !== '*' && month === '*' && dow === '*') {
    return `Monthly on the ${ordinal(parseInt(dom))} at ${timeStr}`
  }

  return cron
}

function detectMode(cron) {
  if (!cron) return { mode: 'preset' }
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return { mode: 'custom' }

  const [min, hour, dom, month, dow] = parts

  for (const preset of QUICK_PRESETS) {
    if (cron.trim() === preset.cron) return { mode: 'preset', activePreset: preset.cron }
  }

  const isSimpleTime = /^\d+$/.test(min) && /^\d+$/.test(hour)

  if (isSimpleTime && dom === '*' && month === '*' && dow === '*') {
    return { mode: 'daily', hour: parseInt(hour), minute: parseInt(min) }
  }
  if (isSimpleTime && dom === '*' && month === '*' && dow !== '*') {
    return { mode: 'weekly', hour: parseInt(hour), minute: parseInt(min), days: dow.split(',').map(Number) }
  }
  if (isSimpleTime && dom !== '*' && month === '*' && dow === '*') {
    return { mode: 'monthly', hour: parseInt(hour), minute: parseInt(min), dayOfMonth: parseInt(dom) }
  }

  return { mode: 'custom' }
}

export default function CronExpressionBuilder({ value, onChange }) {
  const initial = detectMode(value)
  const [mode, setMode] = useState(initial.mode)
  const [hour, setHour] = useState(initial.hour ?? 9)
  const [minute, setMinute] = useState(initial.minute ?? 0)
  const [selectedDays, setSelectedDays] = useState(initial.days ?? [1])
  const [dayOfMonth, setDayOfMonth] = useState(initial.dayOfMonth ?? 1)

  const switchMode = (newMode) => {
    setMode(newMode)
    switch (newMode) {
      case 'preset': {
        const match = QUICK_PRESETS.find(p => p.cron === value)
        onChange(match ? match.cron : '0 * * * *')
        break
      }
      case 'daily':
        onChange(`${minute} ${hour} * * *`)
        break
      case 'weekly':
        onChange(`${minute} ${hour} * * ${selectedDays.sort((a, b) => a - b).join(',')}`)
        break
      case 'monthly':
        onChange(`${minute} ${hour} ${dayOfMonth} * *`)
        break
      case 'custom':
        break
    }
  }

  const updateHour = (h) => {
    setHour(h)
    if (mode === 'daily') onChange(`${minute} ${h} * * *`)
    else if (mode === 'weekly') onChange(`${minute} ${h} * * ${selectedDays.sort((a, b) => a - b).join(',')}`)
    else if (mode === 'monthly') onChange(`${minute} ${h} ${dayOfMonth} * *`)
  }

  const updateMinute = (m) => {
    setMinute(m)
    if (mode === 'daily') onChange(`${m} ${hour} * * *`)
    else if (mode === 'weekly') onChange(`${m} ${hour} * * ${selectedDays.sort((a, b) => a - b).join(',')}`)
    else if (mode === 'monthly') onChange(`${m} ${hour} ${dayOfMonth} * *`)
  }

  const toggleDay = (day) => {
    const next = selectedDays.includes(day)
      ? selectedDays.filter(d => d !== day)
      : [...selectedDays, day]
    const days = next.length > 0 ? next : [day]
    setSelectedDays(days)
    onChange(`${minute} ${hour} * * ${days.sort((a, b) => a - b).join(',')}`)
  }

  const updateDayOfMonth = (d) => {
    setDayOfMonth(d)
    onChange(`${minute} ${hour} ${d} * *`)
  }

  const description = describeCron(value)

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-gray-300">Schedule</label>

      <div className="flex bg-gray-700/50 rounded-lg p-1 gap-0.5">
        {[
          { id: 'preset', label: 'Interval' },
          { id: 'daily', label: 'Daily' },
          { id: 'weekly', label: 'Weekly' },
          { id: 'monthly', label: 'Monthly' },
          { id: 'custom', label: 'Custom' },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => switchMode(tab.id)}
            className={`flex-1 px-2 py-1.5 rounded-md text-xs font-medium transition-all ${
              mode === tab.id
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-600/50'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {mode === 'preset' && (
        <div className="grid grid-cols-3 gap-2">
          {QUICK_PRESETS.map(preset => (
            <button
              key={preset.cron}
              type="button"
              onClick={() => onChange(preset.cron)}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-all border ${
                value === preset.cron
                  ? 'bg-blue-600/20 border-blue-500 text-blue-400'
                  : 'bg-gray-700/50 border-gray-600 text-gray-300 hover:border-gray-500 hover:bg-gray-700'
              }`}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}

      {mode === 'daily' && (
        <TimePicker hour={hour} minute={minute} onHourChange={updateHour} onMinuteChange={updateMinute} />
      )}

      {mode === 'weekly' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-2">Day(s) of week</label>
            <div className="flex gap-1.5">
              {DAYS_OF_WEEK.map(day => (
                <button
                  key={day.value}
                  type="button"
                  onClick={() => toggleDay(day.value)}
                  className={`flex-1 py-2 rounded-lg text-xs font-medium transition-all border ${
                    selectedDays.includes(day.value)
                      ? 'bg-blue-600/20 border-blue-500 text-blue-400'
                      : 'bg-gray-700/50 border-gray-600 text-gray-400 hover:border-gray-500'
                  }`}
                >
                  {day.label}
                </button>
              ))}
            </div>
          </div>
          <TimePicker hour={hour} minute={minute} onHourChange={updateHour} onMinuteChange={updateMinute} />
        </div>
      )}

      {mode === 'monthly' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-2">Day of month</label>
            <select
              value={dayOfMonth}
              onChange={e => updateDayOfMonth(parseInt(e.target.value))}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            >
              {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
                <option key={d} value={d}>{ordinal(d)}</option>
              ))}
            </select>
          </div>
          <TimePicker hour={hour} minute={minute} onHourChange={updateHour} onMinuteChange={updateMinute} />
        </div>
      )}

      {mode === 'custom' && (
        <div>
          <input
            type="text"
            value={value}
            onChange={e => onChange(e.target.value)}
            placeholder="* * * * *"
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono text-sm"
          />
          <p className="text-xs text-gray-500 mt-1">Format: minute hour day-of-month month day-of-week</p>
        </div>
      )}

      <div className="flex items-center gap-2 bg-gray-700/30 rounded-lg px-3 py-2 border border-gray-700">
        <Clock className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />
        <span className="text-xs text-gray-400">{description}</span>
        <code className="ml-auto text-xs font-mono text-gray-500 flex-shrink-0">{value}</code>
      </div>
    </div>
  )
}

function TimePicker({ hour, minute, onHourChange, onMinuteChange }) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-2">Time</label>
      <div className="flex items-center gap-2">
        <select
          value={hour}
          onChange={e => onHourChange(parseInt(e.target.value))}
          className="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          {Array.from({ length: 24 }, (_, i) => i).map(h => (
            <option key={h} value={h}>
              {String(h === 0 ? 12 : h > 12 ? h - 12 : h).padStart(2, '0')} {h >= 12 ? 'PM' : 'AM'}
            </option>
          ))}
        </select>
        <span className="text-gray-400 text-lg font-bold">:</span>
        <select
          value={minute}
          onChange={e => onMinuteChange(parseInt(e.target.value))}
          className="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          {Array.from({ length: 12 }, (_, i) => i * 5).map(m => (
            <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
          ))}
        </select>
      </div>
    </div>
  )
}
