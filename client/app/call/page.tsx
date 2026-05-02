'use client'

import { useState, useEffect, useRef, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Mic, MicOff, PhoneOff, Phone, CheckCircle2, XCircle, Clock, SendHorizontal } from 'lucide-react'
import Link from 'next/link'
import { WS_URL } from '@/lib/api'

type CallState = 'idle' | 'connecting' | 'active' | 'recording' | 'processing' | 'call_ended' | 'complete'
type VoiceState = 'waiting' | 'agent_speaking' | 'listening' | 'processing'

interface ClaimResult {
  covered: boolean | null
  sms_text: string
  claim_id: string
  callback_status_only?: boolean
  status_label?: string
  message?: string
}

interface LiveMessages {
  agent: string
  user: string
}

interface BrowserSpeechRecognitionAlternative {
  transcript: string
}

interface BrowserSpeechRecognitionResult {
  isFinal: boolean
  length: number
  [index: number]: BrowserSpeechRecognitionAlternative
}

interface BrowserSpeechRecognitionResultList {
  length: number
  [index: number]: BrowserSpeechRecognitionResult
}

interface BrowserSpeechRecognitionEvent extends Event {
  resultIndex: number
  results: BrowserSpeechRecognitionResultList
}

interface BrowserSpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  onerror: ((event: Event) => void) | null
  onend: (() => void) | null
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

declare global {
  interface Window {
    SpeechRecognition?: new () => BrowserSpeechRecognition
    webkitSpeechRecognition?: new () => BrowserSpeechRecognition
  }
}

const SILENCE_THRESHOLD = 0.018
const SILENCE_MS = 900
const CUSTOMER_NAME_KEY = 'scale_customer_name'
const CUSTOMER_KEY_KEY = 'scale_customer_key'

const STAGE_LABELS: Record<string, string> = {
  intake: 'Gathering information',
  damage_assessment: 'Assessing damage',
  rag: 'Checking policy',
  coverage: 'Determining coverage',
  escalation: 'Escalating to agent',
  decision: 'Arranging assistance',
  callback_complete: 'Claim update',
  complete: 'Complete',
}

function rememberCustomerName(name: unknown) {
  if (typeof window === 'undefined' || typeof name !== 'string') return
  const cleaned = name.trim()
  const firstName = cleaned.split(/\s+/)[0]
  if (!cleaned || !firstName) return
  window.localStorage.setItem(CUSTOMER_NAME_KEY, cleaned)
  window.localStorage.setItem(CUSTOMER_KEY_KEY, firstName)
}

function WaveformBars({ active }: { active: boolean }) {
  const delays = [0, 0.15, 0.3, 0.15, 0, 0.15, 0.3]
  return (
    <div className="flex items-center gap-1.5 h-14">
      {delays.map((delay, i) => (
        <div
          key={i}
          className={`w-1.5 rounded-full transition-all duration-300 ${active ? 'bg-violet-400 animate-bar-wave' : 'bg-zinc-700 h-2'}`}
          style={active ? { animationDelay: `${delay}s`, height: '100%' } : {}}
        />
      ))}
    </div>
  )
}

function RippleRings({ color = 'violet' }: { color?: 'violet' | 'red' }) {
  const borderColor = color === 'violet' ? 'border-violet-500/25' : 'border-red-500/25'
  return (
    <>
      {[0, 0.5, 1].map((delay) => (
        <div
          key={delay}
          className={`absolute rounded-full border ${borderColor} animate-ring-expand`}
          style={{
            width: '100%',
            height: '100%',
            animationDelay: `${delay}s`,
          }}
        />
      ))}
    </>
  )
}

function CallPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const callbackClaimId = searchParams.get('callback')

  const [callState, setCallState] = useState<CallState>('idle')
  const [voiceState, setVoiceState] = useState<VoiceState>('waiting')
  const [isRecording, setIsRecording] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [result, setResult] = useState<ClaimResult | null>(null)
  const [duration, setDuration] = useState(0)
  const [stage, setStage] = useState('')
  const [claimId, setClaimId] = useState<string | null>(null)
  const [liveMessages, setLiveMessages] = useState<LiveMessages>({ agent: '', user: '' })

  const wsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const proactiveTimerRef = useRef<NodeJS.Timeout | null>(null)
  const pendingUserTurnRef = useRef(false)
  const agentSpeakingTimerRef = useRef<NodeJS.Timeout | null>(null)
  const cancelCurrentRecordingRef = useRef(false)
  const currentAudioSourceRef = useRef<AudioBufferSourceNode | null>(null)
  const stoppingRecordingRef = useRef(false)
  const awaitingBackendRef = useRef(false)
  const backendTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reviewStartedAtRef = useRef<number | null>(null)
  const pendingResultRef = useRef<ClaimResult | null>(null)
  const completeRevealTimerRef = useRef<NodeJS.Timeout | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const analyserSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const silenceAnimationFrameRef = useRef<number | null>(null)
  const silenceStartedAtRef = useRef<number | null>(null)
  const speechDetectedRef = useRef(false)
  const speechRecognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const lastPartialTranscriptSentRef = useRef('')
  const committedUserMessageRef = useRef('')

  useEffect(() => {
    let interval: NodeJS.Timeout
    if (['active', 'recording', 'processing', 'call_ended'].includes(callState)) {
      interval = setInterval(() => setDuration((d) => d + 1), 1000)
    }
    return () => clearInterval(interval)
  }, [callState])

  const stopSpeechRecognition = useCallback((mode: 'stop' | 'abort' = 'abort') => {
    const recognition = speechRecognitionRef.current
    speechRecognitionRef.current = null
    if (!recognition) return
    try {
      if (mode === 'stop') {
        recognition.stop()
      } else {
        recognition.abort()
      }
    } catch {
      // browser speech recognition can throw if it is already stopped
    }
  }, [])

  const stopSilenceDetection = useCallback(() => {
    if (silenceAnimationFrameRef.current != null) {
      cancelAnimationFrame(silenceAnimationFrameRef.current)
      silenceAnimationFrameRef.current = null
    }
    analyserSourceRef.current?.disconnect()
    analyserSourceRef.current = null
    analyserRef.current = null
    silenceStartedAtRef.current = null
    speechDetectedRef.current = false
  }, [])

  const stopAgentPlayback = useCallback(() => {
    if (agentSpeakingTimerRef.current) {
      clearTimeout(agentSpeakingTimerRef.current)
      agentSpeakingTimerRef.current = null
    }
    try {
      currentAudioSourceRef.current?.stop()
    } catch {
      // audio can already be finished when barge-in fires
    }
    currentAudioSourceRef.current = null
    setVoiceState((current) => current === 'agent_speaking' ? 'waiting' : current)
  }, [])

  const sendTranscriptPartial = useCallback((text: string) => {
    const cleaned = text.trim()
    if (!cleaned || cleaned === lastPartialTranscriptSentRef.current) return
    lastPartialTranscriptSentRef.current = cleaned
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'transcript_partial', text: cleaned }))
    }
  }, [])

  const cleanupRealtime = useCallback(() => {
    if (proactiveTimerRef.current) {
      clearTimeout(proactiveTimerRef.current)
      proactiveTimerRef.current = null
    }
    if (agentSpeakingTimerRef.current) {
      clearTimeout(agentSpeakingTimerRef.current)
      agentSpeakingTimerRef.current = null
    }
    if (backendTimeoutRef.current) {
      clearTimeout(backendTimeoutRef.current)
      backendTimeoutRef.current = null
    }
    if (completeRevealTimerRef.current) {
      clearTimeout(completeRevealTimerRef.current)
      completeRevealTimerRef.current = null
    }
    stopSilenceDetection()
    stopSpeechRecognition('abort')
    mediaRecorderRef.current?.stream?.getTracks().forEach((track) => track.stop())
    mediaRecorderRef.current = null
    stopAgentPlayback()
    pendingUserTurnRef.current = false
    cancelCurrentRecordingRef.current = false
    stoppingRecordingRef.current = false
    awaitingBackendRef.current = false
    reviewStartedAtRef.current = null
    pendingResultRef.current = null
    lastPartialTranscriptSentRef.current = ''
    committedUserMessageRef.current = ''
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [stopAgentPlayback, stopSilenceDetection, stopSpeechRecognition])

  useEffect(() => {
    return () => cleanupRealtime()
  }, [cleanupRealtime])

  const playAudio = useCallback(async (b64: string) => {
    if (!b64) return
    const bytes = atob(b64)
    const buf = new Uint8Array(bytes.length)
    for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i)
    if (!audioCtxRef.current) audioCtxRef.current = new AudioContext()
    const audioBuf = await audioCtxRef.current.decodeAudioData(buf.buffer)
    currentAudioSourceRef.current?.stop()
    const source = audioCtxRef.current.createBufferSource()
    source.buffer = audioBuf
    source.connect(audioCtxRef.current.destination)
    currentAudioSourceRef.current = source
    source.start()
    setVoiceState('agent_speaking')
    if (agentSpeakingTimerRef.current) clearTimeout(agentSpeakingTimerRef.current)
    const durationMs = (audioBuf.duration * 1000) + 300
    agentSpeakingTimerRef.current = setTimeout(() => {
      currentAudioSourceRef.current = null
      setVoiceState('waiting')
    }, durationMs)
  }, [])

  const clearBackendWait = useCallback(() => {
    awaitingBackendRef.current = false
    if (backendTimeoutRef.current) {
      clearTimeout(backendTimeoutRef.current)
      backendTimeoutRef.current = null
    }
  }, [])

  const startBackendWait = useCallback(() => {
    awaitingBackendRef.current = true
    if (backendTimeoutRef.current) {
      clearTimeout(backendTimeoutRef.current)
    }
    backendTimeoutRef.current = setTimeout(() => {
      awaitingBackendRef.current = false
      pendingUserTurnRef.current = false
      stoppingRecordingRef.current = false
      setCallState('active')
      setVoiceState('waiting')
    }, 15000)
  }, [])

  const stopRecordingTurn = useCallback((cancel = false) => {
    if (!mediaRecorderRef.current || stoppingRecordingRef.current) return
    cancelCurrentRecordingRef.current = cancel
    stoppingRecordingRef.current = true
    stopSilenceDetection()
    stopSpeechRecognition(cancel ? 'abort' : 'stop')
    setIsRecording(false)
    setCallState(cancel ? 'active' : 'processing')
    setVoiceState(cancel ? 'waiting' : 'processing')
    mediaRecorderRef.current.stop()
  }, [stopSilenceDetection, stopSpeechRecognition])

  const startSpeechRecognition = useCallback(() => {
    if (typeof window === 'undefined') return
    const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!RecognitionCtor) return

    stopSpeechRecognition('abort')
    const recognition = new RecognitionCtor()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.onresult = (event) => {
      let fullText = ''
      for (let i = 0; i < event.results.length; i++) {
        const candidate = event.results[i]?.[0]?.transcript?.trim()
        if (candidate) {
          fullText = `${fullText} ${candidate}`.trim()
        }
      }
      if (!fullText) return
      setLiveMessages((current) => ({ ...current, user: fullText }))
      sendTranscriptPartial(fullText)
    }
    recognition.onerror = () => {
      if (speechRecognitionRef.current === recognition) {
        speechRecognitionRef.current = null
      }
    }
    recognition.onend = () => {
      if (speechRecognitionRef.current === recognition) {
        speechRecognitionRef.current = null
      }
    }
    speechRecognitionRef.current = recognition
    try {
      recognition.start()
    } catch {
      speechRecognitionRef.current = null
    }
  }, [sendTranscriptPartial, stopSpeechRecognition])

  const startSilenceDetection = useCallback((stream: MediaStream) => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext()
    }
    const context = audioCtxRef.current
    context.resume().catch(() => {})

    stopSilenceDetection()

    const source = context.createMediaStreamSource(stream)
    const analyser = context.createAnalyser()
    analyser.fftSize = 2048
    source.connect(analyser)

    analyserSourceRef.current = source
    analyserRef.current = analyser
    silenceStartedAtRef.current = null
    speechDetectedRef.current = false

    const samples = new Uint8Array(analyser.fftSize)
    const tick = () => {
      const activeAnalyser = analyserRef.current
      if (!activeAnalyser) return

      activeAnalyser.getByteTimeDomainData(samples)
      let sumSquares = 0
      for (const raw of samples) {
        const normalized = (raw - 128) / 128
        sumSquares += normalized * normalized
      }
      const rms = Math.sqrt(sumSquares / samples.length)
      const now = performance.now()

      if (rms >= SILENCE_THRESHOLD) {
        speechDetectedRef.current = true
        silenceStartedAtRef.current = null
      } else if (speechDetectedRef.current) {
        if (silenceStartedAtRef.current == null) {
          silenceStartedAtRef.current = now
        } else if (now - silenceStartedAtRef.current >= SILENCE_MS) {
          stopRecordingTurn(false)
          return
        }
      }

      silenceAnimationFrameRef.current = requestAnimationFrame(tick)
    }

    silenceAnimationFrameRef.current = requestAnimationFrame(tick)
  }, [stopRecordingTurn, stopSilenceDetection])

  const handleWsMessage = useCallback((event: MessageEvent) => {
    const state = JSON.parse(event.data)
    const partialOnly = Boolean(
      state.turn_transcript_partial &&
      !state.turn_transcript &&
      !state.audio &&
      state.stage === 'intake',
    )
    if (!partialOnly) {
      clearBackendWait()
      stoppingRecordingRef.current = false
    }
    setStage(state.stage || '')
    if (state.claim_id) setClaimId(state.claim_id)
    rememberCustomerName(state.schema?.name)

    if (state.follow_up || state.proactive) {
      setCallState('active')
      setLiveMessages((current) => ({
        ...current,
        agent: state.follow_up || state.message || current.agent,
      }))
      if (!state.audio) {
        setVoiceState('waiting')
      }
    }
    if (state.turn_transcript_partial) {
      setLiveMessages((current) => ({ ...current, user: state.turn_transcript_partial }))
    }
    if (state.turn_transcript) {
      pendingUserTurnRef.current = false
      committedUserMessageRef.current = state.turn_transcript
      lastPartialTranscriptSentRef.current = ''
      setLiveMessages((current) => ({ ...current, user: state.turn_transcript }))
    }
    if (state.stage === 'call_ended') {
      reviewStartedAtRef.current = Date.now()
      setCallState('call_ended')
      if (state.message) {
        setLiveMessages((current) => ({ ...current, agent: state.message }))
      }
    }
    if (state.callback_status_only || state.stage === 'callback_complete') {
      setResult({
        covered: state.coverage?.covered ?? null,
        sms_text: '',
        claim_id: state.callback_claim_id || callbackClaimId || '',
        callback_status_only: true,
        status_label: state.callback_status_label || 'Claim update',
        message: state.message || state.follow_up || '',
      })
      pendingResultRef.current = null
      reviewStartedAtRef.current = null
      setCallState('complete')
      if (state.message) {
        setLiveMessages((current) => ({ ...current, agent: state.message }))
      }
    }
    if (state.stage === 'escalation') {
      pendingResultRef.current = null
      reviewStartedAtRef.current = null
      setResult({
        covered: null,
        sms_text: '',
        claim_id: state.claim_id ?? claimId ?? '',
        callback_status_only: true,
        status_label: 'Under human review',
        message: "We're checking the details with one of our agents. We'll text you shortly with the next steps.",
      })
      setCallState('complete')
    }
    if (state.stage === 'complete') {
      const nextResult = {
        covered: state.coverage?.covered ?? false,
        sms_text: state.sms_text ?? '',
        claim_id: state.claim_id ?? '',
      }
      const reviewStartedAt = reviewStartedAtRef.current
      const elapsed = reviewStartedAt ? Date.now() - reviewStartedAt : 0
      const remainingMs = Math.max(0, 2500 - elapsed)
      pendingResultRef.current = nextResult
      if (completeRevealTimerRef.current) {
        clearTimeout(completeRevealTimerRef.current)
      }
      if (remainingMs === 0) {
        setResult(nextResult)
        setCallState('complete')
      } else {
        completeRevealTimerRef.current = setTimeout(() => {
          if (pendingResultRef.current) {
            setResult(pendingResultRef.current)
            setCallState('complete')
            pendingResultRef.current = null
          }
        }, remainingMs)
      }
    }
    if (state.audio) {
      playAudio(state.audio)
    }
  }, [callbackClaimId, clearBackendWait, playAudio])

  const connectWs = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    ws.binaryType = 'arraybuffer'
    ws.onopen = () => {
      const msg: Record<string, string> = { type: 'start_session' }
      if (callbackClaimId) msg.callback_claim_id = callbackClaimId
      ws.send(JSON.stringify(msg))
      setCallState('active')
      proactiveTimerRef.current = setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'proactive_check' }))
        }
      }, 10000)
    }
    ws.onmessage = handleWsMessage
    ws.onclose = () => {
      setCallState((current) => current === 'complete' ? current : 'idle')
    }
    wsRef.current = ws
  }, [handleWsMessage, callbackClaimId])

  const handleStartCall = async () => {
    cleanupRealtime()
    setCallState('connecting')
    setDuration(0)
    setResult(null)
    setClaimId(null)
    setVoiceState('waiting')
    setLiveMessages({ agent: '', user: '' })
    reviewStartedAtRef.current = null
    pendingResultRef.current = null
    committedUserMessageRef.current = ''
    lastPartialTranscriptSentRef.current = ''

    // Request mic permission up front so the browser prompt appears at the
    // moment the user clicks Start Call, not later when they tap the mic.
    try {
      const probeStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      probeStream.getTracks().forEach((t) => t.stop())
    } catch (err) {
      console.warn('Microphone permission denied or unavailable:', err)
      window.alert(
        'Microphone access is required for the call.\n\n' +
        'Click the lock icon next to the URL, allow microphone, then try again.'
      )
      setCallState('idle')
      return
    }

    connectWs()
  }

  const toggleRecording = async () => {
    if (isMuted) return
    if (stoppingRecordingRef.current) return
    if (isRecording) {
      stopRecordingTurn(false)
      return
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (proactiveTimerRef.current) {
      clearTimeout(proactiveTimerRef.current)
      proactiveTimerRef.current = null
    }
    if (voiceState === 'agent_speaking') {
      stopAgentPlayback()
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
      const chunks: Blob[] = []
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunks.push(e.data)
        }
      }
      mr.onstop = async () => {
        stopSilenceDetection()
        stream.getTracks().forEach((t) => t.stop())
        stoppingRecordingRef.current = false
        const wasCancelled = cancelCurrentRecordingRef.current
        cancelCurrentRecordingRef.current = false
        mediaRecorderRef.current = null
        if (wasCancelled) {
          setLiveMessages((current) => ({ ...current, user: committedUserMessageRef.current }))
          lastPartialTranscriptSentRef.current = ''
          setCallState('active')
          setVoiceState('waiting')
          return
        }
        if (!chunks.length || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          setLiveMessages((current) => ({ ...current, user: committedUserMessageRef.current }))
          lastPartialTranscriptSentRef.current = ''
          setCallState('active')
          setVoiceState('waiting')
          return
        }
        try {
          const blob = new Blob(chunks, { type: 'audio/webm;codecs=opus' })
          const arrayBuffer = await blob.arrayBuffer()
          pendingUserTurnRef.current = true
          wsRef.current.send(arrayBuffer)
          wsRef.current.send(JSON.stringify({ type: 'stop_recording' }))
          startBackendWait()
          setCallState('processing')
          setVoiceState('processing')
        } catch {
          pendingUserTurnRef.current = false
          setLiveMessages((current) => ({ ...current, user: committedUserMessageRef.current }))
          lastPartialTranscriptSentRef.current = ''
          setCallState('active')
          setVoiceState('waiting')
        }
      }
      mr.start(250)
      mediaRecorderRef.current = mr
      lastPartialTranscriptSentRef.current = ''
      startSpeechRecognition()
      startSilenceDetection(stream)
      setIsRecording(true)
      setCallState('recording')
      setVoiceState('listening')
    } catch {
      setCallState('active')
    }
  }

  const handleEndCall = () => {
    cleanupRealtime()
    setCallState('idle')
    setDuration(0)
    setResult(null)
    setClaimId(null)
    setVoiceState('waiting')
    setLiveMessages({ agent: '', user: '' })
    reviewStartedAtRef.current = null
    pendingResultRef.current = null
    committedUserMessageRef.current = ''
    lastPartialTranscriptSentRef.current = ''
  }

  const toggleMute = () => {
    if (stoppingRecordingRef.current || awaitingBackendRef.current || callState === 'processing') return
    setIsMuted((m) => !m)
    if (isRecording) {
      stopRecordingTurn(true)
    }
  }

  const formatTime = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white flex flex-col">
      <header className="h-14 px-6 flex items-center justify-between border-b border-zinc-800/50">
        <span className="font-semibold tracking-tight">ClaimBuddy</span>
        {(callState === 'active' || callState === 'recording' || callState === 'processing' || callState === 'call_ended') && (
          <span className="text-sm font-mono text-zinc-400">{formatTime(duration)}</span>
        )}
        {callState === 'idle' && <span className="text-xs text-zinc-600">Roadside assistance</span>}
      </header>

      <main className="flex-1 flex flex-col items-center justify-center p-6">

        {/* IDLE */}
        {callState === 'idle' && (
          <div className="flex flex-col items-center gap-10 text-center">
            <div>
              <p className="text-zinc-500 text-sm uppercase tracking-widest mb-2">ClaimBuddy</p>
              <h1 className="text-3xl font-semibold">File a Claim</h1>
            </div>
            <button
              onClick={handleStartCall}
              className="relative w-28 h-28 rounded-full bg-emerald-600 hover:bg-emerald-500 flex items-center justify-center transition-colors shadow-lg shadow-emerald-900/40 group"
            >
              <Phone className="w-10 h-10 group-hover:scale-110 transition-transform" />
            </button>
            <p className="text-zinc-500 text-sm">Tap to start your claim</p>
            <Link href="/claims" className="text-sm text-zinc-600 hover:text-zinc-400 transition-colors">
              View previous claims
            </Link>
            {callbackClaimId && (
              <div className="px-4 py-2 rounded-lg bg-violet-500/10 border border-violet-500/20 text-sm text-violet-400">
                Continuing with context from a previous claim
              </div>
            )}
          </div>
        )}

        {/* CONNECTING */}
        {callState === 'connecting' && (
          <div className="flex flex-col items-center gap-6">
            <div className="relative w-28 h-28 flex items-center justify-center">
              <RippleRings color="violet" />
              <div className="w-28 h-28 rounded-full bg-violet-600/20 border border-violet-500/30 flex items-center justify-center z-10">
                <Phone className="w-10 h-10 text-violet-400" />
              </div>
            </div>
            <p className="text-zinc-400">Connecting...</p>
          </div>
        )}

        {/* ACTIVE CALL */}
        {(callState === 'active' || callState === 'recording' || callState === 'processing') && (
          <div className="flex flex-col items-center gap-12 w-full max-w-sm">
            {/* Voice visualization */}
            <div className="flex flex-col items-center gap-6">
              <div className="relative w-36 h-36 flex items-center justify-center">
                {voiceState === 'agent_speaking' && <RippleRings color="violet" />}
                {voiceState === 'listening' && <RippleRings color="red" />}
                <div className={`w-36 h-36 rounded-full flex items-center justify-center z-10 transition-colors ${
                  voiceState === 'listening'
                    ? 'bg-red-600/20 border-2 border-red-500/50 animate-mic-pulse'
                    : voiceState === 'agent_speaking'
                    ? 'bg-violet-600/20 border-2 border-violet-500/50'
                    : 'bg-zinc-800 border-2 border-zinc-700'
                }`}>
                  {voiceState === 'processing' ? (
                    <div className="w-8 h-8 border-2 border-zinc-600 border-t-white rounded-full animate-spin" />
                  ) : voiceState === 'listening' ? (
                    <Mic className="w-12 h-12 text-red-400" />
                  ) : voiceState === 'agent_speaking' ? (
                    <WaveformBars active={true} />
                  ) : (
                    <WaveformBars active={false} />
                  )}
                </div>
              </div>

              <div className="text-center">
                <p className="text-sm font-medium text-zinc-300">
                  {voiceState === 'agent_speaking' ? 'ClaimBuddy' :
                   voiceState === 'listening' ? 'Listening...' :
                   voiceState === 'processing' ? (STAGE_LABELS[stage] || 'Processing...') :
                   'Tap mic when ready'}
                </p>
                {voiceState === 'agent_speaking' && (
                  <p className="text-xs text-zinc-600 mt-1">Tap mic to interrupt, or wait for the prompt to finish</p>
                )}
                {voiceState === 'listening' && (
                  <p className="text-xs text-zinc-600 mt-1">Pause briefly and we’ll send it automatically</p>
                )}
                {voiceState === 'processing' && stage && (
                  <p className="text-xs text-zinc-600 mt-1">{STAGE_LABELS[stage] || ''}</p>
                )}
              </div>
            </div>

            {(liveMessages.agent || liveMessages.user) && (
              <div className="w-full space-y-3">
                {liveMessages.agent && (
                  <div className="rounded-2xl bg-zinc-900/80 border border-zinc-800/80 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wider text-zinc-600 mb-1">ClaimBuddy</p>
                    <p className="text-sm text-zinc-200 leading-relaxed">{liveMessages.agent}</p>
                  </div>
                )}
                {liveMessages.user && (
                  <div className="rounded-2xl bg-violet-500/10 border border-violet-500/20 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wider text-violet-300/70 mb-1">You</p>
                    <p className="text-sm text-violet-100 leading-relaxed">{liveMessages.user}</p>
                  </div>
                )}
              </div>
            )}

            {/* Controls */}
            <div className="flex items-center gap-8">
              <button
                onClick={toggleMute}
                disabled={stoppingRecordingRef.current || awaitingBackendRef.current || callState === 'processing'}
                className={`w-14 h-14 rounded-full flex items-center justify-center transition-all ${
                  isMuted ? 'bg-zinc-700 text-zinc-300' : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-400'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
                title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
                aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
              >
                {isMuted ? <MicOff className="w-6 h-6" /> : <Mic className="w-6 h-6" />}
              </button>

              <button
                onClick={toggleRecording}
                disabled={callState === 'processing' || isMuted || stoppingRecordingRef.current}
                className={`w-20 h-20 rounded-full flex items-center justify-center transition-all shadow-lg ${
                  isRecording
                    ? 'bg-red-600 shadow-red-900/40 scale-110'
                    : 'bg-violet-600 hover:bg-violet-500 shadow-violet-900/40'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
                title={voiceState === 'agent_speaking' ? 'Interrupt and speak' : isRecording ? 'Send voice turn' : 'Tap to speak'}
                aria-label={voiceState === 'agent_speaking' ? 'Interrupt and speak' : isRecording ? 'Send voice turn' : 'Tap to speak'}
              >
                {isRecording ? <SendHorizontal className="w-8 h-8" /> : <Mic className="w-8 h-8" />}
              </button>

              <button
                onClick={handleEndCall}
                className="w-14 h-14 rounded-full bg-zinc-800 hover:bg-red-900/60 text-zinc-400 hover:text-red-400 flex items-center justify-center transition-all"
                title="End call"
              >
                <PhoneOff className="w-6 h-6" />
              </button>
            </div>

            <p className="text-xs text-zinc-600">Tap mic to speak. Pause to send automatically, or tap again to send sooner.</p>
          </div>
        )}

        {/* PROCESSING CLAIM (call ended, pipeline running) */}
        {callState === 'call_ended' && (
          <div className="flex flex-col items-center gap-8 text-center max-w-sm">
            <div className="relative w-28 h-28 flex items-center justify-center">
              <div className="absolute inset-0 rounded-full border border-violet-500/20 animate-ring-expand" />
              <div className="w-28 h-28 rounded-full bg-violet-600/10 border border-violet-500/20 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-zinc-700 border-t-violet-400 rounded-full animate-spin" />
              </div>
            </div>
            <div>
              <h2 className="text-xl font-semibold mb-2">Reviewing your claim</h2>
              <p className="text-sm text-zinc-500">We’re checking your cover and arranging the right assistance.</p>
            </div>
            <button
              onClick={handleEndCall}
              className="flex items-center gap-2 px-5 py-2.5 rounded-full border border-zinc-800 text-zinc-500 hover:text-white hover:border-zinc-600 text-sm transition-colors"
            >
              <PhoneOff className="w-4 h-4" /> Close
            </button>
          </div>
        )}

        {/* COMPLETE */}
        {callState === 'complete' && result && (
          <div className="w-full max-w-md flex flex-col gap-4">
            <div className="rounded-2xl border overflow-hidden bg-zinc-900/50"
              style={{
                borderColor: result.covered === true
                  ? 'rgb(34 197 94 / 0.2)'
                  : result.covered === false
                    ? 'rgb(239 68 68 / 0.2)'
                    : 'rgb(139 92 246 / 0.2)',
              }}>
              <div className={`px-6 py-5 flex items-center gap-4 ${
                result.covered === true ? 'bg-emerald-500/5' :
                result.covered === false ? 'bg-red-500/5' :
                'bg-violet-500/5'
              }`}>
                {result.covered === true
                  ? <CheckCircle2 className="w-8 h-8 text-emerald-400 shrink-0" />
                  : result.covered === false
                    ? <XCircle className="w-8 h-8 text-red-400 shrink-0" />
                    : <Clock className="w-8 h-8 text-violet-400 shrink-0" />
                }
                <div>
                  <p className={`font-semibold text-lg ${
                    result.covered === true ? 'text-emerald-400' :
                    result.covered === false ? 'text-red-400' :
                    'text-violet-300'
                  }`}>
                    {result.callback_status_only ? result.status_label : result.covered ? 'Help Confirmed' : 'Not Covered'}
                  </p>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {result.callback_status_only
                      ? 'Existing claim status'
                      : result.covered
                        ? 'Assistance is on the way'
                        : 'A claims handler will contact you within 2 hours'}
                  </p>
                </div>
              </div>
              {result.callback_status_only && result.message && (
                <div className="px-6 py-4 border-t border-zinc-800/50">
                  <p className="text-sm text-zinc-400 leading-relaxed">{result.message}</p>
                </div>
              )}
              {result.sms_text && (
                <div className="px-6 py-4 border-t border-zinc-800/50">
                  <p className="text-xs text-zinc-600 mb-1.5">SMS sent to your phone</p>
                  <p className="text-sm text-zinc-400 leading-relaxed">{result.sms_text}</p>
                </div>
              )}
            </div>

            <div className="flex gap-3">
              {result.claim_id && (
                <button
                  onClick={() => router.push(`/claims/${result.claim_id}`)}
                  className="flex-1 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors"
                >
                  {result.callback_status_only ? 'Back to Claim' : 'View Claim Details'}
                </button>
              )}
              <button
                onClick={() => {
                  cleanupRealtime()
                  setCallState('idle')
                  setResult(null)
                  setDuration(0)
                  setClaimId(null)
                }}
                className="flex-1 py-3 rounded-xl border border-zinc-800 text-zinc-400 hover:text-white hover:border-zinc-600 text-sm transition-colors"
              >
                Start Another Claim
              </button>
            </div>

            <Link href="/claims" className="text-center text-sm text-zinc-600 hover:text-zinc-400 transition-colors">
              View previous claims
            </Link>
          </div>
        )}
      </main>
    </div>
  )
}

export default function CustomerCallPage() {
  return (
    <Suspense>
      <CallPageInner />
    </Suspense>
  )
}
