import { cn } from "@/lib/utils";

/** A row of mutually exclusive choices; keyboard reachable, announces state. */
export function Segmented<T extends string>({ value, onChange, options, label, className }: {
  value: T; onChange: (v: T) => void; label: string; className?: string;
  options: { value: T; label: React.ReactNode; hint?: string }[];
}) {
  return (
    <div role="radiogroup" aria-label={label}
      className={cn("inline-flex flex-wrap gap-1 rounded-full border-4 border-tick bg-sheet/80 p-1", className)}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} title={o.hint}
          onClick={() => onChange(o.value)}
          className={cn("rounded-full px-4 py-2 text-sm font-bold uppercase tracking-wide transition-all duration-200",
            value === o.value ? "scale-105 bg-pencil text-paper shadow-[3px_3px_0_rgb(var(--magenta))]" : "text-graphite hover:bg-magenta/20 hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
