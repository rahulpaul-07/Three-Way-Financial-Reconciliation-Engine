import { motion, useReducedMotion } from "framer-motion";
import { useId, useRef } from "react";
import { cn } from "@/lib/utils";

export interface TabItem<T extends string> { value: T; label: React.ReactNode; count?: number }

/**
 * Tabs with an indicator that slides to the chosen tab.
 *
 * The pattern follows 21st.dev's Animated Tabs (21st.dev/@educalvolpz/
 * components/animated-tabs): the indicator moves rather than fading out and
 * in, and takes the width of the active label rather than assuming equal
 * tabs. Built here on framer-motion's shared layout animation, with the
 * WAI-ARIA tabs pattern: one tab stop, arrow keys, Home and End.
 *
 * `variant="underline"` sits on a rule, for switching views of one thing.
 * `variant="pill"` sits in a tray, for choosing where the data comes from.
 */
export function Tabs<T extends string>({ items, value, onChange, label, variant = "underline", idBase, className }: {
  items: TabItem<T>[]; value: T; onChange: (v: T) => void; label: string;
  variant?: "underline" | "pill"; idBase?: string; className?: string;
}) {
  const auto = useId().replace(/:/g, "");
  const base = idBase ?? auto;
  const reduce = useReducedMotion();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKey(e: React.KeyboardEvent, i: number) {
    const last = items.length - 1;
    const next = e.key === "ArrowRight" ? (i === last ? 0 : i + 1)
      : e.key === "ArrowLeft" ? (i === 0 ? last : i - 1)
      : e.key === "Home" ? 0 : e.key === "End" ? last : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].value);
    refs.current[next]?.focus();
  }

  const pill = variant === "pill";
  return (
    <div role="tablist" aria-label={label}
      className={cn("scroll-x relative flex max-w-full",
        pill ? "w-fit gap-1 rounded-lg border border-rule bg-sheet p-1" : "gap-1 border-b border-rule",
        className)}>
      {items.map((t, i) => {
        const active = t.value === value;
        return (
          <button key={t.value} ref={(el) => { refs.current[i] = el; }}
            role="tab" id={`${base}-tab-${t.value}`} aria-selected={active}
            aria-controls={`${base}-panel-${t.value}`} tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.value)} onKeyDown={(e) => onKey(e, i)}
            className={cn("relative shrink-0 whitespace-nowrap text-sm font-medium transition-colors",
              pill ? "rounded-md px-3.5 py-1.5" : "px-3 pb-2.5 pt-1.5",
              active ? (pill ? "text-paper" : "text-ink") : "text-graphite hover:text-ink")}>
            {active && (
              <motion.span layoutId={`${base}-indicator`} aria-hidden
                transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 500, damping: 40 }}
                className={cn("absolute",
                  pill ? "inset-0 rounded-md bg-ink" : "inset-x-2 -bottom-px h-0.5 rounded-full bg-tick")} />
            )}
            <span className="relative z-10 inline-flex items-center gap-2">
              {t.label}
              {t.count != null && (
                <span className={cn("num rounded px-1.5 text-xs",
                  active ? (pill ? "bg-paper/20" : "bg-tick/15 text-tick") : "bg-rule/50")}>{t.count}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** The region a tab controls. Rendered only when selected. */
export function TabPanel({ idBase, value, children, className }: {
  idBase: string; value: string; children: React.ReactNode; className?: string;
}) {
  return (
    <div role="tabpanel" id={`${idBase}-panel-${value}`} aria-labelledby={`${idBase}-tab-${value}`}
      tabIndex={0} className={cn("focus-visible:outline-offset-4", className)}>
      {children}
    </div>
  );
}
