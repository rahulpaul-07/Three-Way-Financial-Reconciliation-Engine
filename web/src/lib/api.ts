import type { Benchmarks, Meta, Run, TaxonomyClass, Traces } from "./types";

// Where the live engine is. Empty means same origin (the dashboard served by
// FastAPI on Render). The GitHub Pages build sets this to the Render URL.
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
const DATA = `${import.meta.env.BASE_URL}data`;

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit, timeoutMs = 45_000): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctl.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(body?.detail ?? `Request failed (${res.status})`, res.status);
    return body as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as Error).name === "AbortError") {
      throw new ApiError("The engine took too long to answer. A free-tier instance may still be waking up; try again in a moment.");
    }
    throw new ApiError("Could not reach the engine. Check your connection, or use a recorded batch.");
  } finally {
    clearTimeout(timer);
  }
}

// ---- recorded snapshots (always available) --------------------------------
export const snapshot = {
  meta: () => request<Meta>(`${DATA}/meta.json`),
  benchmarks: () => request<Benchmarks>(`${DATA}/benchmarks.json`),
  taxonomy: () => request<{ classes: TaxonomyClass[] }>(`${DATA}/taxonomy.json`),
  traces: () => request<Traces>(`${DATA}/agent_traces.json`),
  dataset: (name: string) => request<Run>(`${DATA}/datasets/${name}.json`),
};

// ---- live engine -----------------------------------------------------------
export interface Health { status: string; version: string; model_configured: boolean }

export const live = {
  health: (timeoutMs = 5000) => request<Health>(`${API_BASE}/api/v1/health`, undefined, timeoutMs),
  dataset: (name: string) =>
    request<Run>(`${API_BASE}/api/v1/datasets/${encodeURIComponent(name)}`, { method: "POST" }),
  sample: (params: { seed: number; orders: number; defect_scale: number; compound: boolean }) =>
    request<Run>(`${API_BASE}/api/v1/sample`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
    }),
  reconcile: (files: Record<string, File>) => {
    const form = new FormData();
    for (const [name, file] of Object.entries(files)) form.append(name, file);
    return request<Run>(`${API_BASE}/api/v1/reconcile`, { method: "POST", body: form }, 90_000);
  },
  investigate: (key?: string) =>
    request<InvestigateResponse>(`${API_BASE}/api/v1/investigate`, {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { "x-api-key": key } : {}) },
      body: "{}",
    }, 180_000),
  ask: (question: string, key?: string) =>
    request<AskResponse>(`${API_BASE}/api/v1/ask`, {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { "x-api-key": key } : {}) },
      body: JSON.stringify({ question }),
    }, 120_000),
};

export interface InvestigateResponse {
  provider: string; capped_at: number; source: string;
  investigations: {
    entity_id: string; matcher_said: string; agent_said: string; agreed: boolean;
    reasoning: string; analyst_note: string; terminated: string;
    steps: { n: number; tool: string; input: Record<string, unknown>; ok: boolean; summary: string }[];
  }[];
}

export interface AskResponse {
  question: string; answer: string; error: string | null; tools_used: string[];
  model_calls: number; source: string; caveat: string;
}
