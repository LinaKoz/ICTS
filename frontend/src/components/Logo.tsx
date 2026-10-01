/** ICTS Rostering mark: an ink tile crossed by the day's three shift bands. */
export function LogoMark({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" width={size} height={size} aria-hidden="true">
      <rect width="40" height="40" rx="6" fill="var(--ink)" />
      <rect x="7" y="23" width="8" height="6" fill="var(--shift-a)" />
      <rect x="16" y="23" width="8" height="6" fill="var(--shift-b)" />
      <rect x="25" y="23" width="8" height="6" fill="var(--shift-c)" />
      <rect x="7" y="11" width="26" height="2.5" fill="var(--surface)" />
      <rect x="7" y="16" width="16" height="2.5" fill="var(--surface)" opacity="0.6" />
    </svg>
  )
}

export function Logo() {
  return (
    <span className="logo">
      <LogoMark className="logo-mark" />
      <span className="logo-word"><span className="logo-icts">ICTS</span> Rostering</span>
    </span>
  )
}
