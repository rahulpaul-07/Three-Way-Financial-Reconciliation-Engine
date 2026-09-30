import { cn } from "@/lib/utils";

/**
 * A printer's rule: a hairline either side of a lozenge flanked by two
 * points, the ornament a Victorian compositor set between sections. Drawn
 * in SVG rather than a dingbat so it looks the same on every platform and
 * never falls back to an emoji font. Decorative, hidden from assistive tech.
 */
export function Ornament({ className, width = 120 }: { className?: string; width?: number }) {
  const mid = width / 2;
  return (
    <svg aria-hidden width={width} height="12" viewBox={`0 0 ${width} 12`} className={cn("text-brass", className)}>
      <line x1="0" y1="6" x2={mid - 14} y2="6" stroke="currentColor" strokeWidth="1" />
      <line x1={mid + 14} y1="6" x2={width} y2="6" stroke="currentColor" strokeWidth="1" />
      <circle cx={mid - 10} cy="6" r="1.4" fill="currentColor" />
      <circle cx={mid + 10} cy="6" r="1.4" fill="currentColor" />
      <path d={`M${mid} 1 L${mid + 5} 6 L${mid} 11 L${mid - 5} 6 Z`} fill="currentColor" />
    </svg>
  );
}
