import { cn } from "@/lib/utils";
import { BlurFade } from "./blur-fade";
import { Ornament } from "./ornament";

const ROMAN: [number, string][] = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];

/** "04" becomes "IV"; anything that is not a small number is shown as given. */
function roman(folio: string) {
  let n = Number(folio);
  if (!Number.isInteger(n) || n < 1 || n > 39) return folio;
  let out = "";
  for (const [v, s] of ROMAN) while (n >= v) { out += s; n -= v; }
  return out;
}

/**
 * The opening of a section: a numbered folio, the title, and a short lede.
 *
 * The folio is the page reference a ledger carries in its margin, set in
 * Roman numerals as a Victorian account book numbered its parts; it also
 * gives a long page a table of contents the reader can feel.
 */
export function SectionHeader({ folio, eyebrow, title, children, className }: {
  folio: string; eyebrow: string; title: React.ReactNode; children?: React.ReactNode; className?: string;
}) {
  return (
    <BlurFade className={cn("grid gap-x-10 gap-y-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-end", className)}>
      <div>
        <p className="smallcaps flex items-center gap-3 text-sm text-graphite">
          <span className="font-serif text-base tracking-[0.04em] text-redink [font-variant-caps:normal]">
            <span className="sr-only">Part </span>{roman(folio)}.
          </span>
          {eyebrow}
        </p>
        <h2 className="mt-3 text-balance text-[clamp(2rem,3.6vw,3rem)] font-medium leading-[1.08] tracking-[-0.01em]">{title}</h2>
        <Ornament className="mt-5" />
      </div>
      {children && <div className="max-w-prose text-[1.05rem] leading-relaxed text-graphite lg:pb-1">{children}</div>}
    </BlurFade>
  );
}
