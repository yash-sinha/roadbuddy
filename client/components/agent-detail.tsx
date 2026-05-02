'use client'

import { useState } from 'react'
import { Mic, Phone, CheckCircle2, AlertCircle, Clock, AlertTriangle, History, MapPinned, CarFront, ShieldCheck, ClipboardList, FileText } from 'lucide-react'

type ClaimField = 'name' | 'location' | 'vehicle' | 'issue_type' | 'urgency'

interface ClaimSchema {
  name: string | null
  location: string | null
  vehicle: string | null
  issue_type: string | null
  urgency: string | null
}

interface IntakeGap {
  field: ClaimField
  reason: string
}

interface IntakeReview {
  ready: boolean
  gaps: IntakeGap[]
  nextField: ClaimField | null
  nextReason: string | null
}

interface CallbackContext {
  id?: string
  caller_name?: string | null
  location?: string | null
  vehicle?: string | null
  issue_type?: string | null
  urgency?: string | null
  stage?: string | null
  covered?: boolean | null
  confidence?: number | null
  reasoning?: string | null
}

interface TimelineEvent {
  stage: string
  label: string
  time: string
  note?: string
}

interface AgentDetailProps {
  agent: {
    id: string
    callerName: string
    callerPhone: string
    duration: string
    status: 'active' | 'processing' | 'complete' | 'escalated' | 'cancelled' | 'archived'
    claimType: string
    location: string
    vehicle: string
    urgency: string
    confidence: number
    coverageStatus: 'covered' | 'not-covered' | 'pending'
    reasoning: string
    transcript: string
    notificationSent: boolean
    stage?: string
    schema?: ClaimSchema
    intakeReview?: IntakeReview | null
    callbackContext?: CallbackContext | null
    damageType?: string
    damageSeverity?: string
    damageReason?: string
    damageAmbiguous?: boolean
    policyChunks?: string[]
    action?: {
      type: string
      garage?: { name: string; eta_minutes: number; distance_km?: number }
      taxi?: { name: string; eta_minutes: number; pickup: string }
      rental?: { name: string; address: string; eta_minutes?: number } | null
    }
    callSummary?: string
    timeline?: TimelineEvent[]
  }
  policyText?: string
  canReview?: boolean
  onApprove?: (notes: string) => void
  onDecline?: (notes: string) => void
  onArchive?: () => void
  canArchive?: boolean
  reviewSubmitting?: boolean
  reviewError?: string | null
}

const coverageConfig = {
  covered: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Covered' },
  'not-covered': { icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-500/10', label: 'Not Covered' },
  pending: { icon: Clock, color: 'text-zinc-300', bg: 'bg-zinc-500/10', label: 'Pending' },
}

const stageLabel: Record<string, string> = {
  intake: 'Voice Intake',
  call_ended: 'Reviewing Claim',
  damage_assessment: 'Damage Assessment',
  rag: 'Policy Retrieval',
  coverage: 'Coverage Review',
  escalation: 'Human Review',
  decision: 'Assistance Planning',
  complete: 'Customer Updated',
}

const fieldLabels: Record<ClaimField, string> = {
  name: 'Name',
  location: 'Location',
  vehicle: 'Vehicle',
  issue_type: 'Issue',
  urgency: 'Urgency',
}

function formatLabel(value?: string | null) {
  if (!value) return '—'
  return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase())
}

function stageSummary(value?: string) {
  if (!value) return 'Waiting for first update'
  return stageLabel[value] || formatLabel(value)
}

function fieldValue(agent: AgentDetailProps['agent'], field: ClaimField) {
  if (agent.schema?.[field]) return formatLabel(agent.schema[field])
  switch (field) {
    case 'name':
      return agent.callerName || '—'
    case 'location':
      return agent.location || '—'
    case 'vehicle':
      return agent.vehicle || '—'
    case 'issue_type':
      return agent.claimType || '—'
    case 'urgency':
      return agent.urgency || '—'
  }
}

function fieldQuality(agent: AgentDetailProps['agent'], field: ClaimField) {
  const value = agent.schema?.[field]
  const gap = agent.intakeReview?.gaps.find((item) => item.field === field)
  if (!value) {
    return { label: 'Missing', tone: 'text-red-400 bg-red-500/10 border-red-500/20', reason: gap?.reason || 'Not captured yet.' }
  }
  if (gap) {
    return { label: 'Needs Review', tone: 'text-amber-400 bg-amber-500/10 border-amber-500/20', reason: gap.reason }
  }
  return { label: 'Confirmed', tone: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20', reason: 'Usable for downstream review.' }
}

function callbackRows(agent: AgentDetailProps['agent']) {
  const callback = agent.callbackContext
  if (!callback) return []
  const previous: Record<ClaimField, string | null | undefined> = {
    name: callback.caller_name,
    location: callback.location,
    vehicle: callback.vehicle,
    issue_type: callback.issue_type,
    urgency: callback.urgency,
  }

  return (Object.keys(fieldLabels) as ClaimField[]).map((field) => {
    const currentRaw = agent.schema?.[field] || null
    const previousRaw = previous[field] || null
    let status = 'Unchanged'
    if (!previousRaw && currentRaw) status = 'Added'
    else if (previousRaw && !currentRaw) status = 'Missing Now'
    else if (previousRaw !== currentRaw) status = 'Changed'

    return {
      field,
      label: fieldLabels[field],
      previous: previousRaw ? formatLabel(previousRaw) : '—',
      current: currentRaw ? formatLabel(currentRaw) : '—',
      status,
    }
  })
}

export function AgentDetail({ agent, policyText = '', canReview = false, onApprove, onDecline, onArchive, canArchive = false, reviewSubmitting = false, reviewError = null }: AgentDetailProps) {
  const [notes, setNotes] = useState('')
  const CoverageIcon = coverageConfig[agent.coverageStatus].icon
  const callbackDiff = callbackRows(agent)

  return (
    <div className="h-full flex flex-col">
      <div className="p-6 border-b border-zinc-800">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-zinc-800 flex items-center justify-center">
              {agent.status === 'active' ? (
                <Mic className="w-5 h-5 text-emerald-400" />
              ) : (
                <Phone className="w-5 h-5 text-zinc-400" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-medium text-white">{agent.callerName}</h2>
                {agent.callbackContext && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-800/80 px-2 py-1 text-[10px] text-zinc-400">
                    <History className="w-3 h-3" /> Callback
                  </span>
                )}
              </div>
              <p className="text-sm text-zinc-300">{agent.callerPhone} · {agent.duration}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 rounded-full px-3 py-1.5 ${
              agent.status === 'active' ? 'bg-emerald-500/10' :
              agent.status === 'escalated' ? 'bg-red-500/10' :
              agent.status === 'complete' ? 'bg-blue-500/10' :
              agent.status === 'archived' ? 'bg-zinc-500/10' :
              'bg-amber-500/10'
            }`}>
              <span className={`w-2 h-2 rounded-full ${
                agent.status === 'active' ? 'bg-emerald-500 animate-pulse' :
                agent.status === 'escalated' ? 'bg-red-500 animate-pulse' :
                agent.status === 'complete' ? 'bg-blue-500' :
                agent.status === 'archived' ? 'bg-zinc-500' :
                'bg-amber-500 animate-pulse'
              }`} />
              <span className="text-xs text-zinc-300">{stageSummary(agent.stage)}</span>
            </div>
            {canArchive && onArchive && (
              <button
                onClick={() => {
                  if (window.confirm('Archive this claim? It will be removed from the active queue.')) {
                    onArchive()
                  }
                }}
                className="rounded-full border border-zinc-700 hover:border-zinc-500 px-3 py-1.5 text-xs text-zinc-300 hover:text-white transition-colors"
                title="Archive claim — removes from active queue"
              >
                Archive
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto thin-scroll p-6 space-y-6">
        {agent.callSummary && (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
            <div className="flex items-center gap-2 mb-2">
              <ClipboardList className="w-4 h-4 text-violet-400" />
              <p className="text-xs uppercase tracking-wider text-zinc-300">Call Summary</p>
            </div>
            <p className="text-sm text-zinc-300 leading-relaxed">{agent.callSummary}</p>
          </div>
        )}

        {agent.intakeReview && !agent.intakeReview.ready && (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <p className="text-sm font-medium text-amber-400">Intake still needs clarification</p>
            </div>
            <p className="text-sm text-zinc-300">{agent.intakeReview.nextReason}</p>
          </div>
        )}

        <div>
          <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Field Quality</h3>
          <div className="grid grid-cols-2 gap-4">
            {(Object.keys(fieldLabels) as ClaimField[]).map((field) => {
              const quality = fieldQuality(agent, field)
              return (
                <div key={field} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <p className="text-xs text-zinc-300">{fieldLabels[field]}</p>
                    <span className={`rounded-full border px-2 py-1 text-[10px] ${quality.tone}`}>
                      {quality.label}
                    </span>
                  </div>
                  <p className="text-sm text-white">{fieldValue(agent, field)}</p>
                  <p className="text-xs text-zinc-300 mt-2 leading-relaxed">{quality.reason}</p>
                </div>
              )
            })}
          </div>
        </div>

        {callbackDiff.length > 0 && (
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Callback Context Diff</h3>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 overflow-hidden">
              {callbackDiff.map((row) => (
                <div key={row.field} className="grid grid-cols-[120px_1fr_1fr_90px] gap-4 px-4 py-3 border-b border-zinc-800 last:border-b-0 text-sm">
                  <div className="text-zinc-300">{row.label}</div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1">Previous</p>
                    <p className="text-zinc-300">{row.previous}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1">Current</p>
                    <p className="text-zinc-300">{row.current}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-[11px] text-violet-300">{row.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {(agent.damageType || agent.damageReason) && (
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Damage Assessment — Agent Reasoning</h3>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-violet-400" />
                  <span className="text-sm font-medium text-white">
                    {formatLabel(agent.damageType) || 'Unknown'}
                    {agent.damageSeverity ? ` — ${formatLabel(agent.damageSeverity)}` : ''}
                  </span>
                </div>
                {agent.damageAmbiguous && (
                  <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                    Ambiguous
                  </span>
                )}
              </div>
              {agent.damageReason && (
                <p className="text-sm text-zinc-300 leading-relaxed">{agent.damageReason}</p>
              )}
            </div>
          </div>
        )}

        <div>
          <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Coverage Decision — Agent Reasoning</h3>
          <div className={`p-4 rounded-xl ${coverageConfig[agent.coverageStatus].bg}`}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <CoverageIcon className={`w-4 h-4 ${coverageConfig[agent.coverageStatus].color}`} />
                <span className={`text-sm font-medium ${coverageConfig[agent.coverageStatus].color}`}>
                  {coverageConfig[agent.coverageStatus].label}
                </span>
              </div>
              {agent.confidence > 0 && (
                <span className="text-xs text-zinc-300">{agent.confidence}% confidence</span>
              )}
            </div>
            {agent.confidence > 0 && (
              <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden mb-3">
                <div
                  className={`h-full rounded-full transition-all ${
                    agent.confidence >= 70 ? 'bg-emerald-500' :
                    agent.confidence >= 40 ? 'bg-amber-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${agent.confidence}%` }}
                />
              </div>
            )}
            <p className="text-sm text-zinc-300 leading-relaxed">{agent.reasoning}</p>
            {agent.status === 'escalated' && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                <p className="text-[11px] uppercase tracking-wider text-amber-300 mb-1">Why escalated</p>
                <p className="text-xs text-zinc-200 leading-relaxed">
                  {agent.intakeReview && !agent.intakeReview.ready
                    ? `Intake gating: ${agent.intakeReview.nextReason}`
                    : agent.damageAmbiguous
                    ? 'Damage assessment was ambiguous — needs human classification.'
                    : agent.confidence < 70
                    ? `Coverage confidence ${agent.confidence}% is below the 70% threshold.`
                    : 'Forced escalation. See reasoning above.'}
                </p>
              </div>
            )}
          </div>
        </div>

        {canReview && (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <p className="text-sm font-medium text-amber-400">Human decision required</p>
            </div>
            <p className="text-sm text-zinc-300 mb-3">
              Review the intake quality, policy evidence, and reasoning below, then confirm the outcome for the customer.
            </p>
            <label className="block text-[11px] uppercase tracking-wider text-zinc-300 mb-1">
              Reviewer notes <span className="text-zinc-500 normal-case tracking-normal">(optional — appended to the audit trail)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Verified incident reference with caller; approving as covered."
              rows={2}
              className="w-full rounded-lg bg-zinc-950/60 border border-zinc-800 focus:border-amber-500/40 focus:outline-none text-sm text-zinc-100 placeholder:text-zinc-500 px-3 py-2 mb-3 resize-y"
            />
            {reviewError && (
              <p className="text-xs text-red-400 mb-2">{reviewError}</p>
            )}
            <div className="flex gap-3">
              <button
                onClick={() => onApprove?.(notes)}
                disabled={reviewSubmitting}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-wait rounded-lg transition-colors"
              >
                <CheckCircle2 className="w-4 h-4" /> {reviewSubmitting ? 'Submitting…' : 'Approve Claim'}
              </button>
              <button
                onClick={() => onDecline?.(notes)}
                disabled={reviewSubmitting}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-wait rounded-lg transition-colors"
              >
                <AlertCircle className="w-4 h-4" /> {reviewSubmitting ? 'Submitting…' : 'Reject Claim'}
              </button>
            </div>
          </div>
        )}

        {(agent.damageType || agent.damageSeverity || agent.action?.garage || agent.action?.taxi || agent.action?.rental) && (
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Proposed Assistance</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <ShieldCheck className="w-4 h-4 text-violet-400" />
                  <p className="text-xs uppercase tracking-wider text-zinc-300">Assessment</p>
                </div>
                <p className="text-sm text-white">{formatLabel(agent.damageType) || '—'}{agent.damageSeverity ? ` — ${formatLabel(agent.damageSeverity)}` : ''}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <CarFront className="w-4 h-4 text-violet-400" />
                  <p className="text-xs uppercase tracking-wider text-zinc-300">Primary Action</p>
                </div>
                <p className="text-sm text-white">{formatLabel(agent.action?.type) || 'Awaiting action selection'}</p>
                <p className="text-xs text-zinc-300 mt-2">ETA basis: nearest suitable provider from the mock dispatch dataset.</p>
              </div>
            </div>

            {(agent.action?.garage || agent.action?.taxi || agent.action?.rental) && (
              <div className="space-y-3 mt-4">
                {agent.action?.garage && (
                  <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MapPinned className="w-4 h-4 text-zinc-400" />
                      <p className="text-xs uppercase tracking-wider text-zinc-300">Garage / Roadside</p>
                    </div>
                    <p className="text-sm text-white">{agent.action.garage.name}</p>
                    <p className="text-xs text-zinc-300 mt-2">
                      ETA {agent.action.garage.eta_minutes} min
                      {agent.action.garage.distance_km ? ` • ${agent.action.garage.distance_km.toFixed(1)} km away` : ''}
                    </p>
                  </div>
                )}
                {agent.action?.taxi && (
                  <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <p className="text-xs uppercase tracking-wider text-zinc-300 mb-2">Taxi Support</p>
                    <p className="text-sm text-white">{agent.action.taxi.name}</p>
                    <p className="text-xs text-zinc-300 mt-2">ETA {agent.action.taxi.eta_minutes} min • Pickup {agent.action.taxi.pickup}</p>
                  </div>
                )}
                {agent.action?.rental && (
                  <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <p className="text-xs uppercase tracking-wider text-zinc-300 mb-2">Rental Support</p>
                    <p className="text-sm text-white">{agent.action.rental.name}</p>
                    <p className="text-xs text-zinc-300 mt-2">{agent.action.rental.address}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {(policyText || (agent.policyChunks && agent.policyChunks.length > 0)) && (
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Policy Document</h3>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 overflow-hidden">
              <div className="border-b border-zinc-800 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="w-4 h-4 text-violet-400" />
                  <p className="text-xs uppercase tracking-wider text-zinc-300">Retrieved For This Claim</p>
                </div>
                {agent.policyChunks && agent.policyChunks.length > 0 ? (
                  <div className="space-y-3">
                    {agent.policyChunks.map((chunk, index) => (
                      <div key={`${chunk}-${index}`} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                        <p className="text-[11px] uppercase tracking-wider text-zinc-400 mb-2">Section {index + 1}</p>
                        <p className="text-sm text-zinc-300 leading-relaxed">{chunk}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-zinc-300">
                    Policy retrieval has not run for this claim yet.
                  </p>
                )}
              </div>
              {policyText && (
                <details className="group">
                  <summary className="cursor-pointer list-none p-4 text-sm text-zinc-300 transition-colors hover:bg-zinc-800/40">
                    <span className="font-medium">Full active policy document</span>
                    <span className="ml-2 text-xs text-zinc-400">Click to expand</span>
                  </summary>
                  <div className="max-h-96 overflow-auto thin-scroll border-t border-zinc-800 bg-zinc-950/50 p-4">
                    <pre className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300 font-sans">{policyText}</pre>
                  </div>
                </details>
              )}
            </div>
          </div>
        )}

        {agent.timeline && agent.timeline.length > 0 && (
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Event Timeline</h3>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 space-y-4">
              {agent.timeline.map((event, index) => (
                <div key={`${event.stage}-${event.time}-${index}`} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <div className="w-3 h-3 rounded-full bg-violet-500 mt-1" />
                    {index < agent.timeline!.length - 1 && <div className="w-px flex-1 bg-zinc-800 mt-2" />}
                  </div>
                  <div className="flex-1 pb-3">
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-sm text-white">{event.label}</p>
                      <span className="text-xs text-zinc-300">{event.time}</span>
                    </div>
                    {event.note && <p className="text-xs text-zinc-300 mt-1 leading-relaxed">{event.note}</p>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-3">Conversation Transcript</h3>
          <div className="p-4 rounded-xl bg-zinc-800/50 min-h-[120px]">
            {agent.transcript ? (
              <p className="text-sm text-zinc-300 leading-relaxed">{agent.transcript}</p>
            ) : (
              <p className="text-sm text-zinc-400 italic">Waiting for conversation...</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
