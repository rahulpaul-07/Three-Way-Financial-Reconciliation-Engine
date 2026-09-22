import { cn } from "@/lib/utils";

/** A row of mutually exclusive choices; keyboard reachable, announces state. */
export function Segmented<T extends string>({ value, onChange, options, label, className }: {
  value: T; onChange: (v: T) => void; label: string; className?: string;
  options: { value: T; label: React.ReactNode; hint?: string }[];
}) {
  return (
    <div role="radiogroup" aria-label={label}
      className={cn("inline-flex flex-wrap gap-1 rounded border border-rule bg-sheet p-1", className)}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} title={o.hint}
          onClick={() => onChange(o.value)}
          className={cn("rounded-sm px-3 py-1.5 text-sm transition-colors",
            value === o.value ? "bg-ink text-paper" : "text-graphite hover:bg-ink/[0.06] hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
