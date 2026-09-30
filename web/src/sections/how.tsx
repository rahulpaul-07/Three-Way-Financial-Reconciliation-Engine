import { useRef, useState } from "react";
import { useInViewport } from "@/hooks/use-hydrated";
import type { Run, Severity } from "@/lib/types";
import { cn, int, pct } from "@/lib/utils";
import { AnimatedBeam } from "@/components/ui/animated-beam";
import { BlurFade } from "@/components/ui/blur-fade";
import { SectionHeader } from "@/components/ui/section-header";
import { SEVERITY_BG, SEVERITY_NAME, SEVERITY_TEXT, SEVERITY_VAR } from "@/components/ui/severity";

// The tiers genuinely are a sequence -- each runs only on what the one before
// left behind -- so they are numbered.
const TIERS = [
  { name: "Self-consistency", body: "Checks that need one source only. Does gross minus fee minus GST equal net on each gateway row? Does every bank balance follow from the one before? A jump means a statement line is missing, and it is reported against the gap, not the row that reveals it." },
  { name: "Exact key joins", body: "Order to gateway row by order reference, gateway row to settlement by settlement ID, settlement to bank line by UTR. Fees are checked against a per-method rule table with a two-paise tolerance. A settlement already paid by one bank line cannot be paid again by a second." },
  { name: "Deterministic inference", body: "No usable reference: match on exact amount inside the T+1 to T+3 working-day window. Where several bank lines compete for several settlements, solve them together with the Hungarian algorithm rather than greedily. Instalments are matched by a subset sum bounded at four terms." },
  { name: "Bounded agent", body: "Whatever is left goes to a model with nine read-only tools and five rounds. It can propose; only a tool result that exists, ties exactly and falls in the window can make anything count as resolved." },
];

export function HowItWorks({ run }: { run: Run | null }) {
  return (
    <section id="how" className="border-b border-rule">
      <div className="mx-auto max-w-page px-5 py-20 sm:px-8 lg:py-28">
        <SectionHeader folio="01" eyebrow="How it works" title="Four files in. Every record out, with a reason.">
          Matching is a cascade of progressively weaker methods. Every resolution records the tier that produced it,
          so the result is stratified by confidence instead of reported as one opaque percentage. Figures below are
          from the reference batch.
        </SectionHeader>
        <BlurFade className="mt-12"><Flow run={run} /></BlurFade>
        <BlurFade className="mt-16"><Cascade run={run} /></BlurFade>
      </div>
    </section>
  );
}

const SOURCES = [
  { key: "orders", name: "Ledger", file: "ledger.csv", unit: "orders" },
  { key: "txns", name: "Gateway", file: "gateway.csv", unit: "rows" },
  { key: "settlements", name: "Settlements", file: "settlements.csv", unit: "payouts" },
  { key: "bank", name: "Bank", file: "bank.csv", unit: "lines" },
] as const;
const OUTCOMES: Severity[] = ["ok", "expected", "review", "break"];

/**
 * Where a record comes from and where it ends up, drawn as flows. Each
 * outcome's count is the engine's own, so the widths of the story and the
 * numbers cannot disagree.
 */
function Flow({ run }: { run: Run | null }) {
  const box = useRef<HTMLDivElement>(null);
  const engine = useRef<HTMLDivElement>(null);
  const src = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const out = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const sev = run?.summary.by_severity ?? {};
  const visible = useInViewport(box, "0px");

  return (
    <figure>
      {/* Stacked on phones, side by side from sm up; the beams follow. */}
      <div ref={box} className="relative grid items-center gap-y-12 engraved bg-sheet px-5 py-9 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,1fr)] sm:gap-x-12 sm:gap-y-0 sm:px-10 sm:py-10 lg:gap-x-28">
        <div className="relative z-10 grid grid-cols-2 gap-2.5 sm:block sm:space-y-4">
          {SOURCES.map((s, i) => (
            <div key={s.key} ref={src[i]} className="rounded-md border border-rule bg-paper px-2.5 py-2 sm:px-3.5 sm:py-2.5">
              <div className="text-[0.8rem] font-medium sm:text-sm">{s.name}</div>
              <div className="truncate font-mono text-[0.68rem] text-graphite sm:text-xs">
                {run ? `${int(run.sources[s.key])} ${s.unit}` : s.file}
              </div>
            </div>
          ))}
        </div>

        <div ref={engine} className="relative z-10 rounded-lg bg-ink outline outline-1 [outline-offset:-5px] outline-paper/30 dark:outline-tick/40 px-3 py-5 text-paper sm:px-5 sm:py-6 dark:bg-sheet dark:text-ink dark:ring-1 dark:ring-tick/50">
          <div className="smallcaps text-[0.8rem] opacity-70 sm:text-sm">Engine</div>
          <div className="mt-1 font-serif text-base leading-tight sm:text-xl">Tiered matcher</div>
          <ol className="mt-3 hidden space-y-1 text-xs opacity-80 sm:block">
            {TIERS.map((t, i) => <li key={t.name}><span className="num opacity-60">{i}</span> {t.name}</li>)}
          </ol>
          {run && (
            <div className="mt-3 border-t border-paper/15 pt-3 dark:border-ink/15 text-[0.72rem] sm:text-xs">
              <span className="num font-medium">{int(run.summary.entities)}</span> records,{" "}
              <span className="num font-medium">{pct(run.summary.resolution_rate)}</span> resolved
            </div>
          )}
        </div>

        <div className="relative z-10 grid grid-cols-2 gap-2.5 sm:block sm:space-y-4">
          {OUTCOMES.map((k, i) => (
            <div key={k} ref={out[i]} className="flex items-center justify-between gap-2 rounded-md border border-rule bg-paper px-2.5 py-2 sm:px-3.5 sm:py-2.5">
              <span className={cn("flex min-w-0 items-center gap-2 text-[0.8rem] font-medium sm:text-sm", SEVERITY_TEXT[k])}>
                <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", SEVERITY_BG[k])} />
                <span className="truncate">{SEVERITY_NAME[k]}</span>
              </span>
              <span className="num font-serif text-base sm:text-lg">{run ? int(sev[k] ?? 0) : "–"}</span>
            </div>
          ))}
        </div>

        {src.map((r, i) => (
          <AnimatedBeam key={`s${i}`} containerRef={box} fromRef={r} toRef={engine}
            curvature={(1.5 - i) * 18} delay={i * 0.35} color="rgb(var(--ink))" pathOpacity={0.18} active={visible} />
        ))}
        {out.map((r, i) => (
          <AnimatedBeam key={`o${i}`} containerRef={box} fromRef={engine} toRef={r}
            curvature={(i - 1.5) * -18} delay={1.6 + i * 0.35} color={SEVERITY_VAR[OUTCOMES[i]]} pathOpacity={0.3} active={visible} />
        ))}
      </div>
      <figcaption className="mt-3 max-w-prose text-sm text-graphite">
        Matched and explained records close themselves. Anything that needs review or is a genuine break is sent to a person
        with the reason attached; none is dropped.
      </figcaption>
    </figure>
  );
}

/**
 * The cascade, drawn with the counts from whichever batch is loaded: how many
 * records each tier was handed and how many it could close. Reading it top to
 * bottom is the argument for the design -- the strong methods take most of the
 * volume, and what survives all of them is small enough for a person.
 */
function Cascade({ run }: { run: Run | null }) {
  const [open, setOpen] = useState(1);
  const total = run?.summary.entities ?? 0;
  const closed = (tier: number) => Number(run?.summary.tiers[String(tier)] ?? 0);
  // Tier 0 closes nothing: a self-consistency check can only raise a hand, so
  // it is counted by what it does -- how many records it flagged.
  const flagged0 = run?.resolutions.filter((r) => r.tier === 0).length ?? 0;
  // Tier 3 needs a model and is not part of a recorded run, so it is shown as
  // the stage that receives whatever the three deterministic tiers left.
  const left = [0, 1, 2, 3].map((t) => total - [0, 1, 2, 3].slice(0, t).reduce((a, x) => a + closed(x), 0));

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
      <div>
        <h3 className="text-2xl font-medium">The cascade</h3>
        <p className="mt-3 max-w-prose leading-relaxed text-graphite">
          Each tier sees only what the tier before it could not close. The bars show how much of the batch is still open
          as it enters each one. Select a tier for what it does.
        </p>
      </div>
      <ol className="relative">
        {/* The rail the steps hang from. */}
        <span aria-hidden className="absolute bottom-6 left-[0.9rem] top-6 w-px bg-rule" />
        {TIERS.map((t, i) => {
          const entering = left[i];
          const share = total ? entering / total : 0;
          const isOpen = open === i;
          return (
            <li key={t.name} className="relative pb-3 pl-12 last:pb-0">
              <span aria-hidden className={cn("num absolute left-0 top-3 flex h-7 w-7 items-center justify-center rounded-full border text-xs transition-colors",
                isOpen ? "border-ink bg-ink text-paper" : "border-rule bg-paper text-graphite")}>{i}</span>
              <button onClick={() => setOpen(isOpen ? -1 : i)} aria-expanded={isOpen}
                className={cn("group w-full rounded-lg border px-4 py-3 text-left transition-colors",
                  isOpen ? "border-ink/30 bg-sheet" : "border-transparent hover:border-rule hover:bg-sheet/60")}>
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <span className="font-serif text-lg font-medium sm:text-xl">{t.name}</span>
                  {run && (
                    <span className="num ml-auto text-sm text-graphite">
                      {i === 0
                        ? <>{int(entering)} checked, <span className="text-redink">{int(flagged0)} flagged</span></>
                        : i < 3
                          ? <>{int(entering)} in, <span className="text-tick">{int(closed(i))} closed</span></>
                          : <>{int(entering)} left for a person</>}
                    </span>
                  )}
                </div>
                {run && (
                  <div className="mt-2 h-1.5 w-full rounded-full bg-rule/40" role="img"
                    aria-label={`${pct(share, 0)} of records still open entering this tier`}>
                    <div className={cn("h-full rounded-full transition-[width] duration-700", i === 3 ? "bg-redink/70" : "bg-tick")}
                      style={{ width: `${Math.max(share * 100, 0.6)}%`, opacity: 1 - i * 0.18 }} />
                  </div>
                )}
                <p className={cn("mt-2 max-w-prose text-sm leading-relaxed text-graphite", !isOpen && "line-clamp-1")}>
                  {t.body}
                </p>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
