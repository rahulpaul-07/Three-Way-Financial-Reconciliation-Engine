import { blob } from "./links";

import { useState } from "react";
import type { Run } from "@/lib/types";
import { cn, int, pct } from "@/lib/utils";

// The tiers genuinely are a sequence -- each runs only on what the one before
// left behind -- so they are numbered. The stances below are not, so they are not.
const TIERS = [
  { name: "Self-consistency", body: "Checks that need one source only. Does gross minus fee minus GST equal net on each gateway row? Does every bank balance follow from the one before? A jump means a statement line is missing, and it is reported against the gap, not the row that reveals it." },
  { name: "Exact key joins", body: "Order to gateway row by order reference, gateway row to settlement by settlement ID, settlement to bank line by UTR. Fees are checked against a per-method rule table with a two-paise tolerance. A settlement already paid by one bank line cannot be paid again by a second." },
  { name: "Deterministic inference", body: "No usable reference: match on exact amount inside the T+1 to T+3 working-day window. Where several bank lines compete for several settlements, solve them together with the Hungarian algorithm rather than greedily. Instalments are matched by a subset sum bounded at four terms." },
  { name: "Bounded agent", body: "Whatever is left goes to a model with nine read-only tools and five rounds. It can propose; only a tool result that exists, ties exactly and falls in the window can make anything count as resolved." },
];

const STANCES = [
  { title: "A wrong match is worse than no match", body: "An unmatched record is visible and gets looked at. A wrong match is invisible and makes the books appear to balance. Where two settlements fit equally, the engine refuses to choose." },
  { title: "Constraints live in code, not in the prompt", body: "Step limits, a closed tool registry, a fixed taxonomy and the evidence rule are enforced by the program and tested with adversarial input, no model in the loop. A rule in a prompt is a request." },
  { title: "Measured against an answer key", body: "The generator writes a ground-truth file the engine never reads. Accuracy is graded, not asserted, and CI fails the build if it moves." },
];

const RULES = [
  "Money is integer paise throughout; floats never touch currency.",
  "MDR depends on method: a percentage for cards and wallets, flat for netbanking, zero for UPI.",
  "Settlement is T+1 working days; a Friday capture settles on Monday.",
  "Refunds and chargebacks are negative, so a settlement can legitimately net below zero.",
  "Only rows that moved money must satisfy gross − fee − GST = net; a failed attempt has net zero.",
  "An order in a currency other than INR cannot be compared, however well its number ties.",
];

export function HowItWorks({ run }: { run: Run | null }) {
  return (
    <section id="how">
      <div className="mx-auto max-w-page px-5 py-16 sm:px-8 lg:py-20">
        <div className="max-w-prose">
          <h2 className="text-3xl font-medium">How it works</h2>
          <p className="mt-3 text-graphite">
            Matching is a cascade of progressively weaker methods. Every resolution records the tier that produced it,
            so the result is stratified by confidence instead of reported as one opaque percentage.
          </p>
        </div>

        <Cascade run={run} />

        <div className="mt-16 grid gap-12 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div>
            <h3 className="text-2xl font-medium">Three stances</h3>
            <div className="mt-5 space-y-6">
              {STANCES.map((s) => (
                <div key={s.title} className="max-w-prose">
                  <h4 className="font-serif text-lg font-medium">{s.title}</h4>
                  <p className="mt-1 leading-relaxed text-graphite">{s.body}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-medium">Domain rules encoded</h3>
            <ul className="ruled mt-5 text-sm leading-8">
              {RULES.map((r) => <li key={r} className="text-ink">{r}</li>)}
            </ul>
            <p className="mt-6 text-sm text-graphite">
              The reasoning behind each choice, and what was rejected, is in{" "}
              <a className="underline underline-offset-2 hover:text-ink" href={blob("DECISIONS.md")}>DECISIONS.md</a>; what broke during the build and how,
              in <a className="underline underline-offset-2 hover:text-ink" href={blob("NOTES.md")}>NOTES.md</a>.
            </p>
          </div>
        </div>
      </div>
    </section>
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
  // Tier 0 closes nothing: a self-consistency check can only raise a hand.
  // Reporting it as "0 closed" would read as a failure, so it is counted by
  // what it actually does -- how many records it flagged.
  const flagged0 = run?.resolutions.filter((r) => r.tier === 0).length ?? 0;
  // Tier 3 needs a model and is not part of a recorded run, so it is shown as
  // the stage that receives whatever the three deterministic tiers left.
  const left = [0, 1, 2, 3].map((t) => total - [0, 1, 2, 3].slice(0, t).reduce((a, x) => a + closed(x), 0));

  return (
    <ol className="mt-10 space-y-2">
      {TIERS.map((t, i) => {
        const entering = left[i];
        const resolved = i < 3 ? closed(i) : 0;
        const share = total ? entering / total : 0;
        const isOpen = open === i;
        return (
          <li key={t.name}>
            <button onClick={() => setOpen(isOpen ? -1 : i)} aria-expanded={isOpen}
              className="group w-full rounded-lg border border-rule bg-sheet px-4 py-3 text-left transition-colors hover:border-ink/40">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="num font-serif text-sm text-graphite">Tier {i}</span>
                <span className="font-serif text-xl font-medium">{t.name}</span>
                {run && (
                  <span className="num ml-auto text-sm text-graphite">
                    {i === 0
                      ? <>{int(entering)} checked, <span className="text-redink">{int(flagged0)} flagged</span></>
                      : i < 3
                        ? <>{int(entering)} in, <span className="text-tick">{int(resolved)} closed</span></>
                        : <>{int(entering)} left for a person</>}
                  </span>
                )}
              </div>
              {run && (
                <div className="mt-2 h-2 w-full rounded-sm bg-rule/40" role="img"
                  aria-label={`${pct(share, 0)} of records still open entering this tier`}>
                  <div className={cn("h-full rounded-sm", i === 3 ? "bg-redink/70" : "bg-tick")}
                    style={{ width: `${Math.max(share * 100, 0.6)}%`, opacity: 1 - i * 0.18 }} />
                </div>
              )}
              <p className={cn("mt-2 max-w-prose text-sm leading-relaxed text-graphite",
                isOpen ? "" : "line-clamp-1 group-hover:text-ink")}>
                {t.body}
              </p>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
