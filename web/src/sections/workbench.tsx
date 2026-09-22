import { Loader2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { live, snapshot } from "@/lib/api";
import type { Meta, Run } from "@/lib/types";
import { cn, int, pct } from "@/lib/utils";
import type { Engine } from "@/hooks/use-engine";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/panel";
import { RunView } from "@/sections/run/run-view";
import { blob } from "./links";

type Mode = "recorded" | "generate" | "upload";

export function Workbench({ engine, meta, run, onRun }: {
  engine: Engine; meta: Meta | null; run: Run | null; onRun: (r: Run) => void;
}) {
  const [mode, setMode] = useState<Mode>("recorded");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const isLive = engine.state === "live";
  const starting = engine.state === "checking" || engine.state === "waking";

  async function go(label: string, job: () => Promise<Run>, needsEngine = false) {
    setBusy(label); setError(null);
    try {
      // A sleeping instance should not mean a dead button: take the request
      // now, wait for the engine to answer, then run it.
      if (needsEngine && !isLive) {
        setQueued(true);
        await engine.whenLive();
      }
      onRun(await job());
      document.getElementById("run")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null); setQueued(false);
    }
  }

  return (
    <section id="workbench" className="border-b border-rule">
      <div className="mx-auto max-w-page px-5 py-16 sm:px-8 lg:py-20">
        <div className="max-w-prose">
          <h2 className="text-3xl font-medium">Workbench</h2>
          <p className="mt-3 text-graphite">
            Pick a batch, generate one, or upload your own three files. Every chart and table below
            comes from the engine's output for that batch; nothing is computed in the browser except layout.
          </p>
        </div>

        <div className="mt-8">
          <Segmented label="Data source" value={mode} onChange={(m) => { setMode(m); setError(null); }}
            options={[
              { value: "recorded", label: "Sample batches" },
              { value: "generate", label: "Generate a batch" },
              { value: "upload", label: "Upload your CSVs" },
            ]} />
        </div>

        <div className="mt-6">
          {mode === "recorded" && (
            <DatasetList meta={meta} current={run?.source} busy={busy}
              onPick={(name) => go(name, () => (isLive ? live.dataset(name).catch(() => snapshot.dataset(name)) : snapshot.dataset(name)))} />
          )}
          {mode === "generate" && <Generate disabled={engine.state === "offline"} busy={busy} engine={engine}
            onGenerate={(p) => go("generate", () => live.sample(p), true)} />}
          {mode === "upload" && <UploadForm disabled={engine.state === "offline"} busy={busy} engine={engine}
            onUpload={(files) => go("upload", () => live.reconcile(files), true)} />}
          {queued && starting && (
            <p aria-live="polite" className="mt-4 max-w-prose rounded border border-pencil/40 bg-pencil/[0.07] px-4 py-3 text-sm text-pencil">
              Held until the engine answers. It sleeps when nobody has used it for a quarter of an hour and takes
              30 to 60 seconds to start; this runs by itself as soon as it does.
            </p>
          )}
          {error && (
            <p role="alert" className="mt-4 max-w-prose rounded border border-redink/40 bg-redink/[0.06] px-4 py-3 text-sm text-redink">
              {error}
            </p>
          )}
        </div>

        <div id="run" className="mt-12 scroll-mt-20">
          {run ? <RunView run={run} meta={meta} /> : <Skeleton className="h-96 w-full" />}
        </div>
      </div>
    </section>
  );
}

function DatasetList({ meta, current, busy, onPick }: {
  meta: Meta | null; current?: string; busy: string | null; onPick: (name: string) => void;
}) {
  if (!meta) return <Skeleton className="h-48 w-full" />;
  return (
    <div className="scroll-x rounded-lg border border-rule bg-sheet">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-graphite">
            <th className="px-4 py-2.5 font-medium">Batch</th>
            <th className="py-2.5 font-medium">What it shows</th>
            <th className="py-2.5 text-right font-medium">Entities</th>
            <th className="py-2.5 text-right font-medium">Resolved</th>
            <th className="py-2.5 pr-4 text-right font-medium">Correct</th>
          </tr>
        </thead>
        <tbody>
          {meta.datasets.map((d) => {
            const active = current === d.name;
            return (
              <tr key={d.name} className={cn("border-b border-rule/60 last:border-0", active && "bg-tick/[0.07]")}>
                <td className="px-4 py-2">
                  <button onClick={() => onPick(d.name)} disabled={!!busy} aria-pressed={active}
                    className="inline-flex items-center gap-2 font-medium text-ink underline decoration-rule decoration-1 underline-offset-4 hover:decoration-ink disabled:opacity-60">
                    {busy === d.name && <Loader2 size={14} className="animate-spin" />}
                    {d.title}
                  </button>
                </td>
                <td className="py-2 pr-4 text-graphite">{d.blurb}</td>
                <td className="num py-2 text-right">{int(d.entities)}</td>
                <td className="num py-2 text-right">{pct(d.resolution_rate)}</td>
                <td className="num py-2 pr-4 text-right">{d.accuracy == null ? "n/a" : pct(d.accuracy)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OfflineNote({ engine }: { engine: Engine }) {
  if (engine.state === "live") return null;
  const seconds = Math.round(engine.waitedMs / 1000);
  if (engine.state === "offline") {
    return (
      <p className="mt-3 max-w-prose text-sm text-pencil">
        The engine is not answering, so the recorded batches above are all this page can show.{" "}
        <button onClick={engine.retry} className="underline underline-offset-2">Try again</button>, or run it
        locally: <code className="font-mono text-xs">pip install -r requirements-web.txt</code>, then uvicorn.
      </p>
    );
  }
  return (
    <p className="mt-3 max-w-prose text-sm text-graphite">
      {engine.state === "waking"
        ? `Starting the engine${seconds > 2 ? ` (${seconds}s)` : ""}. Press anyway: the request waits and runs on its own.`
        : "Checking for the engine. Press anyway; the request will wait."}
    </p>
  );
}

function Generate({ disabled, busy, engine, onGenerate }: {
  disabled: boolean; busy: string | null; engine: Engine;
  onGenerate: (p: { seed: number; orders: number; defect_scale: number; compound: boolean }) => void;
}) {
  const [seed, setSeed] = useState(42);
  const [orders, setOrders] = useState(120);
  const [scale, setScale] = useState(1);
  const [compound, setCompound] = useState(false);

  return (
    <div className="rounded-lg border border-rule bg-sheet p-5 sm:p-6">
      <p className="max-w-prose text-sm text-graphite">
        The generator plants known defects and writes an answer key alongside, so a generated batch is graded as well as reconciled.
        Raise the defect rate to watch the resolution rate fall; allow compound defects to watch accuracy fall.
      </p>
      <div className="mt-5 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Seed" hint="Same seed, same batch">
          <input type="number" min={0} max={1000000} value={seed} onChange={(e) => setSeed(Number(e.target.value))}
            className="num h-10 w-full rounded border border-rule bg-paper px-3" />
        </Field>
        <Field label={`Orders: ${orders}`} hint="20 to 2,000">
          <input type="range" min={20} max={2000} step={20} value={orders} onChange={(e) => setOrders(Number(e.target.value))}
            className="w-full accent-[rgb(var(--tick))]" />
        </Field>
        <Field label={`Defect rate: ×${scale}`} hint="Multiplies every planted defect">
          <input type="range" min={0} max={6} step={0.5} value={scale} onChange={(e) => setScale(Number(e.target.value))}
            className="w-full accent-[rgb(var(--tick))]" />
        </Field>
        <Field label="Compound defects" hint="Several defects on one record">
          <label className="flex h-10 items-center gap-2 text-sm">
            <input type="checkbox" checked={compound} onChange={(e) => setCompound(e.target.checked)}
              className="h-4 w-4 accent-[rgb(var(--tick))]" />
            Allow
          </label>
        </Field>
      </div>
      <Button className="mt-6" disabled={disabled || !!busy}
        onClick={() => onGenerate({ seed, orders, defect_scale: scale, compound })}>
        {busy === "generate" && <Loader2 size={16} className="animate-spin" />}
        {busy === "generate" && engine.state !== "live" ? "Waiting for the engine" : "Generate and reconcile"}
      </Button>
      <OfflineNote engine={engine} />
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-sm font-medium">{label}</div>
      <div className="mb-2 text-xs text-graphite">{hint}</div>
      {children}
    </div>
  );
}

const FILES = [
  { name: "ledger", required: true, cols: "order_id, order_amount_paise, currency, order_datetime, customer_id, order_status, payment_method" },
  { name: "gateway", required: true, cols: "txn_id, txn_type, order_ref, gross_amount_paise, fee_paise, gst_on_fee_paise, net_amount_paise, txn_datetime, settlement_id, payment_method, status" },
  { name: "bank", required: true, cols: "bank_txn_id, value_date, description, credit_paise, debit_paise, balance_paise, utr" },
  { name: "settlements", required: false, cols: "settlement_id, capture_date, payout_date, total_paise, utr" },
  { name: "ground_truth", required: false, cols: "entity_id, entity_type, expected_classification, expected_match_target, notes" },
];

function UploadForm({ disabled, busy, engine, onUpload }: {
  disabled: boolean; busy: string | null; engine: Engine; onUpload: (f: Record<string, File>) => void;
}) {
  const [files, setFiles] = useState<Record<string, File>>({});
  const formRef = useRef<HTMLDivElement>(null);
  const ready = FILES.filter((f) => f.required).every((f) => files[f.name]);

  return (
    <div ref={formRef} className="rounded-lg border border-rule bg-sheet p-5 sm:p-6">
      <p className="max-w-prose text-sm text-graphite">
        Amounts are integer paise (45000 means ₹450.00). Files are reconciled in memory and deleted with the response; nothing is stored.
        To try it without your own books, download a set from{" "}
        <a className="underline underline-offset-2" href={blob("datasets/01-reference")}>datasets/01-reference</a>.
      </p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        {FILES.map((f) => (
          <label key={f.name} className="block">
            <span className="text-sm font-medium">{f.name}.csv</span>
            <span className="ml-2 text-xs text-graphite">{f.required ? "required" : "optional"}</span>
            <span className="mt-0.5 block text-xs leading-snug text-graphite">{f.cols}</span>
            <span className={cn("mt-2 flex h-10 items-center gap-2 rounded border border-dashed px-3 text-sm",
              files[f.name] ? "border-tick/60 text-ink" : "border-rule text-graphite")}>
              <Upload size={15} aria-hidden />
              <span className="truncate">{files[f.name]?.name ?? "Choose a file"}</span>
              <input type="file" accept=".csv,text/csv" className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  setFiles((prev) => {
                    const next = { ...prev };
                    if (file) next[f.name] = file; else delete next[f.name];
                    return next;
                  });
                }} />
            </span>
          </label>
        ))}
      </div>
      <Button className="mt-6" disabled={disabled || !ready || !!busy} onClick={() => onUpload(files)}>
        {busy === "upload" && <Loader2 size={16} className="animate-spin" />}
        {busy === "upload" && engine.state !== "live" ? "Waiting for the engine" : "Reconcile these files"}
      </Button>
      {!ready && <p className="mt-2 text-xs text-graphite">Choose the ledger, gateway and bank files to continue.</p>}
      <OfflineNote engine={engine} />
    </div>
  );
}
