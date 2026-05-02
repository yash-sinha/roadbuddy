'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, CheckCircle2, XCircle, Clock, AlertTriangle,
  Mic, FileText, Car, MapPin, Wrench, Phone, ChevronDown, ChevronUp,
} from 'lucide-react'
import { API_BASE, WS_URL } from '@/lib/api'

interface Claim {
  id: string
  created_at: string
  caller_name: string | null
  location: string | null
  vehicle: string | null
  issue_type: string | null
  urgency: string | null
  transcript: string | null
  conversation_transcript?: string | null
  damage_type: string | null
  damage_severity: string | null
  covered: number | null
  confidence: number | null
  reasoning: string | null
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

const ISSUE_LABELS: Record<string, string> = {
  flat_tyre: 'Flat Tyre',
  accident: 'Accident',
  battery_failure: 'Battery Failure',
  battery: 'Battery Failure',
  engine_failure: 'Engine Failure',
  cosmetic_damage: 'Cosmetic Damage',
  other: 'Other',
}

const CUSTOMER_NAME_KEY = 'scale_customer_name'
const CUSTOMER_KEY_KEY = 'scale_customer_key'

function rememberCustomerName(name: string | null | undefined) {
  if (typeof window === 'undefined') return
  const cleaned = (name || '').trim()
  const firstName = cleaned.split(/\s+/)[0]
  if (!cleaned || !firstName) return
  window.localStorage.setItem(CUSTOMER_NAME_KEY, cleaned)
  window.localStorage.setItem(CUSTOMER_KEY_KEY, firstName)
}

function claimTitle(claim: Claim): string {
  const type = ISSUE_LABELS[claim.issue_type || ''] || claim.issue_type || 'Claim'
  if (!claim.location) return type
  const shortLoc = claim.location.split(',')[0]
  return `${type} — ${shortLoc}`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

interface PipelineStep {
  key: string
  label: string
  description: (c: Claim) => string | null
  show: (c: Claim) => boolean
  isEscalation?: boolean
}

const PIPELINE_STEPS: PipelineStep[] = [
  {
    key: 'intake',
    label: 'Voice Intake',
    description: (c) => c.caller_name ? `Details collected from ${c.caller_name}` : 'Claim details collected',
    show: () => true,
  },
  {
    key: 'damage',
    label: 'Damage Assessment',
    description: (c) => c.damage_type
      ? `${(c.damage_type || '').replace(/_/g, ' ')} — ${c.damage_severity}`
      : null,
    show: () => true,
  },
  {
    key: 'rag',
    label: 'Policy Retrieval',
    description: () => 'Relevant policy sections retrieved',
    show: () => true,
  },
  {
    key: 'coverage',
    label: 'Coverage Review',
    description: (c) => c.covered === 1
      ? 'Covered under your roadside assistance policy.'
      : c.covered === 0
      ? 'Not covered under your current policy.'
      : 'Reviewing your cover.',
    show: () => true,
  },
  {
    key: 'escalation',
    label: 'Human Review',
    description: () => 'A claims handler reviewed the decision',
    show: (c) => c.escalated === 1,
    isEscalation: true,
  },
  {
    key: 'decision',
    label: 'Assistance Planning',
    description: (c) => c.action_type
      ? `${c.action_type === 'tow_truck' ? 'Tow truck' : 'Repair truck'} dispatched${c.garage_name ? ` from ${c.garage_name}` : ''}`
      : 'Decision processed',
    show: (c) => c.covered === 1,
  },
  {
    key: 'complete',
    label: 'Customer Update',
    description: (c) => c.covered === 1
      ? 'Assistance arranged and confirmation sent.'
      : 'Outcome shared. A handler will follow up.',
    show: () => true,
  },
]

function PipelineTimeline({ claim }: { claim: Claim }) {
  const steps = PIPELINE_STEPS.filter((s) => s.show(claim))
  const progressByStep: Record<string, number> = {
    intake: 0,
    damage: 1,
    rag: 2,
    coverage: 3,
    escalation: 4,
    decision: 5,
    complete: 6,
  }
  const progressByStage: Record<string, number> = {
    intake: 0,
    call_ended: 0,
    damage_assessment: 1,
    rag: 2,
    coverage: 3,
    escalation: 4,
    decision: 5,
    complete: 6,
  }
  const isComplete = claim.status === 'complete'
  const currentProgress = isComplete ? 6 : (progressByStage[claim.stage || ''] ?? 0)

  return (
    <div className="flex flex-col">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1
        const desc = step.description(claim)
        const stepProgress = progressByStep[step.key]
        const isDone = isComplete ? stepProgress <= currentProgress : stepProgress < currentProgress
        const isCurrent = !isComplete && stepProgress === currentProgress

        return (
          <div key={step.key} className="flex gap-4">
            {/* Timeline line + dot */}
            <div className="flex flex-col items-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 ${
                step.isEscalation && (isDone || isCurrent)
                  ? 'bg-amber-500/10 border border-amber-500/40'
                  : isDone
                  ? 'bg-emerald-500/10 border border-emerald-500/40'
                  : isCurrent
                  ? 'bg-violet-500/10 border border-violet-500/40'
                  : 'bg-zinc-800 border border-zinc-700'
              }`}>
                {step.isEscalation && (isDone || isCurrent)
                  ? <AlertTriangle className="w-4 h-4 text-amber-400" />
                  : isDone
                  ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  : isCurrent
                  ? <Clock className="w-4 h-4 text-violet-400" />
                  : <Clock className="w-4 h-4 text-zinc-600" />
                }
              </div>
              {!isLast && (
                <div className={`w-px flex-1 my-1 ${isDone ? 'bg-emerald-500/20' : isCurrent ? 'bg-violet-500/20' : 'bg-zinc-800'}`} />
              )}
            </div>

            {/* Content */}
            <div className={`pb-5 ${isLast ? '' : ''}`}>
              <p className={`text-sm font-medium ${
                step.isEscalation && (isDone || isCurrent)
                  ? 'text-amber-400'
                  : isDone
                  ? 'text-zinc-200'
                  : isCurrent
                  ? 'text-violet-300'
                  : 'text-zinc-600'
              }`}>{step.label}</p>
              {desc && <p className="text-xs text-zinc-500 mt-0.5 leading-relaxed capitalize">{desc}</p>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function ClaimDetailPage() {
  const params = useParams()
  const router = useRouter()
  const claimId = params.id as string

  const [claim, setClaim] = useState<Claim | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadClaim = useCallback((showLoading = false) => {
    if (showLoading) {
      setLoading(true)
    }
    fetch(`${API_BASE}/claims/${claimId}`)
      .then((r) => {
        if (!r.ok) { setNotFound(true); setLoading(false); return null }
        return r.json()
      })
      .then((data) => {
        if (data) {
          setClaim(data)
          rememberCustomerName(data.caller_name)
          setNotFound(false)
          setLoading(false)
        }
      })
      .catch(() => { setNotFound(true); setLoading(false) })
  }, [claimId])

  useEffect(() => {
    loadClaim(true)

    const ws = new WebSocket(WS_URL)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe_claim', claim_id: claimId }))
    }
    ws.onmessage = (event) => {
      const state = JSON.parse(event.data)
      const partialOnly = Boolean(
        state.turn_transcript_partial &&
        !state.turn_transcript &&
        !state.audio &&
        state.stage === 'intake',
      )
      if (partialOnly) return
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current)
      }
      refreshTimerRef.current = setTimeout(() => loadClaim(false), 150)
    }

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current)
        refreshTimerRef.current = null
      }
      ws.close()
    }
  }, [claimId, loadClaim])

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-zinc-700 border-t-violet-400 rounded-full animate-spin" />
      </div>
    )
  }

  if (notFound || !claim) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex flex-col items-center justify-center gap-4">
        <p className="text-zinc-500">Claim not found</p>
        <Link href="/claims" className="text-sm text-violet-400 hover:text-violet-300">← Back to claims</Link>
      </div>
    )
  }

  const isApproved = claim.covered === 1
  const isDenied = claim.covered === 0
  const isArchived = claim.status === 'archived' || claim.stage === 'archived'
  const isCancelled = claim.status === 'cancelled' || claim.stage === 'cancelled'
  const isClosed = isArchived || isCancelled
  const isProcessing = !isClosed && claim.status !== 'complete'

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <header className="h-14 px-4 flex items-center gap-3 border-b border-zinc-800/50">
        <button onClick={() => router.push('/claims')} className="p-2 rounded-lg hover:bg-zinc-800 transition-colors">
          <ArrowLeft className="w-5 h-5 text-zinc-400" />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="font-semibold text-sm truncate">{claimTitle(claim)}</h1>
          <p className="text-xs text-zinc-400">
            <span className="font-mono uppercase tracking-wider">#{claim.id.slice(0, 8)}</span>
            <span className="text-zinc-600"> · </span>
            {formatDate(claim.created_at)}
          </p>
        </div>
      </header>

      <main className="max-w-xl mx-auto px-4 py-6 space-y-6">

        {/* Status banner */}
        <div className={`rounded-xl px-5 py-4 flex items-center gap-4 ${
          isArchived ? 'bg-zinc-600/5 border border-zinc-600/20' :
          isCancelled ? 'bg-zinc-500/5 border border-zinc-500/20' :
          isProcessing ? 'bg-amber-500/5 border border-amber-500/20' :
          isApproved ? 'bg-emerald-500/5 border border-emerald-500/20' :
          'bg-red-500/5 border border-red-500/20'
        }`}>
          {isClosed
            ? <XCircle className="w-7 h-7 text-zinc-400 shrink-0" />
            : isProcessing
            ? <Clock className="w-7 h-7 text-amber-400 shrink-0" />
            : isApproved
            ? <CheckCircle2 className="w-7 h-7 text-emerald-400 shrink-0" />
            : <XCircle className="w-7 h-7 text-red-400 shrink-0" />
          }
          <div>
            <p className={`font-semibold ${
              isClosed ? 'text-zinc-300' :
              isProcessing ? 'text-amber-400' : isApproved ? 'text-emerald-400' : 'text-red-400'
            }`}>
              {isArchived ? 'Claim Archived' : isCancelled ? 'Claim Cancelled' : isProcessing ? 'Reviewing Your Claim' : isApproved ? 'Help Confirmed' : 'Not Covered'}
            </p>
            <p className="text-xs text-zinc-300 mt-0.5 leading-relaxed">
              {isArchived
                ? 'This claim has been archived by an agent.'
                : isCancelled
                ? 'Call ended before details were captured.'
                : isProcessing
                ? 'A handler is reviewing your claim. We will text you shortly with the next steps.'
                : isApproved
                ? 'Roadside assistance is on the way. Watch your phone for updates.'
                : 'This incident is not covered under your policy. A handler will follow up within 2 hours.'}
            </p>
          </div>
        </div>

        {/* Claim details */}
        <div className="grid grid-cols-2 gap-3">
          {claim.caller_name && (
            <div className="rounded-xl bg-zinc-900/50 border border-zinc-800/50 p-3">
              <p className="text-xs text-zinc-600 mb-1">Claimant</p>
              <p className="text-sm font-medium">{claim.caller_name}</p>
            </div>
          )}
          {claim.vehicle && (
            <div className="rounded-xl bg-zinc-900/50 border border-zinc-800/50 p-3 flex items-start gap-2">
              <Car className="w-4 h-4 text-zinc-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-xs text-zinc-600 mb-1">Vehicle</p>
                <p className="text-sm font-medium">{claim.vehicle}</p>
              </div>
            </div>
          )}
          {claim.location && (
            <div className="rounded-xl bg-zinc-900/50 border border-zinc-800/50 p-3 flex items-start gap-2 col-span-2">
              <MapPin className="w-4 h-4 text-zinc-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-xs text-zinc-600 mb-1">Location</p>
                <p className="text-sm font-medium">{claim.location}</p>
              </div>
            </div>
          )}
        </div>

        {/* Agent pipeline */}
        {!isClosed && (
          <div>
            <p className="text-xs uppercase tracking-wider text-zinc-600 mb-4">Claim Processing</p>
            <PipelineTimeline claim={claim} />
          </div>
        )}

        {/* Services dispatched */}
        {isApproved && (claim.garage_name || claim.taxi_name || claim.rental_name) && (
          <div>
            <p className="text-xs uppercase tracking-wider text-zinc-600 mb-3">Services Dispatched</p>
            <div className="space-y-2">
              {claim.garage_name && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-zinc-900/50 border border-zinc-800/50">
                  <Wrench className="w-4 h-4 text-violet-400 shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium">
                      {claim.action_type === 'tow_truck' ? 'Tow truck' : 'Repair truck'}
                    </p>
                    <p className="text-xs text-zinc-500">{claim.garage_name}</p>
                  </div>
                  {claim.garage_eta && (
                    <span className="text-xs text-zinc-500">ETA {claim.garage_eta} min</span>
                  )}
                </div>
              )}
              {claim.taxi_name && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-zinc-900/50 border border-zinc-800/50">
                  <Car className="w-4 h-4 text-emerald-400 shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium">Taxi</p>
                    <p className="text-xs text-zinc-500">{claim.taxi_name}</p>
                  </div>
                  {claim.taxi_eta && (
                    <span className="text-xs text-zinc-500">ETA {claim.taxi_eta} min</span>
                  )}
                </div>
              )}
              {claim.rental_name && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-zinc-900/50 border border-zinc-800/50">
                  <Car className="w-4 h-4 text-blue-400 shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium">Rental Car</p>
                    <p className="text-xs text-zinc-500">{claim.rental_name}{claim.rental_address ? ` · ${claim.rental_address}` : ''}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* SMS notification */}
        {claim.sms_text && (
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800/50 p-4">
            <p className="text-xs text-zinc-600 mb-2 flex items-center gap-1.5">
              <FileText className="w-3 h-3" /> SMS sent to your phone
            </p>
            <p className="text-sm text-zinc-400 leading-relaxed">{claim.sms_text}</p>
          </div>
        )}

        {/* Transcript */}
        {(claim.conversation_transcript || claim.transcript) && (
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800/50 overflow-hidden">
            <button
              onClick={() => setTranscriptOpen((o) => !o)}
              className="w-full px-4 py-3 flex items-center gap-2 text-left hover:bg-zinc-800/50 transition-colors"
            >
              <Mic className="w-4 h-4 text-zinc-600" />
              <span className="text-sm text-zinc-400 flex-1">Call Transcript</span>
              {transcriptOpen ? <ChevronUp className="w-4 h-4 text-zinc-600" /> : <ChevronDown className="w-4 h-4 text-zinc-600" />}
            </button>
            {transcriptOpen && (
              <div className="px-4 pb-4 border-t border-zinc-800/50">
                <p className="text-sm text-zinc-500 leading-relaxed mt-3 whitespace-pre-wrap">{claim.conversation_transcript || claim.transcript}</p>
              </div>
            )}
          </div>
        )}

        {/* Call back button */}
        {!isClosed && (
          <div className="pt-2 pb-8">
            <Link
              href={`/call?callback=${claim.id}`}
              className="flex items-center justify-center gap-2 w-full py-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 font-medium transition-colors shadow-lg shadow-emerald-900/30"
            >
              <Phone className="w-5 h-5" />
              Call About This Claim
            </Link>
            <p className="text-center text-xs text-zinc-400 mt-2">
              Starts a new call with this claim as context
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
