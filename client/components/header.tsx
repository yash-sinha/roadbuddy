'use client'

interface HeaderProps {
  activeCount: number
}

export function Header({ activeCount }: HeaderProps) {
  return (
    <header className="h-14 px-6 flex items-center justify-between border-b border-zinc-800/50">
      <div className="flex items-center gap-3">
        <span className="text-white font-semibold tracking-tight">ClaimBuddy</span>
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-400 text-sm">Green Insurance Co-Pilot</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-800/50">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs text-zinc-400">{activeCount} Active</span>
        </div>
      </div>
    </header>
  )
}
