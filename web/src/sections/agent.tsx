import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { live, snapshot, type AskResponse, type InvestigateResponse } from "@/lib/api";
import { cn, human } from "@/lib/utils";
import type { EngineState } from "@/hooks/use-engine";
import { useData } from "@/hooks/use-data";
import { Button } from "@/components/ui/button";
import { Panel, Skeleton } from "@/components/ui/panel";
import type { Health } from "@/lib/api";

export function AgentSection({ engine }: { engine: { state: EngineState; health: Health | null } }) {
  const traces = useData(snapshot.traces);
  const reference = useData(() => snapshot.dataset("01-reference"));
  const [pick, setPick] = useState(0);

  const matcher = useMemo(() => new Map(reference.data?.resolutions.map((r) => [r.entity_id, r.classification]) ?? []), [reference.data]);
  const stats = useMemo(() => {
    const s = traces.data?.stats ?? [];
    const out: { label: string; value: string; note: string }[] = [];
    for (let i = 0; i + 2 < s.length; i += 3) out.push({ label: s[i], value: s[i + 1], note: s[i + 2] });
    return out;
  }, [traces.data]);
  const t = traces.data?.traces[pick];

  return (
    <section id="agent" className="border-b border-rule">
      <div className="mx-auto max-w-page px-5 py-16 sm:px-8 lg:py-20">
        <div className="max-w-prose">
          <h2 className="text-3xl font-medium">The agent proposes; code decides</h2>
          <p className="mt-3 text-graphite">
            Records the deterministic tiers cannot close go to a bounded agent. It chooses which of nine investigation tools to call,
            at most five rounds per record, and must cite a tool result for any claim. It performs no arithmetic. If it invents a class
            outside the taxonomy it is downgraded, and if it claims a resolution without evidence it is overruled. A model failure turns an
            exception into an escalation, never into a wrong number.
          </p>
        </div>

        {stats.length > 0 && (
          <dl className="totals mt-8 grid grid-cols-2 gap-6 py-5 sm:grid-cols-4">
            {stats.map((s) => (
              <div key={s.label}>
                <dt className="text-sm text-graphite">{s.label}</dt>
                <dd className="num mt-1 font-serif text-[1.75rem] leading-none">{s.value}</dd>
                <dd className="mt-2 text-xs text-graphite">{s.note}</dd>
              </div>
            ))}
          </dl>
        )}

        <div className="mt-8 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <Panel title="Recorded investigations" className="lg:max-h-[36rem] lg:overflow-y-auto">
            {!traces.data ? <Skeleton className="h-64" /> : (
              <ul className="space-y-1" role="listbox" aria-label="Investigated records">
                {traces.data.traces.map((tr, i) => {
                  const disagree = tr.flag.includes("disagree");
                  return (
                    <li key={tr.entity_id}>
                      <button role="option" aria-selected={i === pick} onClick={() => setPick(i)}
                        className={cn("w-full rounded px-3 py-2 text-left text-sm", i === pick ? "bg-ink text-paper" : "hover:bg-ink/[0.05]")}>
                        <span className="font-mono text-[0.8rem]">{tr.entity_id}</span>
                        <span className={cn("block text-xs", i === pick ? "text-paper/80" : disagree ? "text-pencil" : "text-graphite")}>
                          {human(tr.label)}{disagree && ", disagreed"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel title={t ? <span className="font-mono text-base">{t.entity_id}</span> : "Trace"}
            action={t && <span className="text-sm text-graphite">{t.verdict}</span>}>
            {!t ? <Skeleton className="h-64" /> : (
              <div className="space-y-5 text-sm">
                <p className="text-graphite">
                  Engine said <span className="text-ink">{human(matcher.get(t.entity_id) ?? "unknown")}</span>; the agent concluded{" "}
                  <span className={cn(t.flag.includes("disagree") ? "text-pencil" : "text-ink")}>{human(t.label)}</span>
                  {t.flag.includes("disagree") ? ". They disagree, and the engine's answer stands; the disagreement is kept for a person to read." : ", independently."}
                </p>
                <ol className="space-y-2">
                  {t.steps.map((s) => (
                    <li key={s.n} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-2">
                      <span className="num text-graphite">{s.n}</span>
                      <div>
                        <code className="break-all font-mono text-[0.8rem] text-tick">{s.call}</code>
                        <div className="text-graphite">{s.result}</div>
                      </div>
                    </li>
                  ))}
                </ol>
                <div>
                  <h4 className="font-serif text-base font-medium">Conclusion</h4>
                  <p className="mt-1 max-w-prose leading-relaxed">{t.conclusion}</p>
                </div>
                {t.analyst_note && (
                  <div className="rounded border-l-2 border-pencil bg-pencil/[0.07] px-4 py-3">
                    <h4 className="font-medium">For the analyst</h4>
                    <p className="mt-1 max-w-prose leading-relaxed text-graphite">{t.analyst_note}</p>
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>

        <LivePanel engine={engine} />
      </div>
    </section>
  );
}

function LivePanel({ engine }: { engine: { state: EngineState; health: Health | null } }) {
  const [key, setKey] = useState("");
  const [question, setQuestion] = useState("How much did refunds and chargebacks cost this batch?");
  const [busy, setBusy] = useState<"inv" | "ask" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inv, setInv] = useState<InvestigateResponse | null>(null);
  const [ans, setAns] = useState<AskResponse | null>(null);
  const isLive = engine.state === "live";
  const canRun = isLive && (engine.health?.model_configured || key.trim().length > 0);

  async function run<T>(kind: "inv" | "ask", job: () => Promise<T>, set: (v: T) => void) {
    setBusy(kind); setError(null);
    try { set(await job()); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <Panel className="mt-6" title="Run it yourself"
      note="These call a language model on the sample batch. Your key, if you give one, is sent with that one request, used by a single client and never stored or logged. Requests on the server's key are rate limited.">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <label className="block text-sm font-medium" htmlFor="key">Anthropic API key</label>
          <p className="text-xs text-graphite">{engine.health?.model_configured ? "Optional: the server has a key configured." : "Required: the server has no model configured."}</p>
          <input id="key" type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)}
            placeholder="sk-ant-..." className="mt-2 h-10 w-full rounded border border-rule bg-paper px-3 font-mono text-sm" />
          <Button className="mt-4" variant="outline" disabled={!canRun || !!busy}
            onClick={() => run("inv", () => live.investigate(key.trim() || undefined), setInv)}>
            {busy === "inv" && <Loader2 size={16} className="animate-spin" />} Investigate three exceptions
          </Button>
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="q">Ask about the settlement data</label>
          <p className="text-xs text-graphite">Answered only from aggregate query results. This layer's rules live in the prompt, so its guarantee is weaker.</p>
          <textarea id="q" rows={2} maxLength={400} value={question} onChange={(e) => setQuestion(e.target.value)}
            className="mt-2 w-full rounded border border-rule bg-paper px-3 py-2 text-sm" />
          <Button className="mt-3" variant="outline" disabled={!canRun || !question.trim() || !!busy}
            onClick={() => run("ask", () => live.ask(question.trim(), key.trim() || undefined), setAns)}>
            {busy === "ask" && <Loader2 size={16} className="animate-spin" />} Ask
          </Button>
        </div>
      </div>
      {!isLive && <p className="mt-4 text-sm text-pencil">The live engine is not reachable right now, so only the recorded investigations above are available.</p>}
      {error && <p role="alert" className="mt-4 text-sm text-redink">{error}</p>}
      {ans && (
        <div className="mt-5 rounded border border-rule p-4 text-sm">
          <p className="leading-relaxed">{ans.answer || ans.error}</p>
          <p className="mt-2 text-xs text-graphite">Tools used: {ans.tools_used.join(", ") || "none"}. {ans.caveat}</p>
        </div>
      )}
      {inv && (
        <ul className="mt-5 space-y-3 text-sm">
          {inv.investigations.map((i) => (
            <li key={i.entity_id} className="rounded border border-rule p-4">
              <div className="flex flex-wrap justify-between gap-2">
                <span className="font-mono text-[0.8rem]">{i.entity_id}</span>
                <span className={i.agreed ? "text-tick" : "text-pencil"}>
                  engine {human(i.matcher_said)}, agent {human(i.agent_said)}
                </span>
              </div>
              <p className="mt-2 leading-relaxed text-graphite">{i.reasoning}</p>
              <p className="mt-1 text-xs text-graphite">{i.steps.length} tool calls via {inv.provider}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
