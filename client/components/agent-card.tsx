'use client'

import { Mic, Phone, CheckCircle2, AlertCircle, Clock, History } from 'lucide-react'

interface AgentCardProps {
  id: string
  callerName: string
  callerPhone: string
  duration: string
  status: 'active' | 'processing' | 'complete' | 'escalated' | 'cancelled' | 'archived'
  claimType: string
  location: string
  confidence: number
  coverageStatus: 'covered' | 'not-covered' | 'pending'
  transcript: string
  stageLabel?: string
  nextReason?: string
  hasCallbackContext?: boolean
  onSelect: () => void
  isSelected: boolean
}

export function AgentCard({
  callerName,
  callerPhone,
  duration,
  status,
  claimType,
  location,
  confidence,
  coverageStatus,
  transcript,
  stageLabel,
  nextReason,
  hasCallbackContext,
  onSelect,
  isSelected,
}: AgentCardProps) {
  const statusConfig = {
    active: { color: 'bg-emerald-500', label: 'Live', pulse: true },
    processing: { color: 'bg-amber-500', label: 'Reviewing', pulse: true },
    complete: { color: 'bg-blue-500', label: 'Complete', pulse: false },
    escalated: { color: 'bg-red-500', label: 'Escalated', pulse: true },
    cancelled: { color: 'bg-zinc-500', label: 'Cancelled', pulse: false },
    archived: { color: 'bg-zinc-600', label: 'Archived', pulse: false },
  }

  const coverageConfig = {
    covered: { icon: CheckCircle2, color: 'text-emerald-400', label: 'Covered' },
    'not-covered': { icon: AlertCircle, color: 'text-red-400', label: 'Not Covered' },
    pending: { icon: Clock, color: 'text-zinc-400', label: 'Pending' },
  }

  const CoverageIcon = coverageConfig[coverageStatus].icon

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left p-5 rounded-xl border transition-all ${
        isSelected
          ? 'bg-zinc-800/80 border-violet-500/50 shadow-[0_0_0_1px_rgba(139,92,246,0.15)]'
          : 'bg-zinc-900/50 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800/30'
      }`}
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center">
            {status === 'active' ? (
              <Mic className="w-4 h-4 text-emerald-400" />
            ) : (
              <Phone className="w-4 h-4 text-zinc-400" />
            )}
          </div>
          <div>
            <p className="text-sm font-medium text-white">{callerName}</p>
            <p className="text-xs text-zinc-400">{callerPhone}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400">{duration}</span>
          <div className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${statusConfig[status].color} ${
                statusConfig[status].pulse ? 'animate-pulse' : ''
              }`}
            />
            <span className="text-xs text-zinc-400">{statusConfig[status].label}</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-400">Type</p>
            <p className="text-sm text-zinc-200">{claimType || '—'}</p>
          </div>
          {hasCallbackContext && (
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-800/80 px-2 py-1 text-[10px] text-zinc-400">
              <History className="w-3 h-3" /> Callback
            </span>
          )}
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">Location</p>
          <p className="text-sm text-zinc-200">{location || '—'}</p>
        </div>

        {stageLabel && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1">Stage</p>
            <p className="text-xs text-zinc-200">{stageLabel}</p>
            {nextReason && (
              <p className="text-[11px] text-amber-400 mt-1 leading-relaxed">{nextReason}</p>
            )}
          </div>
        )}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <CoverageIcon className={`w-3.5 h-3.5 ${coverageConfig[coverageStatus].color}`} />
            <span className={`text-xs ${coverageConfig[coverageStatus].color}`}>
              {coverageConfig[coverageStatus].label}
            </span>
          </div>
          {confidence > 0 && (
            <div className="flex items-center gap-2">
              <div className="w-16 h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-violet-500 rounded-full transition-all"
                  style={{ width: `${confidence}%` }}
                />
              </div>
              <span className="text-[10px] text-zinc-400">{confidence}%</span>
            </div>
          )}
        </div>

        {transcript && (
          <p className="text-xs text-zinc-400 line-clamp-2 leading-relaxed">
            {transcript}
          </p>
        )}
      </div>
    </button>
  )
}
