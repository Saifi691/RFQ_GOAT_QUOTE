export type Source = "" | "gmail" | "file" | "api";
export type Status = "processing" | "built" | "replied" | "dry_run" | "skipped" | "failed";

export interface Totals {
  received: number;
  replied: number;
  failed: number;
  skipped: number;
  built: number;
  products: number;
  found: number;
  not_found: number;
  fields_completed: number | null;
  response_s: number | null;
}

export interface DailyPoint {
  day: string;
  received: number;
  replied: number;
}

export interface AgentTotals {
  reviewed: number;
  verified: number;
  critical: number;
  warnings: number;
  fixes_proposed: number;
  fixes_approved: number;
  fixes_pending: number;
}

export interface Metrics {
  totals: Totals;
  sources: { website: number; api: number; pdf: number; catalog: number };
  agent: AgentTotals;
  daily: DailyPoint[];
}

export interface Finding {
  number: number;
  product_id: string;
  field: string;
  verdict: "inferred" | "conflict" | "issue";
  severity: "critical" | "warning" | "info";
  message: string;
  evidence: string | null;
  current_value: string | null;
  proposed_value: string | null;
  proposed_source: string | null;
  found_by: "rules" | "ai";
  decision: "approved" | "rejected" | null;
  decided_at: string | null;
}

export interface AgentSummary {
  values_reviewed?: number;
  verified?: number;
  inferred?: number;
  conflicts?: number;
  issues?: number;
  critical?: number;
  warnings?: number;
  fixes_proposed?: number;
  ai_steps?: number;
}

export interface TraceStep {
  step: number;
  actor: "rules" | "ai";
  tool: string;
  arguments: unknown;
  result: string;
}

export interface RequestRow {
  id: number;
  source: Exclude<Source, "">;
  status: Status;
  message_id: string | null;
  sender: string | null;
  subject: string | null;
  received_at: string;
  replied_at: string | null;
  scrape_mode: string | null;
  quality_mode: string | null;
  products_processed: number | null;
  products_found: number | null;
  products_not_found: number | null;
  fields_completed: number | null;
  warnings: number | null;
  skip_reason: string | null;
  error: string | null;
  has_workbook: number;
  response_s: number | null;
}

export interface ProductRow {
  position: number;
  product_id: string;
  status: "Found" | "Not Found";
  description: string | null;
  fields: number;
  from_website: number;
  from_api: number | null;
  from_pdf: number;
  from_catalog: number;
  notes: number;
}

export interface RequestDetail extends RequestRow {
  message_id: string | null;
  reply_message_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  products: ProductRow[];
  findings: Finding[];
  agent_summary: AgentSummary;
  has_trace: number;
}

export interface Preset {
  id: string;
  label: string;
  subject: string;
  body: string;
  attach: boolean;
}

export interface SimulationConfig {
  enabled: boolean;
  problems: string[];
  sender: string | null;
  recipient: string | null;
  presets: Preset[];
  attachment: string;
}

export interface SimulationSent {
  message_id: string;
  from: string;
  to: string;
  subject: string;
  attached: boolean;
  sent_at: string;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(path, { headers: { Accept: "application/json" } }));
}

function query(source: Source, days: number) {
  const params = new URLSearchParams({ days: String(days) });
  if (source) params.set("source", source);
  return params.toString();
}

export const api = {
  metrics: (source: Source, days: number) => get<Metrics>(`/api/metrics?${query(source, days)}`),
  requests: (source: Source, days: number) => get<RequestRow[]>(`/api/requests?${query(source, days)}&limit=200`),
  request: (id: number) => get<RequestDetail>(`/api/requests/${id}`),
  workbookUrl: (id: number) => `/api/requests/${id}/rfq.xlsx`,
  byMessageId: (messageId: string) =>
    get<RequestRow[]>(`/api/requests?days=2&limit=5&message_id=${encodeURIComponent(messageId)}`),
  trace: (id: number) => get<TraceStep[]>(`/api/requests/${id}/trace`),
  decide: async (id: number, number: number, decision: "approve" | "reject") =>
    parse<Finding>(await fetch(`/api/requests/${id}/findings/${number}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ decision }),
    })),
  simulationConfig: () => get<SimulationConfig>("/api/simulate/config"),
  simulate: async (subject: string, body: string, attach: boolean) =>
    parse<SimulationSent>(await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ subject, body, attach }),
    })),
};
