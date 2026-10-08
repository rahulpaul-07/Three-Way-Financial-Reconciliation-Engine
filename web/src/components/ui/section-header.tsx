import { cn } from "@/lib/utils";
import { BlurFade } from "./blur-fade";

/**
 * The opening of a section: a numbered sticker, the title in stacked-shadow
 * display type, and a short lede. The sticker takes the section's accent
 * (set on the enclosing Section) so each part of the page reads as its own
 * colour.
 */
export function SectionHeader({ folio, eyebrow, title, children, className }: {
  folio: string; eyebrow: string; title: React.ReactNode; children?: React.ReactNode; className?: string;
}) {
  return (
    <BlurFade className={cn("grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-end", className)}>
      <div>
        <p className="flex flex-wrap items-center gap-3 text-sm font-black uppercase tracking-widest">
          <span className="num -rotate-3 rounded-full border-4 border-[rgb(var(--b))] bg-[rgb(var(--a))] px-3 py-0.5 text-[rgb(var(--on))] shadow-[3px_3px_0_rgb(var(--violet))]">{folio}</span>
          <span className="text-[rgb(var(--a))]">{eyebrow}</span>
        </p>
        <h2 className="ts-2 mt-5 text-balance text-[clamp(2.4rem,5.5vw,4.5rem)] font-black uppercase leading-[0.95] tracking-tighter">{title}</h2>
      </div>
      {children && <div className="max-w-prose text-lg leading-relaxed text-graphite lg:pb-1">{children}</div>}
    </BlurFade>
  );
}
