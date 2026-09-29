import { useId } from 'react'

/** ICTS Rostering mark: a gradient tile holding a calendar whose cells read as shifts. */
export function LogoMark({ size = 48, className }: { size?: number; className?: string }) {
  const gradient = useId()
  return (
    <svg className={className} viewBox="0 0 48 48" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id={gradient} x1="4" y1="2" x2="44" y2="46" gradientUnits="userSpaceOnUse">
          <stop stopColor="#60a5fa" />
          <stop offset="1" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="14" fill={`url(#${gradient})`} />
      <rect x="10" y="11" width="28" height="27" rx="6" fill="none" stroke="#fff" strokeWidth="2.2" opacity="0.95" />
      <path d="M10 19h28" stroke="#fff" strokeWidth="2.2" opacity="0.95" />
      <path d="M17 8v6M31 8v6" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
      <rect x="14.5" y="23" width="6" height="5" rx="1.6" fill="#fff" />
      <rect x="21.5" y="23" width="6" height="5" rx="1.6" fill="#fff" opacity="0.55" />
      <rect x="28.5" y="23" width="5" height="5" rx="1.6" fill="#fff" opacity="0.55" />
      <rect x="14.5" y="29.5" width="6" height="5" rx="1.6" fill="#fff" opacity="0.55" />
      <rect x="21.5" y="29.5" width="12" height="5" rx="1.6" fill="#fff" />
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
