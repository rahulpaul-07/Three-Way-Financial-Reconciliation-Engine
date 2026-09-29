import { cn } from "@/lib/utils";
import { BlurFade } from "./blur-fade";

/**
 * The opening of a section: a numbered folio, the title, and a short lede.
 *
 * The folio is the page reference a ledger carries in its margin; it is also
 * the editorial device the long-form sites collected on godly.website use to
 * give a long page a table of contents the reader can feel.
 */
export function SectionHeader({ folio, eyebrow, title, children, className }: {
  folio: string; eyebrow: string; title: React.ReactNode; children?: React.ReactNode; className?: string;
}) {
  return (
    <BlurFade className={cn("grid gap-x-10 gap-y-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-end", className)}>
      <div>
        <p className="flex items-center gap-3 font-mono text-xs uppercase tracking-[0.14em] text-graphite">
          <span className="num text-tick">{folio}</span>
          <span aria-hidden className="h-px w-8 bg-rule" />
          {eyebrow}
        </p>
        <h2 className="mt-4 text-balance text-[clamp(2rem,3.6vw,3rem)] font-medium leading-[1.05] tracking-[-0.015em]">{title}</h2>
      </div>
      {children && <div className="max-w-prose text-[1.05rem] leading-relaxed text-graphite lg:pb-1">{children}</div>}
    </BlurFade>
  );
}
