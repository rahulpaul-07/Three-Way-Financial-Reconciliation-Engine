import { cn } from "@/lib/utils";

/** A leaf of the ledger: a titled region with an optional note beneath. */
export function Panel({ title, note, action, className, children }: {
  title?: React.ReactNode; note?: React.ReactNode; action?: React.ReactNode;
  className?: string; children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border border-rule bg-sheet p-5 sm:p-6", className)}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
          {title && <h3 className="text-lg font-semibold leading-tight">{title}</h3>}
          {action}
        </div>
      )}
      {children}
      {note && <p className="mt-4 max-w-prose text-sm text-graphite">{note}</p>}
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-rule/50", className)} />;
}
