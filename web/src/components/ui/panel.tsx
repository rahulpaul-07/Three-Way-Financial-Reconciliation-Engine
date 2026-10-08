import { cn } from "@/lib/utils";
import { accentOf } from "./section";

/** A leaf of the ledger: a titled region with an optional note beneath. */
/** Tracks the pointer for the `.spotlight` glow (after Magic UI's Magic Card). */
function moveSpotlight(e: React.PointerEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
  e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
}

export function Panel({ title, note, action, className, spotlight, accent = 0, children }: {
  title?: React.ReactNode; note?: React.ReactNode; action?: React.ReactNode;
  className?: string; spotlight?: boolean; accent?: number; children: React.ReactNode;
}) {
  return (
    <section onPointerMove={spotlight ? moveSpotlight : undefined} data-accent={accentOf(accent)}
      className={cn("card-max shadow-hard-sm p-5 sm:p-7", accent % 3 === 1 && "dashed", spotlight && "spotlight", className)}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
          {title && <h3 className="ts-1 text-xl font-black uppercase leading-tight tracking-tight">{title}</h3>}
          {action}
        </div>
      )}
      {children}
      {note && <p className="mt-4 max-w-prose text-sm text-graphite">{note}</p>}
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-violet/40", className)} />;
}
