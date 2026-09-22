export type Severity = "ok" | "expected" | "review" | "break";

export interface Resolution {
  entity_id: string;
  entity_type: "order" | "txn" | "bank_row" | "settlement" | "statement_gap";
  classification: string;
  tier: number;
  matched_to: string;
  detail: string;
  resolved: boolean;
  amount_paise: number;
  date: string;
  severity: Severity;
}

export interface ClassMetric {
  label: string; tp: number; fp: number; fn: number;
  precision: number; recall: number; f1: number; support: number;
}

export interface Order {
  order_id: string; order_amount_paise: number; currency: string;
  order_datetime: string; customer_id: string; order_status: string; payment_method: string;
}
export interface Txn {
  txn_id: string; txn_type: string; order_ref: string | null; gross_amount_paise: number;
  fee_paise: number; gst_on_fee_paise: number; net_amount_paise: number; txn_datetime: string;
  settlement_id: string | null; payment_method: string; status: string;
}
export interface Settlement {
  settlement_id: string; capture_date: string; payout_date: string; total_paise: number; utr: string | null;
}
export interface BankRow {
  bank_txn_id: string; value_date: string; description: string; credit_paise: number | null;
  debit_paise: number | null; balance_paise: number; utr: string | null; movement_paise: number;
}

export interface Run {
  schema: number;
  source: string;
  generated_at: string;
  engine_ms: number;
  sources: { orders: number; txns: number; settlements: number; bank: number };
  summary: {
    entities: number; resolved: number; unresolved: number; resolution_rate: number;
    resolution_ci: [number, number]; tiers: Record<string, number>;
    by_class: Record<string, number>; by_severity: Partial<Record<Severity, number>>;
    exposure_paise: number;
  };
  grading: null | {
    graded: number; correct: number; accuracy: number; accuracy_ci: [number, number];
    per_class: ClassMetric[]; misclassified: { entity_id: string; expected: string; got: string }[];
  };
  detection: null | {
    total: number; detected: number; named: number; silent: number; detection_rate: number;
    by_class: Record<string, Record<string, number>>; labels: Record<string, Record<string, number>>;
    blind_spot_classes: string[];
    outcomes: { entity_id: string; planted: string; emitted: string | null; state: string }[];
  };
  money_flow: {
    nodes: { name: string }[];
    links: { source: number; target: number; value: number }[];
    totals: Record<string, number>;
  };
  daily: { date: string; captured: number; settled: number; banked: number; exceptions: number }[];
  resolutions: Resolution[];
  records: null | { orders: Order[]; txns: Txn[]; settlements: Settlement[]; bank: BankRow[] };
}

export interface DatasetInfo {
  name: string; title: string; blurb: string; entities: number;
  resolution_rate: number; accuracy: number | null; exceptions: number;
}

export interface Meta {
  generated_at: string; commit: string; tests: number; datasets: DatasetInfo[];
  headline: {
    resolution_rate: number; accuracy: number; exceptions: number; entities: number;
    throughput: number; variance_mean: number; detection: string;
  };
}

export interface StressRow {
  scale: number; defect_rate: number; resolution_rate: number; accuracy: number;
  exceptions: number; worst_accuracy: number;
}

export interface Benchmarks {
  variance: { seed: number; entities: number; resolution_rate: number; accuracy: number }[];
  throughput: { orders: number; entities: number; reconcile_seconds: number; entities_per_second: number }[];
  stress_compound: StressRow[];
  stress_density: StressRow[];
  detection: {
    before: { commit: string; detected: number; total: number; silent_classes: string[] };
    after: {
      detected: number; total: number; named: number; silent_classes: string[];
      by_class: Record<string, Record<string, number>>; labels: Record<string, Record<string, number>>;
    };
  };
}

export interface TaxonomyClass { label: string; level: string; severity: Severity; summary: string; real_break: boolean }

export interface Trace {
  entity_id: string; label: string; verdict: string; flag: string;
  steps: { n: number; call: string; result: string }[];
  conclusion: string; analyst_note: string;
}

export interface Traces { source: string; stats: string[]; traces: Trace[] }
