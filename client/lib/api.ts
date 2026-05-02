const RAW_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000'
export const API_BASE = RAW_BASE.replace(/\/$/, '')
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? API_BASE.replace(/^http/, 'ws') + '/ws'
