'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { Header } from '@/components/header'
import { AgentCard } from '@/components/agent-card'
import { AgentDetail } from '@/components/agent-detail'
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle, Upload } from 'lucide-react'
import { API_BASE, WS_URL } from '@/lib/api'

type ClaimStatus = 'active' | 'processing' | 'complete' | 'escalated' | 'cancelled' | 'archived'
type CoverageStatus = 'covered' | 'not-covered' | 'pending'
type ClaimField = 'name' | 'location' | 'vehicle' | 'issue_type' | 'urgency'
type QueueFilter = 'all' | 'pending' | 'completed' | 'archived'

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

interface LiveClaim {
  id: string
  createdAt?: string
  callerName: string
  callerPhone: string
  duration: string
  status: ClaimStatus
  claimType: string
  location: string
  vehicle: string
  urgency: string
  confidence: number
  coverageStatus: CoverageStatus
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

interface PersistedClaim {
  id: string
  created_at: string
  caller_name: string | null
  location: string | null
  vehicle: string | null
  urgency: string | null
  issue_type: string | null
  transcript: string | null
  conversation_transcript?: string | null
  damage_type: string | null
  damage_severity: string | null
  damage_reason: string | null
  damage_ambiguous: number | null
  covered: number | null
  confidence: number | null
  reasoning: string | null
  policy_chunks?: string | null
  escalated: number
  action_type: string | null
  garage_name: string | null
  garage_eta: number | null
  taxi_name: string | null
  taxi_eta: number | null
  rental_name: string | null
  rental_address: string | null
  sms_text: string | null
  summary: string | null
  stage: string | null
  status: string
}

const FALLBACK_AGENTS: LiveClaim[] = [
  {
    id: 'mock-1',
    callerName: 'Sarah Chen',
    callerPhone: '+44 7700 900123',
    duration: '2:34',
    status: 'complete',
    claimType: 'Flat Tyre',
    location: 'M25, Junction 12',
    vehicle: '2022 Honda Civic',
    urgency: 'High',
    confidence: 92,
    coverageStatus: 'covered',
    reasoning: 'Flat tyre covered under roadside assistance. Repair truck dispatched.',
    transcript: 'I have a flat tyre on the motorway and no spare. Need help urgently.',
    notificationSent: true,
    stage: 'complete',
    schema: {
      name: 'Sarah Chen',
      location: 'M25, Junction 12',
      vehicle: '2022 Honda Civic',
      issue_type: 'flat_tyre',
      urgency: 'high',
    },
    intakeReview: { ready: true, gaps: [], nextField: null, nextReason: null },
    damageType: 'flat_tyre',
    damageSeverity: 'minor',
    policyChunks: ['Roadside assistance includes tyre-related incidents when the vehicle is immobilized.'],
    action: {
      type: 'repair_truck',
      garage: { name: 'Central Auto Recovery', eta_minutes: 28, distance_km: 4.6 },
      taxi: { name: 'CityRide London', eta_minutes: 12, pickup: 'M25, Junction 12' },
    },
    callSummary: 'Caller reported a flat tyre with no spare on the motorway. Help was confirmed and roadside assistance arranged.',
    timeline: [
      { stage: 'intake', label: 'Voice Intake', time: '09:42 AM', note: 'Captured caller details and breakdown context.' },
      { stage: 'coverage', label: 'Coverage Review', time: '09:43 AM', note: 'Coverage confirmed from roadside assistance policy.' },
      { stage: 'decision', label: 'Assistance Planning', time: '09:43 AM', note: 'Repair truck selected with taxi support.' },
      { stage: 'complete', label: 'Customer Updated', time: '09:44 AM', note: 'SMS card prepared for the customer.' },
    ],
  },
  {
    id: 'mock-2',
    callerName: 'James Okafor',
    callerPhone: '+44 7700 900456',
    duration: '1:47',
    status: 'escalated',
    claimType: 'Accident',
    location: 'Canary Wharf, E14',
    vehicle: '2021 BMW 3 Series',
    urgency: 'Critical',
    confidence: 38,
    coverageStatus: 'pending',
    reasoning: 'Ambiguous liability — other party uninsured. Senior adjuster required.',
    transcript: 'I was hit by a driver who has no insurance. My car is badly damaged.',
    notificationSent: false,
    stage: 'escalation',
    schema: {
      name: 'James Okafor',
      location: 'Canary Wharf, E14',
      vehicle: '2021 BMW 3 Series',
      issue_type: 'accident',
      urgency: 'critical',
    },
    intakeReview: { ready: true, gaps: [], nextField: null, nextReason: null },
    damageType: 'accident',
    damageSeverity: 'severe',
    policyChunks: ['Uninsured third-party incidents require manual review before roadside coverage is confirmed.'],
    timeline: [
      { stage: 'intake', label: 'Voice Intake', time: '10:18 AM', note: 'Accident details captured from the caller.' },
      { stage: 'coverage', label: 'Coverage Review', time: '10:19 AM', note: 'Low confidence due to uninsured third party.' },
      { stage: 'escalation', label: 'Human Review Needed', time: '10:19 AM', note: 'Waiting for claims handler decision.' },
    ],
  },
]


const stageLabel: Record<string, string> = {
  intake: 'Voice Intake',
  call_ended: 'Reviewing Claim',
  damage_assessment: 'Damage Assessment',
  rag: 'Policy Retrieval',
  coverage: 'Coverage Review',
  escalation: 'Human Review',
  decision: 'Assistance Planning',
  complete: 'Customer Updated',
  cancelled: 'Cancelled',
  archived: 'Archived',
}

const queueConfig = [
  { key: 'escalated', title: 'Needs Review', helper: 'Claims waiting for a human decision.' },
  { key: 'active', title: 'In Flight', helper: 'Live intake and post-call pipeline activity.' },
  { key: 'complete', title: 'Completed', helper: 'Claims that have already been updated.' },
  { key: 'archived', title: 'Archived', helper: 'Claims set aside by an agent.' },
] as const

const queueFilterConfig: Array<{ key: QueueFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'completed', label: 'Completed' },
  { key: 'archived', label: 'Archived' },
]

function formatLabel(value: string | null | undefined) {
  if (!value) return ''
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function parseBackendDate(value?: string) {
  if (!value) return null
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatEventTime(value?: string) {
  if (!value) return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const date = parseBackendDate(value)
  return !date
    ? value
    : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatClaimTimestamp(value?: string) {
  const date = parseBackendDate(value)
  if (!date) return 'Saved claim'
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (isToday) return `Today, ${time}`
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + `, ${time}`
}

function schemaToAgent(schema: ClaimSchema) {
  return {
    callerName: schema?.name || 'Live Caller',
    location: schema?.location || '',
    vehicle: schema?.vehicle || '',
    claimType: formatLabel(schema?.issue_type) || '',
    urgency: formatLabel(schema?.urgency) || '',
  }
}

function coverageToAgent(cov: Record<string, unknown>) {
  return {
    coverageStatus: cov?.covered === true ? 'covered' as const : cov?.covered === false ? 'not-covered' as const : 'pending' as const,
    confidence: cov?.confidence ? Math.round((cov.confidence as number) * 100) : 0,
    reasoning: (cov?.reasoning as string) || '',
  }
}

function parsePolicyChunks(value: string | null | undefined) {
  if (!value) return []
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function persistedStatusToAgent(claim: PersistedClaim): ClaimStatus {
  if (claim.status === 'archived' || claim.stage === 'archived') return 'archived'
  if (claim.status === 'cancelled' || claim.stage === 'cancelled') return 'cancelled'
  if (claim.stage === 'escalation' || (claim.status === 'reviewing' && claim.escalated === 1 && claim.covered == null)) {
    return 'escalated'
  }
  if (claim.status === 'active') return 'active'
  if (claim.status === 'reviewing' || claim.status === 'processing') return 'processing'
  return 'complete'
}

function matchesQueueFilter(agent: LiveClaim, filter: QueueFilter) {
  if (filter === 'pending') {
    return agent.status !== 'complete' && agent.status !== 'cancelled' && agent.status !== 'archived'
  }
  if (filter === 'completed') {
    return agent.status === 'complete' || agent.status === 'cancelled'
  }
  if (filter === 'archived') {
    return agent.status === 'archived'
  }
  return true
}

function buildTimelineFromPersisted(claim: PersistedClaim): TimelineEvent[] {
  const events: TimelineEvent[] = []
  const ts = formatClaimTimestamp(claim.created_at)
  events.push({ stage: 'intake', label: 'Voice Intake', time: ts, note: claim.caller_name ? `Captured details for ${claim.caller_name}.` : 'Caller details captured.' })
  if (claim.transcript || claim.conversation_transcript) {
    events.push({ stage: 'call_ended', label: 'Call Ended', time: ts, note: 'Caller hung up, post-call pipeline started.' })
  }
  if (claim.damage_type) {
    const sev = claim.damage_severity ? ` (${claim.damage_severity})` : ''
    events.push({ stage: 'damage_assessment', label: 'Damage Assessed', time: ts, note: `Type: ${claim.damage_type}${sev}.` })
  }
  if (parsePolicyChunks(claim.policy_chunks).length > 0) {
    events.push({ stage: 'rag', label: 'Policy Retrieved', time: ts, note: 'Relevant policy sections fetched.' })
  }
  if (claim.covered != null || claim.confidence != null) {
    const conf = claim.confidence != null ? ` (${Math.round(claim.confidence * 100)}% confidence)` : ''
    const verdict = claim.covered === 1 ? 'Covered' : claim.covered === 0 ? 'Not covered' : 'Pending'
    events.push({ stage: 'coverage', label: 'Coverage Decision', time: ts, note: `${verdict}${conf}.` })
  }
  if (claim.escalated === 1) {
    events.push({ stage: 'escalation', label: 'Escalated for Review', time: ts, note: 'Routed to human reviewer.' })
  }
  if (claim.action_type) {
    events.push({ stage: 'decision', label: 'Action Selected', time: ts, note: `Dispatch: ${claim.action_type}.` })
  }
  if (claim.sms_text) {
    events.push({ stage: 'complete', label: 'Customer Notified', time: ts, note: 'Outcome message prepared.' })
  }
  if (claim.status === 'cancelled') {
    events.push({ stage: 'cancelled', label: 'Claim Cancelled', time: ts, note: 'Auto-cancelled or abandoned.' })
  }
  if (claim.status === 'archived') {
    events.push({ stage: 'archived', label: 'Claim Archived', time: ts, note: 'Manually archived by reviewer.' })
  }
  return events
}

function mapPersistedClaim(claim: PersistedClaim): LiveClaim {
  return {
    id: claim.id,
    createdAt: claim.created_at,
    callerName: claim.caller_name || 'Unknown Caller',
    callerPhone: `Claim ${claim.id.slice(0, 8)}`,
    duration: formatClaimTimestamp(claim.created_at),
    status: persistedStatusToAgent(claim),
    claimType: formatLabel(claim.issue_type) || 'Claim',
    location: claim.location || '',
    vehicle: claim.vehicle || '',
    urgency: formatLabel(claim.urgency) || '',
    confidence: claim.confidence != null ? Math.round(claim.confidence * 100) : 0,
    coverageStatus:
      claim.covered === 1 ? 'covered' :
      claim.covered === 0 ? 'not-covered' :
      'pending',
    reasoning: claim.reasoning || 'Awaiting review.',
    policyChunks: parsePolicyChunks(claim.policy_chunks),
    transcript: claim.conversation_transcript || claim.transcript || '',
    notificationSent: Boolean(claim.sms_text),
    stage: claim.stage || undefined,
    schema: {
      name: claim.caller_name,
      location: claim.location,
      vehicle: claim.vehicle,
      issue_type: claim.issue_type,
      urgency: claim.urgency,
    },
    damageType: claim.damage_type || undefined,
    damageSeverity: claim.damage_severity || undefined,
    damageReason: claim.damage_reason || undefined,
    damageAmbiguous: claim.damage_ambiguous === 1 ? true : claim.damage_ambiguous === 0 ? false : undefined,
    action: claim.covered === 1 && claim.action_type ? {
      type: claim.action_type,
      garage: claim.garage_name ? { name: claim.garage_name, eta_minutes: claim.garage_eta || 0 } : undefined,
      taxi: claim.taxi_name ? { name: claim.taxi_name, eta_minutes: claim.taxi_eta || 0, pickup: claim.location || 'Claim location' } : undefined,
      rental: claim.rental_name ? { name: claim.rental_name, address: claim.rental_address || 'Rental address pending' } : null,
    } : undefined,
    callSummary: claim.summary || undefined,
    timeline: buildTimelineFromPersisted(claim),
  }
}

function mergeFetchedClaims(current: LiveClaim[], incoming: LiveClaim[]) {
  const byId = new Map<string, LiveClaim>()
  for (const agent of current) {
    byId.set(agent.id, agent)
  }
  for (const agent of incoming) {
    const existing = byId.get(agent.id)
    byId.set(agent.id, existing ? {
      ...existing,
      ...agent,
      id: agent.id,
      timeline: existing.timeline || agent.timeline,
    } : agent)
  }
  const statusOrder: Record<ClaimStatus, number> = { escalated: 0, active: 1, processing: 2, complete: 3, cancelled: 4, archived: 5 }
  return Array.from(byId.values()).sort((left, right) => {
    if (statusOrder[left.status] !== statusOrder[right.status]) {
      return statusOrder[left.status] - statusOrder[right.status]
    }
    return (parseBackendDate(right.createdAt)?.getTime() || 0) - (parseBackendDate(left.createdAt)?.getTime() || 0)
  })
}

function buildTimelineNote(state: Record<string, any>) {
  switch (state.stage) {
    case 'intake':
      return state.intake_review?.nextReason || state.follow_up || 'Collecting and validating claim details.'
    case 'call_ended':
      return state.message || 'Voice intake is complete. Review pipeline is running.'
    case 'damage_assessment':
      if (state.damage?.type) {
        return `${formatLabel(state.damage.type)} assessed as ${state.damage.severity || 'unknown'} severity.`
      }
      return 'Assessing described damage from the call.'
    case 'rag':
      return state.policy_chunks?.length ? `${state.policy_chunks.length} policy sections retrieved.` : 'Retrieving policy evidence.'
    case 'coverage':
      return state.coverage?.reasoning || 'Coverage model is evaluating the retrieved policy context.'
    case 'escalation':
      return state.intake_review?.nextReason || state.coverage?.reasoning || 'Human review required.'
    case 'decision':
      if (state.action?.garage?.name) {
        return `${formatLabel(state.action.type)} proposed via ${state.action.garage.name}.`
      }
      return 'Selecting next best assistance action.'
    case 'complete':
      return state.summary || state.sms_text || 'Customer notification is ready.'
    default:
      return undefined
  }
}

function buildTimelineEvent(state: Record<string, any>): TimelineEvent | null {
  if (!state.stage) return null
  return {
    stage: state.stage,
    label: stageLabel[state.stage] || formatLabel(state.stage),
    time: formatEventTime(state.event_time),
    note: buildTimelineNote(state),
  }
}

function mergeTimeline(existing: TimelineEvent[] = [], nextEvent: TimelineEvent | null) {
  if (!nextEvent) return existing
  const lastEvent = existing[existing.length - 1]
  if (lastEvent?.stage === nextEvent.stage) {
    return [...existing.slice(0, -1), { ...lastEvent, ...nextEvent }]
  }
  return [...existing, nextEvent]
}

export default function Home() {
  const [agents, setAgents] = useState<LiveClaim[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [wsConnected, setWsConnected] = useState(false)
  const [escalationPending, setEscalationPending] = useState(false)
  const [escalationCoverage, setEscalationCoverage] = useState<{ reasoning: string; confidence: number; nextReason?: string | null } | null>(null)
  const [escalationClaimId, setEscalationClaimId] = useState<string | null>(null)
  const [reviewNotes, setReviewNotes] = useState('')
  const [reviewSubmitting, setReviewSubmitting] = useState(false)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [policyText, setPolicyText] = useState('')
  const wsRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)
  const liveActiveRef = useRef(false)
  const liveClaimIdRef = useRef<string | null>(null)
  const [liveDuration, setLiveDuration] = useState(0)

  const selectedAgent = agents.find((a) => a.id === selectedId)
  const activeCount = agents.filter((a) => a.status === 'active' || a.status === 'processing').length
  const pendingCount = agents.filter((a) => a.status !== 'complete' && a.status !== 'cancelled' && a.status !== 'archived').length
  const completedCount = agents.filter((a) => a.status === 'complete' || a.status === 'cancelled').length
  const archivedCount = agents.filter((a) => a.status === 'archived').length

  const refreshClaims = useCallback(async (selectFirst = false, silent = false) => {
    if (!silent) setIsRefreshing(true)
    try {
      const response = await fetch(`${API_BASE}/claims`)
      const data: PersistedClaim[] = await response.json()
      const persisted = data.map(mapPersistedClaim)
      setAgents((prev) => mergeFetchedClaims(prev, persisted.length > 0 ? persisted : FALLBACK_AGENTS))
      if (selectFirst) {
        setSelectedId((current) => current ?? persisted[0]?.id ?? FALLBACK_AGENTS[0]?.id ?? null)
      }
    } catch {
      setAgents((prev) => mergeFetchedClaims(prev, FALLBACK_AGENTS))
      if (selectFirst) {
        setSelectedId((current) => current ?? FALLBACK_AGENTS[0]?.id ?? null)
      }
    } finally {
      if (!silent) setIsRefreshing(false)
    }
  }, [])

  const upsertLiveAgent = useCallback((claimId: string, updates: Partial<LiveClaim>, nextEvent: TimelineEvent | null = null) => {
    setAgents((prev) => {
      const existing = prev.find((a) => a.id === claimId)
      const merged: LiveClaim = existing
        ? {
            ...existing,
            ...updates,
            id: claimId,
            createdAt: existing.createdAt || updates.createdAt,
            timeline: mergeTimeline(existing.timeline, nextEvent),
          }
        : {
            id: claimId,
            callerName: 'Live Caller',
            callerPhone: `Claim ${claimId.slice(0, 8)}`,
            duration: '0:00',
            status: 'active',
            claimType: '',
            location: '',
            vehicle: '',
            urgency: '',
            confidence: 0,
            coverageStatus: 'pending',
            reasoning: 'Waiting for claim information...',
            transcript: '',
            notificationSent: false,
            timeline: mergeTimeline([], nextEvent),
            ...updates,
          }
      return [merged, ...prev.filter((a) => a.id !== claimId)]
    })
    setSelectedId((current) => current ?? claimId)
  }, [])

  useEffect(() => {
    refreshClaims(true)
  }, [refreshClaims])

  useEffect(() => {
    const fetchPolicy = async () => {
      try {
        const response = await fetch(`${API_BASE}/policy`)
        const data: { text?: string } = await response.json()
        setPolicyText(data.text || '')
      } catch {
        setPolicyText('')
      }
    }
    fetchPolicy()
  }, [])

  useEffect(() => {
    const interval = setInterval(() => {
      refreshClaims(false, true)
    }, 5000)
    return () => clearInterval(interval)
  }, [refreshClaims])

  const handleWsMessage = useCallback((event: MessageEvent) => {
    const state = JSON.parse(event.data)
    if (state.remove_from_dashboard && state.claim_id) {
      setAgents((prev) => prev.filter((agent) => agent.id !== state.claim_id))
      setSelectedId((current) => current === state.claim_id ? null : current)
      return
    }
    const timelineEvent = buildTimelineEvent(state)
    const claimId = String(state.claim_id || `live-${Date.now()}`)

    if (state.stage === 'intake' && !liveActiveRef.current) {
      liveActiveRef.current = true
      liveClaimIdRef.current = claimId
      setLiveDuration(0)
      if (timerRef.current) clearInterval(timerRef.current)
      timerRef.current = setInterval(() => setLiveDuration((d) => d + 1), 1000)
    }

    const baseUpdates: Partial<LiveClaim> = {
      transcript: state.conversation_transcript || state.transcript || '',
      stage: state.stage,
      createdAt: state.event_time || undefined,
      schema: state.schema || undefined,
      intakeReview: state.intake_review || undefined,
      callbackContext: state.callback_context || undefined,
      callerPhone: `Claim ${claimId.slice(0, 8)}`,
      ...(state.schema ? schemaToAgent(state.schema) : {}),
      ...(state.damage ? {
        damageType: state.damage.type,
        damageSeverity: state.damage.severity,
        damageReason: state.damage.reason,
        damageAmbiguous: state.damage.ambiguous,
      } : {}),
      ...(state.coverage ? coverageToAgent(state.coverage) : {}),
      ...(state.policy_chunks ? { policyChunks: state.policy_chunks } : {}),
      ...(state.action ? { action: state.action } : {}),
      ...(state.summary ? { callSummary: state.summary } : {}),
    }

    switch (state.stage) {
      case 'intake':
        upsertLiveAgent(claimId, { ...baseUpdates, status: 'active' }, timelineEvent)
        break
      case 'call_ended':
      case 'damage_assessment':
      case 'rag':
      case 'coverage':
      case 'decision':
        upsertLiveAgent(claimId, { ...baseUpdates, status: 'processing' }, timelineEvent)
        break
      case 'escalation':
        upsertLiveAgent(claimId, { ...baseUpdates, status: 'escalated' }, timelineEvent)
        setEscalationPending(true)
        setEscalationClaimId(claimId)
        setSelectedId(claimId)
        setEscalationCoverage({
          reasoning: state.coverage?.reasoning || '',
          confidence: state.coverage?.confidence ? Math.round(state.coverage.confidence * 100) : 0,
          nextReason: state.intake_review?.nextReason || null,
        })
        break
      case 'complete':
        upsertLiveAgent(
          claimId,
          {
            ...baseUpdates,
            status: 'complete',
            notificationSent: true,
          },
          timelineEvent,
        )
        setEscalationPending(false)
        setEscalationClaimId((current) => current === claimId ? null : current)
        liveActiveRef.current = false
        if (liveClaimIdRef.current === claimId) {
          liveClaimIdRef.current = null
        }
        if (timerRef.current) clearInterval(timerRef.current)
        break
    }
  }, [upsertLiveAgent])

  useEffect(() => {
    const ws = new WebSocket(WS_URL)
    ws.onopen = () => {
      setWsConnected(true)
      ws.send(JSON.stringify({ type: 'subscribe_dashboard' }))
    }
    ws.onmessage = handleWsMessage
    ws.onclose = () => {
      setWsConnected(false)
      liveActiveRef.current = false
      liveClaimIdRef.current = null
      if (timerRef.current) clearInterval(timerRef.current)
    }
    wsRef.current = ws
    return () => {
      ws.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [handleWsMessage])

  useEffect(() => {
    const m = Math.floor(liveDuration / 60)
    const s = String(liveDuration % 60).padStart(2, '0')
    setAgents((prev) =>
      prev.map((a) => a.id === liveClaimIdRef.current ? { ...a, duration: `${m}:${s}` } : a)
    )
  }, [liveDuration])

  useEffect(() => {
    const visibleAgents = agents.filter((agent) => matchesQueueFilter(agent, queueFilter))
    if (visibleAgents.length === 0) {
      setSelectedId(null)
      return
    }
    if (!selectedId || !visibleAgents.some((agent) => agent.id === selectedId)) {
      setSelectedId(visibleAgents[0].id)
    }
  }, [agents, queueFilter, selectedId])

  const [policyUploadStatus, setPolicyUploadStatus] = useState<'idle' | 'uploading' | 'ok' | 'error'>('idle')
  const policyFileRef = useRef<HTMLInputElement>(null)

  const handlePolicyUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setPolicyUploadStatus('uploading')
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/policy/upload`, { method: 'POST', body: fd })
      setPolicyUploadStatus(res.ok ? 'ok' : 'error')
      if (res.ok) {
        const policyRes = await fetch(`${API_BASE}/policy`)
        const data: { text?: string } = await policyRes.json()
        setPolicyText(data.text || '')
      }
    } catch {
      setPolicyUploadStatus('error')
    }
    setTimeout(() => setPolicyUploadStatus('idle'), 3000)
    if (policyFileRef.current) policyFileRef.current.value = ''
  }

  const archiveClaim = async (claimId: string) => {
    try {
      const res = await fetch(`${API_BASE}/claims/${claimId}/archive`, { method: 'POST' })
      if (!res.ok) {
        console.error('Archive failed', res.status)
        return
      }
      setAgents((prev) => prev.map((a) => a.id === claimId ? { ...a, status: 'archived' as ClaimStatus } : a))
    } catch (e) {
      console.error('Archive network error', e)
    }
  }

  const sendHumanOverride = async (approved: boolean, override?: 'covered' | 'not_covered', claimId?: string | null, notes?: string) => {
    setReviewError(null)
    setReviewSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/escalation/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approved,
          override: override ?? null,
          claim_id: claimId ?? escalationClaimId ?? selectedId ?? null,
          notes: notes && notes.trim() ? notes.trim() : null,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setReviewError(body?.detail || `Resolve failed (${res.status})`)
        return
      }
      setReviewNotes('')
      setEscalationPending(false)
      setEscalationClaimId(null)
      setEscalationCoverage(null)
      refreshClaims(false, true)
    } catch (e) {
      setReviewError('Network error. Backend unreachable.')
    } finally {
      setReviewSubmitting(false)
    }
  }

  const queueSections = queueConfig.map((section) => {
    if (section.key === 'escalated') {
      return { ...section, items: agents.filter((agent) => agent.status === 'escalated' && matchesQueueFilter(agent, queueFilter)) }
    }
    if (section.key === 'active') {
      return { ...section, items: agents.filter((agent) => (agent.status === 'active' || agent.status === 'processing') && matchesQueueFilter(agent, queueFilter)) }
    }
    if (section.key === 'archived') {
      return { ...section, items: agents.filter((agent) => agent.status === 'archived' && matchesQueueFilter(agent, queueFilter)) }
    }
    return { ...section, items: agents.filter((agent) => (agent.status === 'complete' || agent.status === 'cancelled') && matchesQueueFilter(agent, queueFilter)) }
  }).filter((section) => section.items.length > 0)

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0a] text-white">
      <Header activeCount={activeCount} />

      {escalationPending && (
        <div className="mx-4 mt-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-start gap-4">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-medium text-amber-400 mb-1">Escalation Required</p>
            {escalationCoverage && (
              <p className="text-xs text-zinc-400 mb-1">
                Confidence: {escalationCoverage.confidence}% — {escalationCoverage.reasoning}
              </p>
            )}
            {escalationCoverage?.nextReason && (
              <p className="text-xs text-zinc-500 mb-1">
                Intake gap: {escalationCoverage.nextReason}
              </p>
            )}
            <p className="text-xs text-zinc-500">Confirm or override the coverage decision before the customer is updated.</p>
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => sendHumanOverride(true, 'covered')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-colors"
            >
              <CheckCircle2 className="w-3.5 h-3.5" /> Approve
            </button>
            <button
              onClick={() => sendHumanOverride(false, 'not_covered')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-700 hover:bg-red-600 rounded-lg transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" /> Decline
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        <div className="w-[520px] border-r border-zinc-800/50 overflow-auto thin-scroll p-4">
          <div className="flex items-center justify-between mb-4 px-1">
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-500' : 'bg-zinc-600'}`} />
              <span className="text-xs text-zinc-300">{wsConnected ? 'Live feed connected' : 'Waiting for connection...'}</span>
            </div>
            <div className="flex items-center gap-2">
              <label className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs cursor-pointer transition-colors ${
                policyUploadStatus === 'ok' ? 'bg-emerald-700/30 text-emerald-400' :
                policyUploadStatus === 'error' ? 'bg-red-700/30 text-red-400' :
                policyUploadStatus === 'uploading' ? 'bg-zinc-700 text-zinc-400 cursor-wait' :
                'bg-zinc-800 hover:bg-zinc-700 text-zinc-400'
              }`}>
                <Upload className="w-3 h-3" />
                {policyUploadStatus === 'ok' ? 'Uploaded' : policyUploadStatus === 'error' ? 'Failed' : policyUploadStatus === 'uploading' ? 'Uploading...' : 'Upload Policy'}
                <input ref={policyFileRef} type="file" accept=".txt" className="hidden" onChange={handlePolicyUpload} disabled={policyUploadStatus === 'uploading'} />
              </label>
              <button
                onClick={() => refreshClaims(false)}
                disabled={isRefreshing}
                className="flex items-center justify-center rounded-lg bg-zinc-800 p-1.5 text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-200 disabled:cursor-wait disabled:opacity-50"
                title="Refresh claims"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          <div className="mb-5 px-1">
            <div className="inline-flex rounded-xl border border-zinc-800 bg-zinc-900/70 p-1">
              {queueFilterConfig.map((option) => {
                const count = option.key === 'all' ? agents.length : option.key === 'pending' ? pendingCount : option.key === 'archived' ? archivedCount : completedCount
                const isActive = queueFilter === option.key
                return (
                  <button
                    key={option.key}
                    onClick={() => setQueueFilter(option.key)}
                    className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${
                      isActive ? 'bg-violet-600 text-white' : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
                    }`}
                  >
                    {option.label} <span className="text-[10px] opacity-80">{count}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-5">
            {queueSections.length === 0 ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-10 text-center">
                <p className="text-sm text-zinc-400">No claims in this view.</p>
                <p className="text-xs text-zinc-600 mt-1">
                  {queueFilter === 'pending' ? 'Pending claims will appear here.' : queueFilter === 'completed' ? 'Completed claims will appear here.' : 'New claims will appear here as they come in.'}
                </p>
              </div>
            ) : queueSections.map((section) => (
              <section key={section.key}>
                <div className="mb-2 px-1">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium text-white">{section.title}</h2>
                    <span className="text-[11px] text-zinc-400">{section.items.length}</span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-0.5">{section.helper}</p>
                </div>
                <div className="grid gap-3">
                  {section.items.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      id={agent.id}
                      callerName={agent.callerName}
                      callerPhone={agent.callerPhone}
                      duration={agent.duration}
                      status={agent.status}
                      claimType={agent.claimType}
                      location={agent.location}
                      confidence={agent.confidence}
                      coverageStatus={agent.coverageStatus}
                      transcript={agent.transcript}
                      stageLabel={agent.stage ? (stageLabel[agent.stage] || formatLabel(agent.stage)) : undefined}
                      nextReason={agent.intakeReview?.nextReason || undefined}
                      hasCallbackContext={Boolean(agent.callbackContext)}
                      onSelect={() => setSelectedId(agent.id)}
                      isSelected={selectedId === agent.id}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>

        <div className="flex-1 min-w-0 overflow-auto thin-scroll">
          {selectedAgent ? (
            <AgentDetail
              agent={selectedAgent}
              policyText={policyText}
              canReview={selectedAgent.status === 'escalated' && !selectedAgent.id.startsWith('mock-')}
              onApprove={(notes) => sendHumanOverride(true, 'covered', selectedAgent.id, notes)}
              onDecline={(notes) => sendHumanOverride(false, 'not_covered', selectedAgent.id, notes)}
              onArchive={() => archiveClaim(selectedAgent.id)}
              canArchive={selectedAgent.status === 'active' || selectedAgent.status === 'processing' || selectedAgent.status === 'escalated'}
              reviewSubmitting={reviewSubmitting}
              reviewError={reviewError}
            />
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-zinc-600">Select a claim to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
