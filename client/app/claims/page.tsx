'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { ChevronRight, Phone, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-react'
import { API_BASE, WS_URL } from '@/lib/api'

interface Claim {
  id: string
  created_at: string
  caller_name: string | null
  location: string | null
  vehicle: string | null
  issue_type: string | null
  urgency: string | null
  covered: number | null
  summary: string | null
  stage: string | null
  status: string
  escalated: number
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

function customerKeyFromName(name: string | null | undefined): string {
  return (name || '').trim().split(/\s+/)[0] || ''
}

function claimTitle(claim: Claim): string {
  const type = ISSUE_LABELS[claim.issue_type || ''] || claim.issue_type || 'Claim'
  if (!claim.location) return type
  const shortLoc = claim.location.split(',')[0]
  return `${type} — ${shortLoc}`
}

function relativeDate(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 14) return '1 week ago'
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
  return `${Math.floor(diffDays / 30)} months ago`
}

function StatusBadge({ claim }: { claim: Claim }) {
  if (claim.status === 'archived' || claim.stage === 'archived') {
    return (
      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-zinc-600/10 text-zinc-300 border border-zinc-600/20">
        <XCircle className="w-3 h-3" /> Archived
      </span>
    )
  }
  if (claim.status === 'cancelled' || claim.stage === 'cancelled') {
    return (
      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-zinc-500/10 text-zinc-300 border border-zinc-500/20">
        <XCircle className="w-3 h-3" /> Cancelled
      </span>
    )
  }
  if (claim.status === 'reviewing' || claim.status === 'processing' || claim.status === 'active') {
    return (
      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
        <Clock className="w-3 h-3" /> Reviewing
      </span>
    )
  }
  if (claim.covered === 1) {
    return (
      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
        <CheckCircle2 className="w-3 h-3" /> Help Confirmed
      </span>
    )
  }
  if (claim.covered === 0) {
    return (
      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
        <XCircle className="w-3 h-3" /> Not Covered
      </span>
    )
  }
  return null
}

export default function ClaimsPage() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [customerName, setCustomerName] = useState<string | null>(null)
  const [identityResolved, setIdentityResolved] = useState(false)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false

    const resolveIdentity = async () => {
      const params = new URLSearchParams(window.location.search)
      const explicitName = params.get('caller_name') || params.get('caller')
      const storedName = window.localStorage.getItem(CUSTOMER_NAME_KEY)
      const storedKey = window.localStorage.getItem(CUSTOMER_KEY_KEY)
      let nextName = explicitName || storedName || storedKey || ''

      if (!customerKeyFromName(nextName)) {
        try {
          const response = await fetch(`${API_BASE}/claims/recent-customer`)
          const data = await response.json()
          nextName = data.caller_name || ''
        } catch {
          nextName = ''
        }
      }

      if (cancelled) return

      const customerKey = customerKeyFromName(nextName)
      if (customerKey) {
        setCustomerName(nextName)
        window.localStorage.setItem(CUSTOMER_NAME_KEY, nextName)
        window.localStorage.setItem(CUSTOMER_KEY_KEY, customerKey)
      }
      setIdentityResolved(true)
    }

    resolveIdentity()

    return () => {
      cancelled = true
    }
  }, [])

  const loadClaims = useCallback((showLoading = false) => {
    if (!identityResolved) return
    const customerKey = customerKeyFromName(customerName)
    if (!customerKey) {
      setClaims([])
      setError(false)
      setLoading(false)
      return
    }
    if (showLoading) {
      setLoading(true)
    }
    fetch(`${API_BASE}/claims?caller_name=${encodeURIComponent(customerKey)}`)
      .then((r) => r.json())
      .then((data) => {
        setClaims(data)
        setError(false)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })
  }, [customerName, identityResolved])

  useEffect(() => {
    if (!identityResolved) return
    loadClaims(true)

    const ws = new WebSocket(WS_URL)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe_claims' }))
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
      refreshTimerRef.current = setTimeout(() => loadClaims(false), 150)
    }

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current)
        refreshTimerRef.current = null
      }
      ws.close()
    }
  }, [identityResolved, loadClaims])

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <header className="h-14 px-6 flex items-center justify-between border-b border-zinc-800/50">
        <span className="font-semibold tracking-tight">ClaimBuddy</span>
        <Link
          href="/call"
          className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-emerald-600 hover:bg-emerald-500 text-sm font-medium transition-colors"
        >
          <Phone className="w-3.5 h-3.5" /> New Claim
        </Link>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold">My Claims</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {customerName ? `Recent claims for ${customerName}` : 'Your claim history'}
          </p>
        </div>

        {(!identityResolved || loading) && (
          <div className="flex flex-col gap-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-20 rounded-xl bg-zinc-900/50 border border-zinc-800/50 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="text-center py-16 text-zinc-600">
            <p>Could not load claims. Is the backend running?</p>
          </div>
        )}

        {!loading && !error && claims.length === 0 && (
          <div className="text-center py-16 text-zinc-600">
            <Phone className="w-10 h-10 mx-auto mb-4 opacity-30" />
            <p className="mb-4">No claims yet</p>
            <Link href="/call" className="text-sm text-violet-400 hover:text-violet-300">
              Start your first claim →
            </Link>
          </div>
        )}

        {!loading && !error && claims.length > 0 && (
          <div className="flex flex-col gap-2">
            {claims.map((claim) => (
              <Link
                key={claim.id}
                href={`/claims/${claim.id}`}
                className="group flex items-start gap-4 p-4 rounded-xl bg-zinc-900/50 border border-zinc-800/50 hover:border-zinc-700 hover:bg-zinc-900 transition-all"
              >
                {/* Status dot */}
                <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                  claim.status === 'archived' || claim.stage === 'archived' ? 'bg-zinc-600' :
                  claim.status === 'cancelled' || claim.stage === 'cancelled' ? 'bg-zinc-500' :
                  claim.status === 'reviewing' || claim.status === 'processing' || claim.status === 'active' ? 'bg-amber-400 animate-pulse' :
                  claim.covered === 1 ? 'bg-emerald-400' :
                  claim.covered === 0 ? 'bg-red-400' : 'bg-zinc-600'
                }`} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="font-medium text-sm truncate">{claimTitle(claim)}</span>
                    {claim.escalated === 1 && (
                      <span aria-label="Escalated to human agent">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                      </span>
                    )}
                  </div>
                  {claim.summary ? (
                    <p className="text-xs text-zinc-500 leading-relaxed line-clamp-2">{claim.summary}</p>
                  ) : claim.caller_name ? (
                    <p className="text-xs text-zinc-500">{claim.caller_name}</p>
                  ) : null}
                  <div className="flex items-center gap-3 mt-2">
                    <StatusBadge claim={claim} />
                    <span className="text-xs text-zinc-600">{relativeDate(claim.created_at)}</span>
                  </div>
                </div>

                <ChevronRight className="w-4 h-4 text-zinc-700 group-hover:text-zinc-400 shrink-0 mt-1 transition-colors" />
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
