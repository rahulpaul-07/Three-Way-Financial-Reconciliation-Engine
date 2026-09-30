import { BlurFade } from "@/components/ui/blur-fade";
import { SectionHeader } from "@/components/ui/section-header";
import { blob } from "./links";

// Stances are not a sequence, so they are not numbered.
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

export function Principles() {
  return (
    <section id="principles">
      <div className="mx-auto max-w-page px-5 py-20 sm:px-8 lg:py-28">
        <SectionHeader folio="05" eyebrow="Principles" title="Three stances, and the rules of the domain.">
          The reasoning behind each choice, and what was rejected, is in{" "}
          <a className="underline decoration-rule underline-offset-4 hover:text-ink" href={blob("DECISIONS.md")}>DECISIONS.md</a>;
          what broke during the build and how it was fixed, in{" "}
          <a className="underline decoration-rule underline-offset-4 hover:text-ink" href={blob("NOTES.md")}>NOTES.md</a>.
        </SectionHeader>

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {STANCES.map((s, i) => (
            <BlurFade key={s.title} delay={i * 0.08}
              className="flex flex-col engraved bg-sheet p-6">
              <h3 className="font-serif text-xl font-medium leading-snug">{s.title}</h3>
              <p className="mt-3 leading-relaxed text-graphite">{s.body}</p>
            </BlurFade>
          ))}
        </div>

        <BlurFade className="mt-14 grid gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div>
            <h3 className="text-2xl font-medium">Domain rules encoded</h3>
            <p className="mt-3 max-w-prose leading-relaxed text-graphite">
              Each is enforced in the engine's code rather than left to convention. A single hardcoded fee rate, for example,
              would be wrong on three of the four payment methods.
            </p>
          </div>
          <ul className="ruled rounded-lg border border-rule bg-sheet px-5 text-[0.95rem] leading-8">
            {RULES.map((r) => (
              <li key={r} className="flex gap-3">
                <span aria-hidden className="text-tick">✓</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </BlurFade>
      </div>
    </section>
  );
}
