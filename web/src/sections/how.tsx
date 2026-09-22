import { blob } from "./links";

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

export function HowItWorks() {
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

        <ol className="mt-10 grid gap-x-8 gap-y-8 md:grid-cols-2 xl:grid-cols-4">
          {TIERS.map((t, i) => (
            <li key={t.name} className="border-t-2 border-ink pt-4">
              <div className="num font-serif text-sm text-graphite">Tier {i}</div>
              <h3 className="mt-1 text-xl font-medium">{t.name}</h3>
              <p className="mt-2 text-sm leading-relaxed text-graphite">{t.body}</p>
            </li>
          ))}
        </ol>

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
