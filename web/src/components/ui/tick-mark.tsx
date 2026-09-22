import { motion, useReducedMotion } from "framer-motion";

/** The auditor's tick, drawn with a pencil stroke. */
export function TickMark({ delay = 0, size = 18, className }: { delay?: number; size?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" className={className} aria-hidden>
      <motion.path d="M3.5 10.5 L8 15 L16.5 4.5" fill="none" stroke="currentColor" strokeWidth={2.4}
        strokeLinecap="round" strokeLinejoin="round"
        initial={reduce ? false : { pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ delay, duration: 0.35, ease: "easeOut" }} />
    </svg>
  );
}

/** A red-ink ring, the mark a bookkeeper puts round an item that does not tie. */
export function InkRing({ delay = 0, className }: { delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <svg viewBox="0 0 120 40" preserveAspectRatio="none" className={className} aria-hidden>
      <motion.path d="M8 22 C 6 8, 110 4, 114 18 C 118 34, 12 38, 6 24 C 4 18, 20 10, 40 9"
        fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
        initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
        transition={{ delay, duration: 0.6, ease: "easeInOut" }} />
    </svg>
  );
}
